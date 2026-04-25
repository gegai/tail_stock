"""
持仓路由：
- GET /today   基于 parquet 最新交易日数据选股（等同今日收盘后选股）
- GET /current 基于 parquet 历史数据的最新换仓日持仓
"""
import logging

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from ...core.config import settings
from ...models.schemas import HoldingStock, BacktestParams
from ...services.data_fetcher import (
    get_stock_universe, build_ohlcv_panels,
    build_recent_limitup, _load_basic,
)
from ...services.strategy import select_by_conditions

router = APIRouter(prefix="/portfolio", tags=["portfolio"])
logger = logging.getLogger(__name__)

# Columns needed for single-day selection
_TODAY_COLS = [
    "open", "high", "low", "close", "pre_close",
    "pct_chg", "turnover_rate", "volume_ratio", "circ_mv",
    "is_st", "listed_days", "suspend_type",
]


def _check_recent_limitup(codes: list, latest_date: pd.Timestamp, lookback: int) -> set:
    """Load recent N trading days from parquet and find stocks with pct_chg >= 9.9."""
    try:
        buffer_start = latest_date - pd.Timedelta(days=lookback * 2)
        df = pd.read_parquet(
            settings.data_dir / "stock_daily.parquet",
            columns=["pct_chg"],
            filters=[
                ("trade_date", ">=", buffer_start),
                ("trade_date", "<=", latest_date),
            ],
        )
        df = df.reset_index()
        df["symbol"] = df["ts_code"].str.split(".").str[0]
        df = df[df["symbol"].isin(codes)]

        all_dates = sorted(df["trade_date"].unique())
        if len(all_dates) > lookback:
            cutoff = all_dates[-lookback]
            df = df[df["trade_date"] >= cutoff]

        return set(df[df["pct_chg"] >= 9.9]["symbol"].unique())
    except Exception as e:
        logger.warning(f"Limitup check failed ({e}), skipping condition 5")
        return set(codes)


def _today_select(params: BacktestParams) -> list:
    """Select stocks using the latest available trading day in the parquet."""
    # Find latest trading date
    idx_df = pd.read_parquet(settings.data_dir / "stock_daily.parquet", columns=[])
    latest_date = idx_df.index.get_level_values("trade_date").max()
    latest_ts = pd.Timestamp(latest_date)

    # Load that day's data
    day_df = pd.read_parquet(
        settings.data_dir / "stock_daily.parquet",
        columns=_TODAY_COLS,
        filters=[("trade_date", "==", latest_ts)],
    )
    day_df = day_df.reset_index()
    day_df["symbol"] = day_df["ts_code"].str.split(".").str[0]
    day_df["float_mktcap"] = day_df["circ_mv"] / 10000
    day_df["amplitude"] = (
        (day_df["high"] - day_df["low"])
        / day_df["pre_close"].replace(0, float("nan"))
        * 100
    )

    # Attach stock names
    basic = _load_basic()[["ts_code", "name"]]
    day_df = day_df.merge(basic, on="ts_code", how="left")

    # Filter: non-ST, active (not suspended), listed >= 60 days, close > 0
    df = day_df[~day_df["is_st"].fillna(False).astype(bool)].copy()
    df = df[df["close"].notna() & (df["close"] > 0)]
    df = df[df["suspend_type"].fillna("N") == "N"]
    df = df[df["listed_days"].fillna(0) >= 60]

    # Condition 1: float market cap
    df = df[df["float_mktcap"].notna() & (df["float_mktcap"] <= params.max_float_mktcap)]
    # Condition 2: turnover rate
    df = df[df["turnover_rate"].notna() & (df["turnover_rate"] >= params.min_turnover_rate)]
    # Condition 3: volume ratio
    df = df[df["volume_ratio"].notna() & (df["volume_ratio"] >= params.min_volume_ratio)]
    # Condition 4: amplitude
    df = df[df["amplitude"].notna() & (df["amplitude"] <= params.max_amplitude)]

    if df.empty:
        return []

    # Condition 5: recent limitup in past lookback trading days
    codes = df["symbol"].tolist()
    limitup_codes = _check_recent_limitup(codes, latest_ts, params.limitup_lookback)
    df = df[df["symbol"].isin(limitup_codes)]

    if df.empty:
        return []

    if len(df) > params.max_positions:
        df = df.nlargest(params.max_positions, "turnover_rate")

    weight = 1.0 / len(df)
    return [
        HoldingStock(
            code=str(row["symbol"]),
            name=str(row.get("name", row["symbol"])),
            market_cap=round(float(row.get("float_mktcap", 0)), 2),
            turnover_rate=round(float(row.get("turnover_rate", 0)), 2),
            weight=round(weight, 4),
        )
        for _, row in df.iterrows()
    ]


@router.get("/today", response_model=list[HoldingStock])
async def get_today_holdings(
    max_float_mktcap: float = Query(default=200.0),
    min_turnover_rate: float = Query(default=3.0),
    min_volume_ratio: float = Query(default=1.2),
    max_amplitude: float = Query(default=5.0),
    limitup_lookback: int = Query(default=20),
    max_positions: int = Query(default=20),
):
    """用 parquet 最新交易日数据按5个条件选股（相当于当日收盘后选股）。"""
    params = BacktestParams(
        max_float_mktcap=max_float_mktcap,
        min_turnover_rate=min_turnover_rate,
        min_volume_ratio=min_volume_ratio,
        max_amplitude=max_amplitude,
        limitup_lookback=limitup_lookback,
        max_positions=max_positions,
    )
    try:
        return await run_in_threadpool(_today_select, params)
    except Exception as e:
        logger.exception("Today selection failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/current", response_model=list[HoldingStock])
async def get_current_holdings(
    max_float_mktcap: float = Query(default=200.0),
    min_turnover_rate: float = Query(default=3.0),
    min_volume_ratio: float = Query(default=1.2),
    max_amplitude: float = Query(default=5.0),
    limitup_lookback: int = Query(default=20),
    max_positions: int = Query(default=20),
):
    """根据 parquet 最新交易日数据选股（与 /today 等价，保留兼容）。"""
    params = BacktestParams(
        max_float_mktcap=max_float_mktcap,
        min_turnover_rate=min_turnover_rate,
        min_volume_ratio=min_volume_ratio,
        max_amplitude=max_amplitude,
        limitup_lookback=limitup_lookback,
        max_positions=max_positions,
    )
    try:
        return await run_in_threadpool(_today_select, params)
    except Exception as e:
        logger.exception("Current holdings failed")
        raise HTTPException(status_code=500, detail=str(e))
