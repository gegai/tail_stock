"""
持仓路由：
- GET /select  按指定日期选股
  - 日期在本地 parquet 中 → 直接读取
  - 日期不在 parquet（如今日）→ 从 Tushare 实时拉取（需配置 token）
"""
import logging
import time
from datetime import date
from functools import lru_cache

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from ...core.config import settings
from ...models.schemas import HoldingStock, BacktestParams
from ...services.data_fetcher import _load_basic, _daily_path

router = APIRouter(prefix="/portfolio", tags=["portfolio"])
logger = logging.getLogger(__name__)

_TODAY_COLS = [
    "open", "high", "low", "close", "pre_close",
    "pct_chg", "turnover_rate", "volume_ratio", "circ_mv",
    "is_st", "listed_days", "suspend_type",
]


# ── 工具 ─────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _parquet_dates() -> frozenset:
    """缓存 parquet 中所有可用交易日（normalize 到 date）。"""
    df = pd.read_parquet(_daily_path(), columns=[])
    return frozenset(
        pd.Timestamp(d).normalize()
        for d in df.index.get_level_values("trade_date").unique()
    )


def _apply_filters(df: pd.DataFrame, params: BacktestParams) -> pd.DataFrame:
    df = df[~df["is_st"].fillna(False).astype(bool)]
    df = df[df["close"].notna() & (df["close"] > 0)]
    df = df[df["suspend_type"].fillna("N") == "N"]
    df = df[df["listed_days"].fillna(0) >= 60]
    df = df[df["float_mktcap"].notna() & (df["float_mktcap"] <= params.max_float_mktcap)]
    df = df[df["turnover_rate"].notna() & (df["turnover_rate"] >= params.min_turnover_rate)]
    df = df[df["volume_ratio"].notna() & (df["volume_ratio"] >= params.min_volume_ratio)]
    df = df[df["amplitude"].notna() & (df["amplitude"] <= params.max_amplitude)]
    return df


def _check_limitup(codes: list, ref_date: pd.Timestamp, lookback: int) -> set:
    """从 parquet 中查近 lookback 个交易日是否有涨停。"""
    try:
        buffer_start = ref_date - pd.Timedelta(days=lookback * 2)
        df = pd.read_parquet(
            _daily_path(), columns=["pct_chg"],
            filters=[
                ("trade_date", ">=", buffer_start),
                ("trade_date", "<=", ref_date),
            ],
        )
        df = df.reset_index()
        df["symbol"] = df["ts_code"].str.split(".").str[0]
        df = df[df["symbol"].isin(codes)]
        all_dates = sorted(df["trade_date"].unique())
        if len(all_dates) > lookback:
            df = df[df["trade_date"] >= all_dates[-lookback]]
        return set(df[df["pct_chg"] >= 9.9]["symbol"].unique())
    except Exception as e:
        logger.warning(f"Limitup check failed ({e}), skipping")
        return set(codes)


def _compute_scores(df: pd.DataFrame, params: BacktestParams) -> pd.Series:
    s_turn = (
        df["turnover_rate"].clip(upper=params.min_turnover_rate * 2)
        / (params.min_turnover_rate * 2)
    ) * 40
    s_vr = (
        df["volume_ratio"].clip(upper=params.min_volume_ratio * 2)
        / (params.min_volume_ratio * 2)
    ) * 30
    s_mktcap = ((1 - df["float_mktcap"] / params.max_float_mktcap).clip(lower=0)) * 20
    s_amp    = ((1 - df["amplitude"]     / params.max_amplitude).clip(lower=0))    * 10
    return s_turn + s_vr + s_mktcap + s_amp


def _to_holdings(df: pd.DataFrame, params: BacktestParams) -> list[HoldingStock]:
    if len(df) > params.max_positions:
        scores = _compute_scores(df, params)
        df = df.loc[scores.nlargest(params.max_positions).index]
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


# ── 从 parquet 选股 ──────────────────────────────────────

def _select_from_parquet(req_date: pd.Timestamp, params: BacktestParams) -> list[HoldingStock]:
    day_df = pd.read_parquet(
        _daily_path(), columns=_TODAY_COLS,
        filters=[("trade_date", "==", req_date)],
    )
    if day_df.empty:
        return []
    day_df = day_df.reset_index()
    day_df["symbol"] = day_df["ts_code"].str.split(".").str[0]
    day_df["float_mktcap"] = day_df["circ_mv"] / 10000
    day_df["amplitude"] = (
        (day_df["high"] - day_df["low"])
        / day_df["pre_close"].replace(0, float("nan")) * 100
    )
    basic = _load_basic()[["ts_code", "name"]]
    day_df = day_df.merge(basic, on="ts_code", how="left")

    df = _apply_filters(day_df, params)
    if df.empty:
        return []

    limitup_codes = _check_limitup(df["symbol"].tolist(), req_date, params.limitup_lookback)
    df = df[df["symbol"].isin(limitup_codes)]
    if df.empty:
        return []
    return _to_holdings(df, params)


# ── 从 Tushare 实时选股 ──────────────────────────────────

def _call_tushare(fn, max_retries: int = 3, sleep_sec: float = 1.0, **kwargs) -> pd.DataFrame:
    for attempt in range(max_retries):
        try:
            result = fn(**kwargs)
            time.sleep(sleep_sec)
            return result if result is not None else pd.DataFrame()
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(sleep_sec * (attempt + 1) * 2)
            else:
                logger.error(f"Tushare call failed after {max_retries} retries: {e}")
                return pd.DataFrame()
    return pd.DataFrame()


def _select_from_tushare(date_str: str, params: BacktestParams) -> list[HoldingStock]:
    import tushare as ts

    token = settings.tushare_token
    if not token:
        raise ValueError("未配置 TUSHARE_TOKEN，无法获取实时数据。请在 .env 中设置：TUSHARE_TOKEN=your_token")

    ts.set_token(token)
    pro = ts.pro_api()
    trade_date = date_str.replace("-", "")

    # 先尝试指定日期，若无数据（非交易日）往前找
    for offset in range(5):
        td = (pd.Timestamp(date_str) - pd.Timedelta(days=offset)).strftime("%Y%m%d")
        basic = _call_tushare(
            pro.daily_basic, trade_date=td,
            fields="ts_code,trade_date,turnover_rate,volume_ratio,circ_mv",
        )
        bars = _call_tushare(
            pro.daily, trade_date=td,
            fields="ts_code,open,high,low,close,pre_close,pct_chg",
        )
        if not basic.empty and not bars.empty:
            logger.info(f"Tushare: using trade_date={td}")
            break
    else:
        return []

    def to_sym(ts_code: str) -> str:
        return ts_code.split(".")[0]

    basic["symbol"] = basic["ts_code"].apply(to_sym)
    bars["symbol"] = bars["ts_code"].apply(to_sym)
    df = basic.merge(
        bars[["symbol", "open", "high", "low", "close", "pre_close", "pct_chg"]],
        on="symbol", how="inner",
    )
    df["amplitude"] = (df["high"] - df["low"]) / df["pre_close"].replace(0, float("nan")) * 100
    df["float_mktcap"] = df["circ_mv"] / 10000

    basic_info = _load_basic()[["ts_code", "name", "list_date"]]
    df = df.merge(basic_info, on="ts_code", how="left")

    # Add is_st from name
    df["is_st"] = df["name"].str.contains("ST", case=False, na=False).astype(bool)
    # listed_days from list_date
    df["list_date_ts"] = pd.to_datetime(df["list_date"], errors="coerce")
    today_ts = pd.Timestamp(date_str)
    df["listed_days"] = (today_ts - df["list_date_ts"]).dt.days.fillna(0)
    df["suspend_type"] = "N"  # Tushare daily skips suspended stocks

    df = _apply_filters(df, params)
    if df.empty:
        return []

    # Limitup: check parquet historical data
    limitup_codes = _check_limitup(
        df["symbol"].tolist(), today_ts, params.limitup_lookback
    )
    df = df[df["symbol"].isin(limitup_codes)]
    if df.empty:
        return []
    return _to_holdings(df, params)


# ── 主路由 ───────────────────────────────────────────────

def _select_for_date(date_str: str, params: BacktestParams) -> tuple[list[HoldingStock], str]:
    """Returns (holdings, data_source_label)."""
    req_date = pd.Timestamp(date_str).normalize()
    dates = _parquet_dates()

    if req_date in dates:
        return _select_from_parquet(req_date, params), "parquet"
    else:
        holdings = _select_from_tushare(date_str, params)
        return holdings, "tushare"


@router.get("/select", response_model=list[HoldingStock])
async def select_stocks(
    trade_date: str = Query(default=None, description="选股日期 YYYY-MM-DD，默认今日"),
    max_float_mktcap: float = Query(default=200.0),
    min_turnover_rate: float = Query(default=3.0),
    min_volume_ratio: float = Query(default=1.2),
    max_amplitude: float = Query(default=5.0),
    limitup_lookback: int = Query(default=20),
    max_positions: int = Query(default=5),
):
    """按指定日期选股。日期在 parquet 中用历史数据，否则调 Tushare 实时接口。"""
    if trade_date is None:
        trade_date = date.today().strftime("%Y-%m-%d")

    params = BacktestParams(
        max_float_mktcap=max_float_mktcap,
        min_turnover_rate=min_turnover_rate,
        min_volume_ratio=min_volume_ratio,
        max_amplitude=max_amplitude,
        limitup_lookback=limitup_lookback,
        max_positions=max_positions,
    )
    try:
        holdings, source = await run_in_threadpool(_select_for_date, trade_date, params)
        logger.info(f"select {trade_date} via {source}: {len(holdings)} stocks")
        return holdings
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Stock selection failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/today", response_model=list[HoldingStock])
async def get_today_holdings(
    max_float_mktcap: float = Query(default=200.0),
    min_turnover_rate: float = Query(default=3.0),
    min_volume_ratio: float = Query(default=1.2),
    max_amplitude: float = Query(default=5.0),
    limitup_lookback: int = Query(default=20),
    max_positions: int = Query(default=5),
):
    """兼容旧接口 — 等价于 /select 不传日期。"""
    return await select_stocks(
        trade_date=None,
        max_float_mktcap=max_float_mktcap,
        min_turnover_rate=min_turnover_rate,
        min_volume_ratio=min_volume_ratio,
        max_amplitude=max_amplitude,
        limitup_lookback=limitup_lookback,
        max_positions=max_positions,
    )


@router.get("/current", response_model=list[HoldingStock])
async def get_current_holdings(
    max_float_mktcap: float = Query(default=200.0),
    min_turnover_rate: float = Query(default=3.0),
    min_volume_ratio: float = Query(default=1.2),
    max_amplitude: float = Query(default=5.0),
    limitup_lookback: int = Query(default=20),
    max_positions: int = Query(default=5),
):
    """兼容旧接口 — 使用 parquet 最新日期选股。"""
    return await get_today_holdings(
        max_float_mktcap=max_float_mktcap,
        min_turnover_rate=min_turnover_rate,
        min_volume_ratio=min_volume_ratio,
        max_amplitude=max_amplitude,
        limitup_lookback=limitup_lookback,
        max_positions=max_positions,
    )


@router.get("/available-date-range")
async def get_available_date_range():
    """返回 parquet 中的日期范围，供前端判断哪些日期有历史数据。"""
    try:
        dates = sorted(_parquet_dates())
        return {
            "start": str(dates[0].date()) if dates else None,
            "end": str(dates[-1].date()) if dates else None,
            "tushare_configured": bool(settings.tushare_token),
        }
    except Exception as e:
        return {"start": None, "end": None, "tushare_configured": False, "error": str(e)}
