from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Lock
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from app.config import settings
from app.models import (
    BacktestParams,
    BacktestProgress,
    BacktestRecordSummary,
    BacktestResponse,
    BacktestStartResponse,
    DataInfo,
    MinuteResponse,
    SelectionResponse,
    StockWindowDay,
    StockWindowResponse,
    StrategyParams,
)
from app.services.backtest import run_backtest
from app.services.data import data_info, minute_bars_response
from app.services.data import index_minute_bars_response, resolve_stock_query, stock_window_response
from app.services.records import delete_backtest_record, list_backtest_records, load_backtest_record, save_backtest_record
from app.services.strategy import select_for_date

router = APIRouter()

# A tiny in-memory job store is enough for local desktop use. The UI starts a
# backtest, polls this store, and displays progress while the worker thread runs.
# If this app later becomes multi-user or multi-process, replace this with Redis
# or a database-backed task table.
_executor = ThreadPoolExecutor(max_workers=1)
_jobs: dict[str, BacktestProgress] = {}
_jobs_lock = Lock()


def _save_job(job: BacktestProgress) -> None:
    """Update a job atomically so polling never reads a half-written object."""
    with _jobs_lock:
        _jobs[job.job_id] = job


def _get_job(job_id: str) -> BacktestProgress | None:
    with _jobs_lock:
        return _jobs.get(job_id)


def _resolve_index_query(query: str) -> str:
    """Map common big-market labels to the configured benchmark index code."""
    q = query.strip().upper()
    if not q or q in {"大盘", "沪深300", "HS300", "000300", "000300.SH"}:
        return settings.benchmark_code
    if q.isdigit() and "." not in q:
        return f"{q}.SH" if q.startswith("0") else q
    # When the frontend has just switched from stock to index, it may briefly
    # still hold a stock name. Treat non-code text as the default big market.
    if not any(ch.isdigit() for ch in q):
        return settings.benchmark_code
    return q


@router.get("/data/info", response_model=DataInfo)
async def get_data_info():
    """Inspect local files under D:/股票数据."""
    return await run_in_threadpool(data_info)


@router.post("/select/run", response_model=SelectionResponse)
async def run_selection(
    trade_date: date = Query(...),
    params: StrategyParams | None = None,
):
    """Run article-rule stock selection for one trading day."""
    try:
        return await run_in_threadpool(select_for_date, trade_date, params or StrategyParams())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/backtest/run", response_model=BacktestResponse)
async def run_backtest_api(params: BacktestParams):
    """Synchronous fallback endpoint kept for scripts and quick smoke tests."""
    try:
        result = await run_in_threadpool(run_backtest, params)
        await run_in_threadpool(save_backtest_record, result)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/backtest/start", response_model=BacktestStartResponse)
async def start_backtest(params: BacktestParams):
    """Start a background backtest and return a job id for progress polling."""
    job_id = uuid4().hex
    _save_job(BacktestProgress(job_id=job_id, status="queued", percent=0, stage="排队中"))

    def worker() -> None:
        def report(percent: int, stage: str, current_date: str | None) -> None:
            _save_job(BacktestProgress(
                job_id=job_id,
                status="running",
                percent=percent,
                stage=stage,
                current_date=current_date,
            ))

        try:
            report(1, "开始回测", None)
            result = run_backtest(params, progress=report)
            save_backtest_record(result)
            _save_job(BacktestProgress(
                job_id=job_id,
                status="done",
                percent=100,
                stage="完成",
                result=result,
            ))
        except Exception as exc:
            _save_job(BacktestProgress(
                job_id=job_id,
                status="error",
                percent=100,
                stage="失败",
                error=str(exc),
            ))

    _executor.submit(worker)
    return BacktestStartResponse(job_id=job_id)


@router.get("/backtest/progress/{job_id}", response_model=BacktestProgress)
async def get_backtest_progress(job_id: str):
    """Poll a background backtest job."""
    job = _get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="回测任务不存在")
    return job


@router.get("/backtest/records", response_model=list[BacktestRecordSummary])
async def get_backtest_records():
    """Return saved backtest records for the UI history table."""
    return await run_in_threadpool(list_backtest_records)


@router.get("/backtest/records/{record_id}", response_model=BacktestResponse)
async def get_backtest_record(record_id: str):
    """Load one saved backtest result."""
    try:
        return await run_in_threadpool(load_backtest_record, record_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="回测记录不存在")


@router.delete("/backtest/records/{record_id}")
async def remove_backtest_record(record_id: str):
    """Delete one saved local backtest record."""
    try:
        await run_in_threadpool(delete_backtest_record, record_id)
        return {"ok": True}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="回测记录不存在")


@router.get("/stocks/{code}/minute", response_model=MinuteResponse)
async def get_stock_minute(code: str, trade_date: date = Query(...)):
    """Return 15-minute bars and VWAP for frontend visual inspection."""
    bars = await run_in_threadpool(minute_bars_response, code, str(trade_date))
    return MinuteResponse(code=code, trade_date=str(trade_date), bars=bars)


@router.get("/stocks/{code}/window", response_model=StockWindowResponse)
async def get_stock_window(
    code: str,
    center_date: date = Query(...),
    radius: int = Query(default=5, ge=1, le=20),
    freq: str = Query(default="1min", pattern="^(1min|5min|15min|30min|60min)$"),
    name: str | None = Query(default=None),
):
    """Return a stock's minute charts for center_date +/- radius trading days."""
    days = await run_in_threadpool(stock_window_response, code, str(center_date), radius, freq)
    return StockWindowResponse(
        code=code.upper(),
        name=name,
        center_date=str(center_date),
        days=[StockWindowDay(trade_date=day, bars=bars) for day, bars in days],
    )


@router.get("/minute/detail", response_model=MinuteResponse)
async def get_minute_detail(
    query: str = Query(..., description="股票名称/代码，或指数代码；大盘可填 沪深300/大盘"),
    trade_date: date = Query(...),
    asset_type: str = Query(default="stock", pattern="^(stock|index)$"),
    freq: str = Query(default="1min", pattern="^(1min|5min|15min|30min|60min)$"),
):
    """Query any stock or benchmark minute chart for the data page.

    Stocks can be looked up by code or name. Index queries default to沪深300
    when the user enters 大盘/沪深300; otherwise an explicit index code is used.
    """
    try:
        if asset_type == "index":
            code = _resolve_index_query(query)
            bars = await run_in_threadpool(index_minute_bars_response, code, str(trade_date), freq)
        else:
            code = await run_in_threadpool(resolve_stock_query, query)
            bars = await run_in_threadpool(minute_bars_response, code, str(trade_date), freq)
        return MinuteResponse(code=code, trade_date=str(trade_date), bars=bars)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
