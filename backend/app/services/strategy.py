"""
尾盘30分钟选股法策略层。

严格按文章5个条件过滤：
  1. 流通市值 ≤ 200亿
  2. 换手率 ≥ 3%
  3. 量比 ≥ 1.2
  4. 振幅 ≤ 5%
  5. 近20日出现过涨停

附加大盘过滤：沪深300当日跌幅 > 2% 且量比 > 1.5 → 跳过换仓
换仓日 = 每周/每月最后交易日；执行日 = T+1 开盘
"""
from datetime import date
import pandas as pd
import numpy as np
import logging

from ..models.schemas import BacktestParams

logger = logging.getLogger(__name__)


# ── 换仓日 / 执行日 ──────────────────────────────────────

def get_rebalance_dates(
    trading_days: pd.DatetimeIndex,
    start: date,
    end: date,
    frequency: str = "weekly",
) -> list[pd.Timestamp]:
    """每周/每月/每日最后一个交易日作为选股日(T)。"""
    tds = trading_days[
        (trading_days >= pd.Timestamp(start)) &
        (trading_days <= pd.Timestamp(end))
    ]
    if tds.empty:
        return []

    tds_series = pd.Series(tds, index=tds)

    if frequency == "daily":
        return sorted(tds.tolist())
    elif frequency == "monthly":
        grouped = tds_series.groupby([tds.year, tds.month])
    else:  # weekly
        grouped = tds_series.groupby(
            [tds.isocalendar().year, tds.isocalendar().week]
        )

    return sorted({group.iloc[-1] for _, group in grouped})


def build_execution_map(
    rebalance_dates: list[pd.Timestamp],
    trading_days: pd.DatetimeIndex,
) -> dict[pd.Timestamp, pd.Timestamp]:
    """
    返回 {选股日T → 执行日T+1} 映射。
    若 T 是最后一个交易日，则 T 本身作为执行日（边界情况）。
    """
    td_list = sorted(trading_days.tolist())
    td_idx = {t: i for i, t in enumerate(td_list)}
    result = {}
    for t in rebalance_dates:
        idx = td_idx.get(t)
        if idx is not None and idx + 1 < len(td_list):
            result[t] = td_list[idx + 1]
        elif idx is not None:
            result[t] = t
    return result


# ── 大盘过滤 ─────────────────────────────────────────────

def is_market_crash(
    date: pd.Timestamp,
    benchmark: pd.DataFrame,
    pct_drop_threshold: float = -2.0,
    vol_ratio_threshold: float = 1.5,
) -> bool:
    """
    当日沪深300跌幅 > 2% 且量比 > 1.5 → 视为放量大跌，跳过换仓。
    benchmark 需含 date(index)、pct_change、volume 列。
    """
    if benchmark.empty or date not in benchmark.index:
        return False
    row = benchmark.loc[date]
    pct = row.get("pct_change", 0)
    vol_ratio = row.get("vol_ratio", 0)
    return float(pct) < pct_drop_threshold and float(vol_ratio) > vol_ratio_threshold


# ── 基础过滤 ─────────────────────────────────────────────

def get_base_valid_codes(
    universe: pd.DataFrame,
    panel_close: pd.DataFrame,
    date: pd.Timestamp,
    min_listing_days: int = 60,
) -> set[str]:
    """剔除 ST、停牌（无价格或价格=0）、新股。"""
    # 找最近有效交易日
    avail = panel_close.index[panel_close.index <= date]
    if avail.empty:
        return set()
    d = avail[-1]

    prices = panel_close.loc[d].dropna()
    valid = set(prices[prices > 0].index)

    # 去 ST
    non_st = set(universe[~universe["is_st"]]["code"])
    valid &= non_st

    # 去新股
    if "list_date" in universe.columns:
        cutoff = date - pd.Timedelta(days=min_listing_days)
        old = set(universe[
            universe["list_date"].notna() & (universe["list_date"] <= cutoff)
        ]["code"])
        valid &= old

    return valid


# ── 核心选股 ─────────────────────────────────────────────

def select_by_conditions(
    date: pd.Timestamp,
    universe: pd.DataFrame,
    panel_close: pd.DataFrame,
    panel_turnover: pd.DataFrame,
    panel_volume_ratio: pd.DataFrame,
    panel_amplitude: pd.DataFrame,
    panel_had_limitup: pd.DataFrame,
    params: BacktestParams,
) -> list[str]:
    """
    按文章5个条件过滤，返回满足条件的股票代码列表。
    若结果 > max_positions，按换手率降序截取前 max_positions 只。
    """
    # 找最近有效日期（各面板可能不完全对齐）
    def nearest(panel: pd.DataFrame) -> pd.Timestamp | None:
        avail = panel.index[panel.index <= date]
        return avail[-1] if not avail.empty else None

    base_valid = get_base_valid_codes(universe, panel_close, date)
    if not base_valid:
        return []

    codes = list(base_valid)

    # 1. 流通市值 ≤ max_float_mktcap（亿元）
    if "float_mktcap" in universe.columns:
        mktcap_ok = set(
            universe[
                universe["float_mktcap"].notna() &
                (universe["float_mktcap"] <= params.max_float_mktcap)
            ]["code"]
        )
        codes = [c for c in codes if c in mktcap_ok]

    if not codes:
        return []

    d_turn = nearest(panel_turnover)
    d_vr = nearest(panel_volume_ratio)
    d_amp = nearest(panel_amplitude)
    d_lu = nearest(panel_had_limitup)

    def get_row(panel: pd.DataFrame, d) -> pd.Series:
        if d is None:
            return pd.Series(dtype=float)
        return panel.loc[d].reindex(codes)

    turnover_row = get_row(panel_turnover, d_turn)
    vr_row = get_row(panel_volume_ratio, d_vr)
    amp_row = get_row(panel_amplitude, d_amp)
    lu_row = get_row(panel_had_limitup, d_lu)

    # 2. 换手率 ≥ min_turnover_rate
    codes = [c for c in codes if pd.notna(turnover_row.get(c)) and turnover_row[c] >= params.min_turnover_rate]

    # 3. 量比 ≥ min_volume_ratio
    codes = [c for c in codes if pd.notna(vr_row.get(c)) and vr_row[c] >= params.min_volume_ratio]

    # 4. 振幅 ≤ max_amplitude
    codes = [c for c in codes if pd.notna(amp_row.get(c)) and amp_row[c] <= params.max_amplitude]

    # 5. 近期有涨停
    codes = [c for c in codes if lu_row.get(c, False)]

    if not codes:
        return []

    # 超出 max_positions → 按换手率降序截取
    if len(codes) > params.max_positions:
        turn_vals = turnover_row.reindex(codes).fillna(0)
        codes = turn_vals.nlargest(params.max_positions).index.tolist()

    return codes
