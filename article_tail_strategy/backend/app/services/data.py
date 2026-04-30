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
    """股票行情数据目录，默认位于 D:/股票数据/行情数据。"""
    return settings.data_root / "行情数据"


def index_dir() -> Path:
    """指数行情数据目录，默认位于 D:/股票数据/指数数据。"""
    return settings.data_root / "指数数据"


def stock_daily_path() -> Path:
    """全市场日线列式数据文件路径。"""
    return market_dir() / "stock_daily.parquet"


def stock_basic_path() -> Path:
    """股票基础信息列式数据文件路径。"""
    return market_dir() / "stock_basic_data.parquet"


def stock_minute_path(code: str, freq: str = "15min") -> Path:
    """单只股票分钟线文件路径，频率参数支持一分钟、十五分钟等目录。"""
    return market_dir() / f"stock_{freq}" / f"{code}.parquet"


def index_minute_path(code: str, freq: str = "15min") -> Path:
    """指数分钟线文件路径。"""
    return index_dir() / f"index_{freq}" / f"{code}.parquet"


def index_daily_path(code: str) -> Path:
    """指数日线文件路径。"""
    return index_dir() / "index_daily" / f"{code}.parquet"


@lru_cache(maxsize=1)
def load_basic() -> pd.DataFrame:
    """读取股票基础信息。

    基础信息被名称解析、ST 过滤、上市状态过滤频繁使用，缓存后可以减少
    列式数据文件反复读取。
    """
    return pd.read_parquet(stock_basic_path())


@lru_cache(maxsize=1)
def daily_index_only() -> pd.DataFrame:
    """只读取日线索引，用于快速拿到交易日列表。"""
    return pd.read_parquet(stock_daily_path(), columns=[])


@lru_cache(maxsize=1)
def trading_days() -> pd.DatetimeIndex:
    """返回全市场交易日序列。

    回测、历史回看、前后 N 个交易日窗口都基于这条统一交易日历，
    避免自然日和交易日混用。
    """
    idx = daily_index_only().index.get_level_values("trade_date").unique()
    return pd.DatetimeIndex(pd.to_datetime(idx)).sort_values()


def normalize_code(code: str) -> str:
    """把 6 位股票代码补成数据源使用的标准股票代码。

    例如 600000 -> 600000.SH，000001 -> 000001.SZ。
    如果调用方已经传入 000001.SZ，则直接返回。
    """
    code = code.strip().upper()
    if "." in code:
        return code
    if code.startswith(("6", "9")):
        return f"{code}.SH"
    return f"{code}.SZ"


def resolve_stock_query(query: str) -> str:
    """把股票代码或名称解析为标准股票代码。

    支持示例：
    - 000001
    - 000001.SZ
    - 平安银行
    - 名称片段，例如“平安”

    如果名称片段匹配多只股票，优先返回仍在上市状态的第一条记录。
    这个函数主要服务于“数据查看”页的快速查询，而不是严肃选股。
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
    """读取一段日期范围内的全市场日线数据。

    columns 用于限制字段，减少 parquet IO。策略里做涨停回看、均线计算时
    会按需只取 close/pct_chg 等字段。
    """
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
    """读取某一个交易日的全市场日线数据。

    这是文章“五个日线条件”的数据源。特别注意：circ_mv、turnover_rate、
    volume_ratio、is_st 等字段都来自请求日期当天，而不是最新快照。
    这样历史回测不会偷看到未来市值或未来 ST 状态。
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
    """读取指定股票集合在日期区间内的日线数据。"""
    df = load_daily_range(start, end, DAILY_COLS)
    if codes:
        df = df[df["ts_code"].isin(set(codes))]
    return df


def load_stock_minutes(code: str, day: str | pd.Timestamp, freq: str = "15min") -> pd.DataFrame:
    """读取单只股票某一天的分钟线。

    当前策略主流程使用 15 分钟线，因为文章的关键判断点是 14:30 后。
    数据查看页可以查看 1 分钟线，但全市场回测如果全部用 1 分钟线会慢很多，
    所以策略计算默认使用 15 分钟线。
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
    """读取指数某一天的分钟线，通常是沪深300。

    这些数据用于判断“大盘 14:30 后是否走强”和“大盘是否放量大跌”。
    如果数据缺失，返回空 DataFrame，让调用方明确地让规则失败，而不是默认放行。
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
    """读取指数日线区间数据，用于基准净值和 MA20 大盘过滤。"""
    path = index_daily_path(code)
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_parquet(path)
    df = df.reset_index()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    mask = (df["trade_date"] >= pd.Timestamp(start)) & (df["trade_date"] <= pd.Timestamp(end))
    return df.loc[mask].sort_values("trade_date")


def previous_trading_dates(day: str | pd.Timestamp, n: int) -> list[pd.Timestamp]:
    """返回包含指定日期在内的最近若干个交易日。"""
    day_ts = pd.Timestamp(day).normalize()
    days = trading_days()
    past = days[days <= day_ts]
    return list(past[-n:])


def next_trading_day(day: str | pd.Timestamp) -> pd.Timestamp | None:
    """返回指定日期之后的下一个交易日；如果没有后续交易日则返回空值。"""
    day_ts = pd.Timestamp(day).normalize()
    days = trading_days()
    future = days[days > day_ts]
    return pd.Timestamp(future[0]) if len(future) else None


def enrich_daily(day_df: pd.DataFrame) -> pd.DataFrame:
    """补充股票名称，并计算策略需要的标准化日线指标。

    - 数据里的 circ_mv 单位是万元，这里转换成亿元，便于和前端参数一致。
    - amplitude 对应文章里的“日内振幅”，计算为 (high - low) / pre_close * 100。
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
    """汇总本地数据目录状态，供前端“数据查看”页展示。"""
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
    """构造前端图表可直接使用的股票分钟线数据。

    除开高低收和成交量外，还会附带累计 VWAP。前端用它复盘候选股尾盘
    是否真的站在均价线之上。
    """
    df = load_stock_minutes(code, day, freq)
    return _bars_from_frame(df)


def stock_window_response(code: str, center_day: str, radius: int = 5, freq: str = "1min") -> list[tuple[str, list[MinuteBar]]]:
    """返回中心日前后若干个交易日的分钟线窗口。"""
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
    """构造前端图表可直接使用的指数分钟线数据。"""
    df = load_index_minutes(code, day, freq)
    return _bars_from_frame(df)


def _bars_from_frame(df: pd.DataFrame) -> list[MinuteBar]:
    """把原始分钟线表格转成图表需要的分钟柱列表。"""
    if df.empty:
        return []
    amount_cum = df["amount"].cumsum()
    vol_cum = df["vol"].replace(0, pd.NA).cumsum()
    vwap = (amount_cum / vol_cum).ffill().fillna(df["close"])
    close = df["close"].astype(float)
    ratio = (vwap.astype(float) / close.replace(0, pd.NA)).dropna()
    if not ratio.empty and (ratio.median() < 0.5 or ratio.median() > 1.5):
        # 有些指数文件里的成交额和成交量单位不一致，直接相除会得到离价格很远的数。
        # 这时退回到“成交量加权收盘价”的累计均线，保证前端看到的均价线仍有意义。
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
