"""
分时图路由：返回指定股票前后5个交易日的1分钟K线数据。
数据源：DATA_DIR/stock_1min/{ts_code}.parquet
MultiIndex: [trade_date, trade_time]，trade_time 为完整 datetime。
"""
import logging
import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from ...core.config import settings
from ...services.data_fetcher import _load_basic

router = APIRouter(prefix="/chart", tags=["chart"])
logger = logging.getLogger(__name__)


class MinuteBar(BaseModel):
    dt: str          # ISO datetime string, e.g. "2024-03-29 09:30:00"
    open: float
    high: float
    low: float
    close: float
    vol: float


class MinuteChartData(BaseModel):
    code: str
    name: str
    trade_date: str                    # 执行日
    date_range: dict                   # {"start": ..., "end": ...}
    bars: list[MinuteBar]


def _infer_ts_code(code: str) -> str:
    if code[0] in "0123":
        return f"{code}.SZ"
    if code[0] == "6":
        return f"{code}.SH"
    return f"{code}.BJ"


def _load_minute_chart(code: str, date: str) -> MinuteChartData:
    ts_code = _infer_ts_code(code)
    path = settings.data_dir / "stock_1min" / f"{ts_code}.parquet"

    if not path.exists():
        raise FileNotFoundError(f"1分钟数据文件不存在: {ts_code}")

    df = pd.read_parquet(path)
    # MultiIndex(trade_date, trade_time): trade_time is the full datetime
    all_dates = sorted(df.index.get_level_values("trade_date").unique())
    if not all_dates:
        raise ValueError(f"{ts_code} 1分钟数据为空")

    target = pd.Timestamp(date).normalize()

    # Find position of target date (or nearest)
    date_ts = [pd.Timestamp(d) for d in all_dates]
    idx = next((i for i, d in enumerate(date_ts) if d >= target), len(date_ts) - 1)

    window_dates = all_dates[max(0, idx - 5): idx + 6]
    idx_slice = pd.IndexSlice
    subset = df.loc[idx_slice[window_dates, :], :]

    bars = [
        MinuteBar(
            dt=str(row.name[1]),   # trade_time level
            open=round(float(row["open"]), 3),
            high=round(float(row["high"]), 3),
            low=round(float(row["low"]), 3),
            close=round(float(row["close"]), 3),
            vol=round(float(row["vol"]), 0),
        )
        for _, row in subset.iterrows()
    ]

    # Stock name lookup
    basic = _load_basic()
    name_row = basic[basic["ts_code"] == ts_code]
    name = str(name_row["name"].iloc[0]) if not name_row.empty else code

    start_date = str(pd.Timestamp(window_dates[0]).date())
    end_date = str(pd.Timestamp(window_dates[-1]).date())

    return MinuteChartData(
        code=code,
        name=name,
        trade_date=str(target.date()),
        date_range={"start": start_date, "end": end_date},
        bars=bars,
    )


@router.get("/minute", response_model=MinuteChartData)
async def get_minute_chart(
    code: str = Query(..., description="6位股票代码，如 000001"),
    date: str = Query(..., description="执行日期 YYYY-MM-DD"),
):
    """返回指定股票前后各5个交易日的1分钟K线数据。"""
    try:
        return await run_in_threadpool(_load_minute_chart, code, date)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("Minute chart load failed")
        raise HTTPException(status_code=500, detail=f"分时数据加载失败: {e}")
