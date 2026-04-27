from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

from app.config import settings
from app.models import DataInfo, MinuteBar


DAILY_COLS = [
    "open", "high", "low", "close", "pre_close", "pct_chg", "vol", "amount",
    "turnover_rate", "volume_ratio", "circ_mv", "is_st", "listed_days",
    "suspend_type",
]


def market_dir() -> Path:
    return settings.data_root / "行情数据"


def index_dir() -> Path:
    return settings.data_root / "指数数据"


def stock_daily_path() -> Path:
    return market_dir() / "stock_daily.parquet"


def stock_basic_path() -> Path:
    return market_dir() / "stock_basic_data.parquet"


def stock_minute_path(code: str, freq: str = "15min") -> Path:
    return market_dir() / f"stock_{freq}" / f"{code}.parquet"


def index_minute_path(code: str, freq: str = "15min") -> Path:
    return index_dir() / f"index_{freq}" / f"{code}.parquet"


def index_daily_path(code: str) -> Path:
    return index_dir() / "index_daily" / f"{code}.parquet"


@lru_cache(maxsize=1)
def load_basic() -> pd.DataFrame:
    return pd.read_parquet(stock_basic_path())


@lru_cache(maxsize=1)
def daily_index_only() -> pd.DataFrame:
    return pd.read_parquet(stock_daily_path(), columns=[])


@lru_cache(maxsize=1)
def trading_days() -> pd.DatetimeIndex:
    idx = daily_index_only().index.get_level_values("trade_date").unique()
    return pd.DatetimeIndex(pd.to_datetime(idx)).sort_values()


def normalize_code(code: str) -> str:
    code = code.strip().upper()
    if "." in code:
        return code
    if code.startswith(("6", "9")):
        return f"{code}.SH"
    return f"{code}.SZ"


def resolve_stock_query(query: str) -> str:
    """Resolve a stock code or name to ts_code.

    Accepted examples:
    - 000001
    - 000001.SZ
    - 平安银行
    - partial names such as "平安"

    If a partial name matches multiple stocks, the first active/listed match in
    stock_basic_data is returned. The frontend can use this as a convenient
    "quick inspect" lookup without requiring an exact code.
    """
    q = query.strip().upper()
    if not q:
        raise ValueError("请输入股票名称或代码")
    if q in {"大盘", "沪深300", "HS300", "000300", "000300.SH"}:
        return settings.benchmark_code
    if q.replace(".", "").isalnum() and any(ch.isdigit() for ch in q):
        return normalize_code(q)

    basic = load_basic().copy()
    basic["name_str"] = basic["name"].astype(str)
    matched = basic[basic["name_str"].str.contains(query.strip(), na=False, regex=False)]
    if matched.empty:
        raise ValueError(f"未找到股票：{query}")
    listed = matched[matched["list_status"].fillna("L") == "L"]
    row = (listed if not listed.empty else matched).iloc[0]
    return str(row["ts_code"])


def load_daily_range(start: str, end: str, columns: list[str] | None = None) -> pd.DataFrame:
    cols = columns or DAILY_COLS
    df = pd.read_parquet(
        stock_daily_path(),
        columns=cols,
        filters=[
            ("trade_date", ">=", pd.Timestamp(start)),
            ("trade_date", "<=", pd.Timestamp(end)),
        ],
    )
    return df.reset_index()


def load_daily_date(day: str | pd.Timestamp, columns: list[str] | None = None) -> pd.DataFrame:
    """Load all stock daily rows for one trading day.

    This is the source for the article's five daily filters. Importantly, fields
    such as circ_mv, turnover_rate, volume_ratio and is_st are read from the
    requested date itself, not from the latest snapshot, so historical selection
    does not accidentally see future market-cap or ST information.
    """
    ts = pd.Timestamp(day).normalize()
    cols = columns or DAILY_COLS
    df = pd.read_parquet(
        stock_daily_path(),
        columns=cols,
        filters=[("trade_date", "==", ts)],
    )
    if df.empty:
        return pd.DataFrame()
    df = df.reset_index()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df


def load_daily_for_codes(start: str, end: str, codes: list[str]) -> pd.DataFrame:
    df = load_daily_range(start, end, DAILY_COLS)
    if codes:
        df = df[df["ts_code"].isin(set(codes))]
    return df


def load_stock_minutes(code: str, day: str | pd.Timestamp, freq: str = "15min") -> pd.DataFrame:
    """Load one stock's intraday bars for one trading day.

    The current strategy uses 15-minute bars because the article's key decision
    point is after 14:30. The data folder also has 1-minute bars, but 15-minute
    bars make the rule faster and less noisy for broad-universe backtests.
    """
    ts_code = normalize_code(code)
    path = stock_minute_path(ts_code, freq)
    if not path.exists():
        return pd.DataFrame()
    day_ts = pd.Timestamp(day).normalize()
    df = pd.read_parquet(path)
    if isinstance(df.index, pd.MultiIndex):
        try:
            df = df.loc[pd.IndexSlice[day_ts, :], :].reset_index()
        except KeyError:
            return pd.DataFrame()
    else:
        df = df.reset_index()
        df = df[pd.to_datetime(df["trade_date"]).dt.normalize() == day_ts]
    if df.empty:
        return pd.DataFrame()
    df["trade_time"] = pd.to_datetime(df["trade_time"])
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df.sort_values("trade_time")


def load_index_minutes(code: str, day: str | pd.Timestamp, freq: str = "15min") -> pd.DataFrame:
    """Load benchmark intraday bars, usually沪深300.

    These bars drive the "大盘 14:30 后处于上升趋势" and "放量大跌不进场"
    checks. Returning an empty frame lets callers fail the market rule clearly
    instead of silently pretending the big-market filter passed.
    """
    path = index_minute_path(code, freq)
    if not path.exists():
        return pd.DataFrame()
    day_ts = pd.Timestamp(day).normalize()
    df = pd.read_parquet(path)
    if isinstance(df.index, pd.MultiIndex):
        try:
            df = df.loc[pd.IndexSlice[day_ts, :], :].reset_index()
        except KeyError:
            return pd.DataFrame()
    else:
        df = df.reset_index()
        df = df[pd.to_datetime(df["trade_date"]).dt.normalize() == day_ts]
    if df.empty:
        return pd.DataFrame()
    df["trade_time"] = pd.to_datetime(df["trade_time"])
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df.sort_values("trade_time")


def load_index_daily(code: str, start: str, end: str) -> pd.DataFrame:
    path = index_daily_path(code)
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_parquet(path)
    df = df.reset_index()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    mask = (df["trade_date"] >= pd.Timestamp(start)) & (df["trade_date"] <= pd.Timestamp(end))
    return df.loc[mask].sort_values("trade_date")


def previous_trading_dates(day: str | pd.Timestamp, n: int) -> list[pd.Timestamp]:
    day_ts = pd.Timestamp(day).normalize()
    days = trading_days()
    past = days[days <= day_ts]
    return list(past[-n:])


def next_trading_day(day: str | pd.Timestamp) -> pd.Timestamp | None:
    day_ts = pd.Timestamp(day).normalize()
    days = trading_days()
    future = days[days > day_ts]
    return pd.Timestamp(future[0]) if len(future) else None


def enrich_daily(day_df: pd.DataFrame) -> pd.DataFrame:
    """Attach stock names and compute normalized daily metrics.

    - circ_mv in the data is 万元, so float_mktcap is converted to 亿元.
    - amplitude follows the article's "日内振幅 5% 以内" idea:
      (high - low) / pre_close * 100.
    """
    if day_df.empty:
        return day_df
    basic = load_basic()[["ts_code", "symbol", "name", "list_date", "list_status"]]
    df = day_df.merge(basic, on="ts_code", how="left")
    df["code"] = df["ts_code"]
    df["float_mktcap"] = df["circ_mv"] / 10000.0
    df["amplitude"] = (df["high"] - df["low"]) / df["pre_close"].replace(0, pd.NA) * 100.0
    return df


def data_info() -> DataInfo:
    daily_ok = stock_daily_path().exists()
    basic_ok = stock_basic_path().exists()
    start = end = None
    stock_count = None
    if daily_ok:
        idx = daily_index_only().index
        dates = pd.to_datetime(idx.get_level_values("trade_date"))
        start = str(dates.min().date())
        end = str(dates.max().date())
        stock_count = idx.get_level_values("ts_code").nunique()
    return DataInfo(
        data_root=str(settings.data_root),
        daily_available=daily_ok,
        stock_basic_available=basic_ok,
        stock_15min_count=len(list((market_dir() / "stock_15min").glob("*.parquet"))),
        stock_1min_count=len(list((market_dir() / "stock_1min").glob("*.parquet"))),
        index_15min_count=len(list((index_dir() / "index_15min").glob("*.parquet"))),
        index_1min_count=len(list((index_dir() / "index_1min").glob("*.parquet"))),
        daily_start=start,
        daily_end=end,
        stock_count=stock_count,
    )


def minute_bars_response(code: str, day: str, freq: str = "15min") -> list[MinuteBar]:
    """Build frontend-friendly minute bars with running VWAP.

    The UI uses this to visually audit whether a selected stock actually
    stayed above the average-price line near the tail session.
    """
    df = load_stock_minutes(code, day, freq)
    return _bars_from_frame(df)


def stock_window_response(code: str, center_day: str, radius: int = 5, freq: str = "1min") -> list[tuple[str, list[MinuteBar]]]:
    """Return minute bars for the trading-day window around a center date."""
    ts_code = normalize_code(code)
    days = trading_days()
    center = pd.Timestamp(center_day).normalize()
    pos = days.searchsorted(center)
    if pos >= len(days) or days[pos] != center:
        pos = max(0, pos - 1)
    start = max(0, pos - radius)
    end = min(len(days), pos + radius + 1)
    result: list[tuple[str, list[MinuteBar]]] = []
    for day in days[start:end]:
        bars = _bars_from_frame(load_stock_minutes(ts_code, day, freq))
        result.append((str(pd.Timestamp(day).date()), bars))
    return result


def index_minute_bars_response(code: str, day: str, freq: str = "15min") -> list[MinuteBar]:
    """Build frontend-friendly index minute bars."""
    df = load_index_minutes(code, day, freq)
    return _bars_from_frame(df)


def _bars_from_frame(df: pd.DataFrame) -> list[MinuteBar]:
    """Convert a raw minute DataFrame into chart-ready bars with VWAP."""
    if df.empty:
        return []
    amount_cum = df["amount"].cumsum()
    vol_cum = df["vol"].replace(0, pd.NA).cumsum()
    vwap = (amount_cum / vol_cum).ffill().fillna(df["close"])
    close = df["close"].astype(float)
    ratio = (vwap.astype(float) / close.replace(0, pd.NA)).dropna()
    if not ratio.empty and (ratio.median() < 0.5 or ratio.median() > 1.5):
        # Some index files store amount/volume in different units, making
        # amount/vol unusable as a price-level VWAP. Fall back to a cumulative
        # volume-weighted close so the "均价线" remains visually meaningful.
        weighted = (close * df["vol"]).cumsum()
        vwap = (weighted / vol_cum).ffill().fillna(close)
    bars: list[MinuteBar] = []
    for i, row in df.reset_index(drop=True).iterrows():
        bars.append(MinuteBar(
            dt=str(pd.Timestamp(row["trade_time"])),
            open=round(float(row["open"]), 4),
            high=round(float(row["high"]), 4),
            low=round(float(row["low"]), 4),
            close=round(float(row["close"]), 4),
            vol=round(float(row["vol"]), 2),
            vwap=round(float(vwap.iloc[i]), 4),
        ))
    return bars
