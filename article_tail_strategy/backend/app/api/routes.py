from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Event, Lock
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
    OptimizationParams,
    OptimizationProgress,
    OptimizationRecord,
    OptimizationRecordSummary,
    OptimizationStartResponse,
    SelectionResponse,
    StockWindowDay,
    StockWindowResponse,
    StrategyParams,
)
from app.services.backtest import run_backtest
from app.services.data import data_info, minute_bars_response
from app.services.data import index_minute_bars_response, resolve_stock_query, stock_window_response
from app.services.optimizer import run_parameter_sweep
from app.services.optimization_records import (
    append_optimization_result,
    create_optimization_record,
    list_optimization_records,
    load_optimization_record,
    update_optimization_progress,
)
from app.services.records import delete_backtest_record, list_backtest_records, load_backtest_record, save_backtest_record
from app.services.strategy import select_for_date

router = APIRouter()

# 本项目目前是本机桌面工具，不是多用户服务，所以后台任务状态先存在内存里。
# 前端启动回测后拿到任务编号，然后轮询进度接口读取这里的状态。
# 如果以后改成多人网页服务，或者后端开多个服务进程，这里需要换成
# 外部缓存或数据库任务表，否则不同进程之间看不到彼此的内存状态。
_executor = ThreadPoolExecutor(max_workers=1)
_jobs: dict[str, BacktestProgress] = {}
_jobs_lock = Lock()

# 参数优化任务单独用一个线程池管理。注意这里的线程不是用来跑回测计算的，
# 它只负责“启动优化器、接收进度回调、更新内存状态”。真正耗处理器的部分
# 在参数优化服务里用多进程执行。
_opt_executor = ThreadPoolExecutor(max_workers=1)
_opt_jobs: dict[str, OptimizationProgress] = {}
_opt_cancel_events: dict[str, Event] = {}
_opt_jobs_lock = Lock()


def _save_job(job: BacktestProgress) -> None:
    """原子更新回测任务状态，避免前端轮询时读到写一半的数据。"""
    with _jobs_lock:
        _jobs[job.job_id] = job


def _get_job(job_id: str) -> BacktestProgress | None:
    with _jobs_lock:
        return _jobs.get(job_id)


def _save_opt_job(job: OptimizationProgress) -> None:
    """原子更新参数优化任务状态，供轮询接口读取。"""
    with _opt_jobs_lock:
        _opt_jobs[job.job_id] = job


def _get_opt_job(job_id: str) -> OptimizationProgress | None:
    with _opt_jobs_lock:
        return _opt_jobs.get(job_id)


def _resolve_index_query(query: str) -> str:
    """把前端输入的大盘名称或指数代码统一转换成指数标准代码。

    数据查看页允许用户输入“大盘、沪深300、000300”等自然语言或代码。
    这里统一归一化到 settings.benchmark_code，后续读取分钟数据时就不需要
    每个调用点重复判断。
    """
    q = query.strip().upper()
    if not q or q in {"大盘", "沪深300", "HS300", "000300", "000300.SH"}:
        return settings.benchmark_code
    if q.isdigit() and "." not in q:
        return f"{q}.SH" if q.startswith("0") else q
    # 当前端刚从股票切换到指数时，输入框里可能还残留股票名称。
    # 对不含数字的文本统一按默认大盘指数处理，避免因为旧股票名导致指数查询失败。
    if not any(ch.isdigit() for ch in q):
        return settings.benchmark_code
    return q


@router.get("/data/info", response_model=DataInfo)
async def get_data_info():
    # 读取本机数据目录概况，供前端展示数据是否齐全。
    """检查 D:/股票数据 下的本地行情文件是否齐全。"""
    return await run_in_threadpool(data_info)


@router.post("/select/run", response_model=SelectionResponse)
async def run_selection(
    trade_date: date = Query(...),
    params: StrategyParams | None = None,
):
    # 单日选股接口只回答“当天能选出哪些股票”，不做资金、持仓和卖出模拟。
    # 适合调试策略规则是否过严，或者查看候选股被哪条规则淘汰。
    """按文章规则执行某一个交易日的选股。"""
    try:
        return await run_in_threadpool(select_for_date, trade_date, params or StrategyParams())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/backtest/run", response_model=BacktestResponse)
async def run_backtest_api(params: BacktestParams):
    # 同步回测接口主要给脚本、测试和冒烟验证使用；前端长回测默认走异步接口。
    """同步回测接口，保留给脚本和快速冒烟测试使用。"""
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
    # 启动后台回测，并立即返回任务编号。前端随后通过进度接口
    # 轮询进度，这样完整回测不会阻塞网络请求。
    """启动后台回测任务，并返回用于轮询进度的任务编号。"""
    job_id = uuid4().hex
    _save_job(BacktestProgress(job_id=job_id, status="queued", percent=0, stage="排队中"))

    def worker() -> None:
        def report(percent: int, stage: str, current_date: str | None) -> None:
            # 回测函数每处理一段交易日会调用这个回调，接口层把它转成可轮询状态。
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
            # 成功完成后保存到本地记录目录，前端“回测记录”表就能重新打开。
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
    # 查询后台回测进度；任务编号只保存在当前后端进程内存中。
    """查询后台回测任务进度。"""
    job = _get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="回测任务不存在")
    return job


@router.post("/optimize/start", response_model=OptimizationStartResponse)
async def start_optimization(params: OptimizationParams):
    # 参数优化可能包含几百到几千组完整回测，不能阻塞网络请求。
    # 这里仅创建任务状态和取消信号，然后把实际工作交给后台线程；
    # 后台线程内部再调用参数优化服务的多进程执行器。
    """启动多进程参数遍历任务，并返回用于轮询进度的任务编号。"""
    job_id = uuid4().hex
    await run_in_threadpool(create_optimization_record, job_id, params)
    _launch_optimization(job_id, params, [])
    return OptimizationStartResponse(job_id=job_id)


def _launch_optimization(job_id: str, params: OptimizationParams, initial_results) -> None:
    cancel_event = Event()
    _opt_cancel_events[job_id] = cancel_event
    _save_opt_job(OptimizationProgress(job_id=job_id, status="queued", percent=0, stage="排队中"))

    def worker() -> None:
        last_completed = 0
        last_total = 0

        # 工作线程负责这个任务的所有状态流转。参数优化服务只知道“调用回调汇报进度”，
        # 不直接依赖网页接口框架，这样优化器可以被测试或命令行脚本复用。
        def report(percent: int, completed: int, total: int, stage: str, best) -> None:
            nonlocal last_completed, last_total
            last_completed = completed
            last_total = total
            current_progress = OptimizationProgress(
                job_id=job_id,
                status="running",
                percent=percent,
                completed=completed,
                total=total,
                stage=stage,
                best=best,
            )
            _save_opt_job(current_progress)
            update_optimization_progress(job_id, current_progress)

        def checkpoint(item) -> None:
            append_optimization_result(job_id, item)

        try:
            report(1, 0, 0, "开始参数优化", [])
            best = run_parameter_sweep(
                params,
                cancel_event=cancel_event,
                progress=report,
                initial_results=initial_results,
                checkpoint=checkpoint,
            )
            if cancel_event.is_set():
                # 如果优化器刚好在结束前收到取消信号，最终状态仍然按取消处理。
                final_progress = OptimizationProgress(
                    job_id=job_id,
                    status="cancelled",
                    percent=100,
                    stage="已取消",
                    completed=last_completed,
                    total=last_total,
                    best=best,
                )
                _save_opt_job(final_progress)
                update_optimization_progress(job_id, final_progress)
                return
            final_progress = OptimizationProgress(
                job_id=job_id,
                status="done",
                percent=100,
                # 已完成数量和总数量使用最后一次真实进度，而不是最优列表长度。
                # 最优列表只是前若干名，不能代表总共跑了多少组。
                completed=last_completed,
                total=last_total,
                stage="完成",
                best=best,
            )
            _save_opt_job(final_progress)
            update_optimization_progress(job_id, final_progress)
        except InterruptedError:
            job = _get_opt_job(job_id)
            final_progress = OptimizationProgress(
                job_id=job_id,
                status="cancelled",
                percent=100,
                stage="已取消",
                completed=job.completed if job else last_completed,
                total=job.total if job else last_total,
                best=job.best if job else [],
            )
            _save_opt_job(final_progress)
            update_optimization_progress(job_id, final_progress)
        except Exception as exc:
            job = _get_opt_job(job_id)
            final_progress = OptimizationProgress(
                job_id=job_id,
                status="error",
                percent=100,
                stage="失败",
                completed=job.completed if job else last_completed,
                total=job.total if job else last_total,
                best=job.best if job else [],
                error=str(exc),
            )
            _save_opt_job(final_progress)
            update_optimization_progress(job_id, final_progress)
        finally:
            # 任务结束后移除取消事件，避免内存里积累已经结束的任务控制对象。
            _opt_cancel_events.pop(job_id, None)

    _opt_executor.submit(worker)


@router.get("/optimize/progress/{job_id}", response_model=OptimizationProgress)
async def get_optimization_progress(job_id: str):
    # 返回当前进度和当前前若干名结果。为了响应体稳定，不返回所有已完成组合。
    """查询参数优化任务进度。"""
    job = _get_opt_job(job_id)
    if job is None:
        try:
            record = await run_in_threadpool(load_optimization_record, job_id)
            return record.progress
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="参数优化任务不存在")
    return job


@router.get("/optimize/records", response_model=list[OptimizationRecordSummary])
async def get_optimization_records():
    """返回本地保存的参数优化记录摘要列表。"""
    return await run_in_threadpool(list_optimization_records)


@router.get("/optimize/records/{record_id}", response_model=OptimizationRecord)
async def get_optimization_record(record_id: str):
    """读取一条完整参数优化记录。"""
    try:
        return await run_in_threadpool(load_optimization_record, record_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="参数优化记录不存在")


@router.post("/optimize/records/{record_id}/resume", response_model=OptimizationStartResponse)
async def resume_optimization(record_id: str):
    """从本地优化记录继续跑尚未完成的参数组合。"""
    if record_id in _opt_cancel_events:
        return OptimizationStartResponse(job_id=record_id)
    try:
        record = await run_in_threadpool(load_optimization_record, record_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="参数优化记录不存在")
    if record.progress.status == "done":
        _save_opt_job(record.progress)
        return OptimizationStartResponse(job_id=record_id)
    _launch_optimization(record.id, record.request, record.results)
    return OptimizationStartResponse(job_id=record.id)


@router.delete("/optimize/{job_id}")
async def cancel_optimization(job_id: str):
    # 请求取消正在运行的参数优化任务。这里设置取消信号，不直接强杀进程；
    # 优化器循环会定期检查这个信号，并取消尚未启动的任务。
    """请求取消正在运行的参数优化任务。"""
    event = _opt_cancel_events.get(job_id)
    job = _get_opt_job(job_id)
    if event is None or job is None:
        raise HTTPException(status_code=404, detail="参数优化任务不存在")
    event.set()
    updated = job.model_copy(update={"status": "running", "stage": "取消中"})
    _save_opt_job(updated)
    try:
        await run_in_threadpool(update_optimization_progress, job_id, updated)
    except FileNotFoundError:
        pass
    return {"ok": True}


@router.get("/backtest/records", response_model=list[BacktestRecordSummary])
async def get_backtest_records():
    # 返回本地保存的回测记录摘要列表，用于前端历史表格。
    """返回前端历史表格需要的回测记录摘要。"""
    return await run_in_threadpool(list_backtest_records)


@router.get("/backtest/records/{record_id}", response_model=BacktestResponse)
async def get_backtest_record(record_id: str):
    # 读取某一条完整回测记录，包括净值、交易、选股明细。
    """读取一条已保存的完整回测结果。"""
    try:
        return await run_in_threadpool(load_backtest_record, record_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="回测记录不存在")


@router.delete("/backtest/records/{record_id}")
async def remove_backtest_record(record_id: str):
    # 删除一条本地回测记录。删除是用户显式点击确认后的本机文件操作。
    """删除一条本地回测记录。"""
    try:
        await run_in_threadpool(delete_backtest_record, record_id)
        return {"ok": True}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="回测记录不存在")


@router.get("/stocks/{code}/minute", response_model=MinuteResponse)
async def get_stock_minute(code: str, trade_date: date = Query(...)):
    # 返回某只股票单日 15 分钟数据，用于选股结果里的快速分时查看。
    """返回前端分时图需要的股票 15 分钟数据和均价线。"""
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
    # 交易明细里点击股票会打开新页，用这个接口展示买入日前后若干交易日走势，
    # 方便复盘“买点前后价格形态是不是符合策略假设”。
    """返回某只股票中心日前后若干个交易日的分钟图数据。"""
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
    # 数据查看页的统一分钟图查询接口。股票可以按名称或代码查；
    # 指数可以输入“大盘/沪深300/000300”等。
    """查询任意股票或大盘指数的分钟图。

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
