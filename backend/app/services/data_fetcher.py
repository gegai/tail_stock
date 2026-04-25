"""
Parquet-based data layer for 尾盘选股策略.

Data source: LOCAL PARQUET FILES (pre-downloaded A-share data)
  - {DATA_DIR}/stock_daily.parquet      MultiIndex(trade_date, ts_code), 14M+ rows
  - {DATA_DIR}/stock_basic_data.parquet stock basics (name, symbol, list_date, ...)

All panels use 6-digit symbol as column key (000001, 600000, etc.).
pct_chg unit: % (9.9 = +9.9%)
circ_mv unit: 万元 -> float_mktcap in 亿元 (/ 10000)
"""
import logging
import os
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from ..core.config import settings

logger = logging.getLogger(__name__)

# Subset of columns loaded for strategy panels (reduces memory usage)
_DAILY_COLS = [
    "open", "high", "low", "close", "pre_close", "vol", "amount",
    "pct_chg", "turnover_rate", "volume_ratio", "circ_mv",
    "is_st", "listed_days", "suspend_type",
]


def _daily_path() -> Path:
    return settings.data_dir / "stock_daily.parquet"


def _basic_path() -> Path:
    return settings.data_dir / "stock_basic_data.parquet"


@lru_cache(maxsize=1)
def _load_basic() -> pd.DataFrame:
    """Load stock_basic_data.parquet once and cache."""
    return pd.read_parquet(_basic_path())


def get_stock_universe() -> pd.DataFrame:
    """
    Return full A-share universe with columns:
    code (6-digit), ts_code, name, exchange, is_st, list_date, float_mktcap (亿元)
    """
    basic = _load_basic().copy()

    # Get latest day's circ_mv and is_st from stock_daily
    daily_snap = pd.read_parquet(_daily_path(), columns=["circ_mv", "is_st", "listed_days"])
    latest_date = daily_snap.index.get_level_values("trade_date").max()
    idx = pd.IndexSlice
    latest = (
        daily_snap.loc[idx[latest_date, :], :]
        .reset_index(level=0, drop=True)
        .reset_index()
        .rename(columns={"index": "ts_code"})
    )

    result = basic.merge(latest, on="ts_code", how="left")
    result["float_mktcap"] = result["circ_mv"] / 10000  # 万元 -> 亿元
    result["code"] = result["ts_code"].str.split(".").str[0]  # 6-digit
    result["symbol"] = result["code"]
    result["is_st"] = result["is_st"].fillna(False).astype(bool)
    result["list_date"] = pd.to_datetime(result.get("list_date"), errors="coerce")
    return result


def build_ohlcv_panels(
    codes: "list[str] | None",
    start_date: str,
    end_date: str,
) -> "dict[str, pd.DataFrame]":
    """
    Load from parquet and build aligned panels (index=datetime, columns=6-digit symbol).

    PyArrow row-group filtering: reads only the requested date range.
    unstack() builds all panels in one vectorized operation.

    Returns keys: close, open, volume, turnover, amplitude, pct_chg, volume_ratio
    """
    filters = [
        ("trade_date", ">=", pd.Timestamp(start_date)),
        ("trade_date", "<=", pd.Timestamp(end_date)),
    ]
    df = pd.read_parquet(_daily_path(), columns=_DAILY_COLS, filters=filters)

    df = df.reset_index()
    df["symbol"] = df["ts_code"].str.split(".").str[0]

    if codes:
        df = df[df["symbol"].isin(set(codes))]

    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df["amplitude"] = (df["high"] - df["low"]) / df["pre_close"].replace(0, np.nan) * 100

    df = df.set_index(["trade_date", "symbol"])

    def _panel(col: str) -> pd.DataFrame:
        return df[col].unstack("symbol").sort_index()

    return {
        "close":        _panel("close"),
        "open":         _panel("open"),
        "volume":       _panel("vol"),
        "turnover":     _panel("turnover_rate"),
        "amplitude":    _panel("amplitude"),
        "pct_chg":      _panel("pct_chg"),
        "volume_ratio": _panel("volume_ratio"),
    }


def get_benchmark_hist(
    start_date: str,
    end_date: str,
    ts_code: str = "000300.SH",
) -> pd.DataFrame:
    """
    Returns benchmark OHLCV. Returns empty DataFrame when unavailable.
    Callers must handle empty gracefully (skip market crash filter).
    """
    return pd.DataFrame()


# -- Derived panels -------------------------------------------------------

def build_volume_ratio(volume_panel: pd.DataFrame, window: int = 5) -> pd.DataFrame:
    """Fallback volume_ratio calculation when not pre-computed in data source."""
    vol_ma = volume_panel.rolling(window=window, min_periods=3).mean()
    return (volume_panel / vol_ma.replace(0, np.nan)).fillna(0)


def build_recent_limitup(pct_change_panel: pd.DataFrame, lookback: int = 20) -> pd.DataFrame:
    """近 lookback 个交易日内是否出现过涨停（pct_chg >= 9.9%）。"""
    limitup = (pct_change_panel >= 9.9).astype(float)
    return limitup.rolling(window=lookback, min_periods=1).max().astype(bool)


def build_benchmark_volume_ratio(benchmark: pd.DataFrame, window: int = 5) -> pd.Series:
    """大盘量比（benchmark 含 volume 列时使用）。"""
    if "volume" not in benchmark.columns:
        return pd.Series(dtype=float)
    vol_ma = benchmark["volume"].rolling(window=window, min_periods=3).mean()
    return (benchmark["volume"] / vol_ma.replace(0, np.nan)).fillna(0)


# -- Data info for cache-info endpoint ------------------------------------

def get_data_info() -> dict:
    """Return parquet file stats for the /data/cache-info endpoint."""
    path = _daily_path()
    if not path.exists():
        return {"available": False, "files": 0, "size_mb": 0}

    try:
        df_idx = pd.read_parquet(path, columns=[])
        dates = df_idx.index.get_level_values("trade_date")
        return {
            "available": True,
            "files": len(df_idx),
            "size_mb": round(os.path.getsize(str(path)) / 1024 / 1024, 1),
            "date_range": {
                "start": str(dates.min())[:10],
                "end": str(dates.max())[:10],
            },
            "stock_count": df_idx.index.get_level_values("ts_code").nunique(),
        }
    except Exception as e:
        return {"available": False, "files": 0, "size_mb": 0, "error": str(e)}
