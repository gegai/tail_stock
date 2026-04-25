"""单元测试：尾盘选股5个条件 + 换仓日期 + 绩效指标"""
import pandas as pd
import numpy as np
import pytest
from datetime import date

from app.services.strategy import (
    get_rebalance_dates, build_execution_map,
    select_by_conditions, is_market_crash,
)
from app.services.backtester import calc_performance
from app.models.schemas import BacktestParams


# ── 辅助构造函数 ──────────────────────────────────────────

def make_tds(start="2022-01-01", end="2022-12-31"):
    return pd.bdate_range(start, end)


def make_panels(codes, dates, val=1.0):
    """构造所有值相同的 panel"""
    return pd.DataFrame(val, index=dates, columns=codes)


def make_universe(codes):
    return pd.DataFrame({
        "code": codes,
        "name": codes,
        "float_mktcap": [50.0] * len(codes),   # 亿元，全部 < 200
        "is_st": [False] * len(codes),
        "list_date": [pd.Timestamp("2020-01-01")] * len(codes),
    })


# ── 换仓日期测试 ──────────────────────────────────────────

def test_monthly_rebalance_count():
    tds = make_tds("2022-01-01", "2022-12-31")
    dates = get_rebalance_dates(tds, date(2022, 1, 1), date(2022, 12, 31), "monthly")
    assert len(dates) == 12


def test_weekly_more_than_monthly():
    tds = make_tds("2022-01-01", "2022-12-31")
    monthly = get_rebalance_dates(tds, date(2022, 1, 1), date(2022, 12, 31), "monthly")
    weekly = get_rebalance_dates(tds, date(2022, 1, 1), date(2022, 12, 31), "weekly")
    assert len(weekly) > len(monthly)


def test_execution_map_next_day():
    tds = make_tds("2022-01-01", "2022-01-31")
    rebals = get_rebalance_dates(tds, date(2022, 1, 1), date(2022, 1, 31), "weekly")
    emap = build_execution_map(rebals, tds)
    last_td = tds[-1]
    for t, t1 in emap.items():
        if t < last_td:
            assert t1 > t, "执行日必须晚于选股日（非末尾交易日）"


# ── 大盘过滤测试 ──────────────────────────────────────────

def test_market_crash_triggers():
    dates = pd.date_range("2022-01-01", periods=5, freq="B")
    bench = pd.DataFrame({
        "close": [100, 98, 95, 97, 99],
        "pct_change": [0, -2.0, -3.2, 2.1, 2.1],
        "vol_ratio": [1.0, 1.0, 2.0, 1.0, 1.0],
    }, index=dates)
    assert is_market_crash(dates[2], bench) is True


def test_market_crash_not_triggered_low_drop():
    dates = pd.date_range("2022-01-01", periods=3, freq="B")
    bench = pd.DataFrame({
        "pct_change": [0, -1.5, 0],  # < 2% 跌幅
        "vol_ratio": [1.0, 2.0, 1.0],
    }, index=dates)
    assert is_market_crash(dates[1], bench) is False


def test_market_crash_not_triggered_low_volume():
    dates = pd.date_range("2022-01-01", periods=3, freq="B")
    bench = pd.DataFrame({
        "pct_change": [0, -3.0, 0],
        "vol_ratio": [1.0, 1.2, 1.0],   # 量比 < 1.5
    }, index=dates)
    assert is_market_crash(dates[1], bench) is False


# ── 5条件选股测试 ─────────────────────────────────────────

def _make_select_params(**kwargs):
    defaults = dict(
        max_float_mktcap=200.0,
        min_turnover_rate=3.0,
        min_volume_ratio=1.2,
        max_amplitude=5.0,
        limitup_lookback=20,
        max_positions=50,
    )
    defaults.update(kwargs)
    return BacktestParams(**defaults)


def test_condition1_float_mktcap():
    """流通市值 > 200亿的股票应被过滤"""
    codes = ["A", "B"]
    dates = pd.bdate_range("2022-01-01", periods=25)
    date_t = dates[-1]

    universe = pd.DataFrame({
        "code": codes, "name": codes,
        "float_mktcap": [50.0, 300.0],  # B 超标
        "is_st": [False, False],
        "list_date": [pd.Timestamp("2020-01-01")] * 2,
    })
    params = _make_select_params()

    result = select_by_conditions(
        date=date_t,
        universe=universe,
        panel_close=make_panels(codes, dates, 10.0),
        panel_turnover=make_panels(codes, dates, 5.0),
        panel_volume_ratio=make_panels(codes, dates, 2.0),
        panel_amplitude=make_panels(codes, dates, 3.0),
        panel_had_limitup=make_panels(codes, dates, True),
        params=params,
    )
    assert "A" in result
    assert "B" not in result


def test_condition2_turnover_rate():
    """换手率 < 3% 的股票应被过滤"""
    codes = ["A", "B"]
    dates = pd.bdate_range("2022-01-01", periods=25)
    universe = make_universe(codes)
    params = _make_select_params()

    turn = make_panels(codes, dates, 5.0)
    turn.loc[dates[-1], "B"] = 1.0  # B 换手率不足

    result = select_by_conditions(
        date=dates[-1], universe=universe,
        panel_close=make_panels(codes, dates, 10.0),
        panel_turnover=turn,
        panel_volume_ratio=make_panels(codes, dates, 2.0),
        panel_amplitude=make_panels(codes, dates, 3.0),
        panel_had_limitup=make_panels(codes, dates, True),
        params=params,
    )
    assert "A" in result
    assert "B" not in result


def test_condition3_volume_ratio():
    """量比 < 1.2 的股票应被过滤"""
    codes = ["A", "B"]
    dates = pd.bdate_range("2022-01-01", periods=25)
    universe = make_universe(codes)
    params = _make_select_params()

    vr = make_panels(codes, dates, 2.0)
    vr.loc[dates[-1], "B"] = 0.8  # B 量比不足

    result = select_by_conditions(
        date=dates[-1], universe=universe,
        panel_close=make_panels(codes, dates, 10.0),
        panel_turnover=make_panels(codes, dates, 5.0),
        panel_volume_ratio=vr,
        panel_amplitude=make_panels(codes, dates, 3.0),
        panel_had_limitup=make_panels(codes, dates, True),
        params=params,
    )
    assert "A" in result
    assert "B" not in result


def test_condition4_amplitude():
    """振幅 > 5% 的股票应被过滤"""
    codes = ["A", "B"]
    dates = pd.bdate_range("2022-01-01", periods=25)
    universe = make_universe(codes)
    params = _make_select_params()

    amp = make_panels(codes, dates, 3.0)
    amp.loc[dates[-1], "B"] = 7.0  # B 振幅超标

    result = select_by_conditions(
        date=dates[-1], universe=universe,
        panel_close=make_panels(codes, dates, 10.0),
        panel_turnover=make_panels(codes, dates, 5.0),
        panel_volume_ratio=make_panels(codes, dates, 2.0),
        panel_amplitude=amp,
        panel_had_limitup=make_panels(codes, dates, True),
        params=params,
    )
    assert "A" in result
    assert "B" not in result


def test_condition5_limitup():
    """近期无涨停的股票应被过滤"""
    codes = ["A", "B"]
    dates = pd.bdate_range("2022-01-01", periods=25)
    universe = make_universe(codes)
    params = _make_select_params()

    lu = make_panels(codes, dates, True).astype(bool)
    lu["B"] = False  # B 无涨停

    result = select_by_conditions(
        date=dates[-1], universe=universe,
        panel_close=make_panels(codes, dates, 10.0),
        panel_turnover=make_panels(codes, dates, 5.0),
        panel_volume_ratio=make_panels(codes, dates, 2.0),
        panel_amplitude=make_panels(codes, dates, 3.0),
        panel_had_limitup=lu,
        params=params,
    )
    assert "A" in result
    assert "B" not in result


def test_max_positions_cap():
    """超出 max_positions 时按换手率降序截取"""
    codes = [f"S{i:03d}" for i in range(30)]
    dates = pd.bdate_range("2022-01-01", periods=25)
    universe = make_universe(codes)
    params = _make_select_params(max_positions=10)

    # 赋予不同换手率
    turn = make_panels(codes, dates, 5.0)
    for j, c in enumerate(codes):
        turn[c] = float(j + 1)

    result = select_by_conditions(
        date=dates[-1], universe=universe,
        panel_close=make_panels(codes, dates, 10.0),
        panel_turnover=turn,
        panel_volume_ratio=make_panels(codes, dates, 2.0),
        panel_amplitude=make_panels(codes, dates, 3.0),
        panel_had_limitup=make_panels(codes, dates, True),
        params=params,
    )
    assert len(result) == 10


# ── 绩效指标测试 ──────────────────────────────────────────

def test_calc_performance_positive():
    dates = pd.date_range("2022-01-01", periods=252, freq="B")
    nav = pd.Series(np.linspace(1.0, 1.4, 252), index=dates)
    bench = pd.Series(np.linspace(1.0, 1.1, 252), index=dates)
    m = calc_performance(nav, bench, BacktestParams())
    assert m.total_return > 0
    assert m.max_drawdown <= 0
    assert 0 <= m.win_rate <= 1


def test_max_drawdown_negative():
    dates = pd.date_range("2022-01-01", periods=100, freq="B")
    vals = np.concatenate([np.linspace(1.0, 1.5, 50), np.linspace(1.5, 1.2, 50)])
    nav = pd.Series(vals, index=dates)
    bench = pd.Series(np.ones(100), index=dates)
    m = calc_performance(nav, bench, BacktestParams())
    assert m.max_drawdown < 0
