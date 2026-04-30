from datetime import date

import pandas as pd

from app.models import BacktestParams, StrategyParams
from app.services.backtest import _sell_holding_period, _sell_next_day, _shares_for
from app.services.strategy import daily_screen, market_tail_rules, rule, stock_tail_metrics


def test_rule_rounds_float_values():
    r = rule("振幅", True, 4.123456, "<=5%")
    assert r.passed is True
    assert r.actual == 4.1235


def test_shares_are_rounded_to_board_lots():
    assert _shares_for(10000, 9.9) == 1000
    assert _shares_for(99, 9.9) == 0


def test_sell_next_day_returns_trigger_time(monkeypatch):
    bars = pd.DataFrame({
        "trade_time": pd.to_datetime(["2026-04-25 09:30", "2026-04-25 09:45"]),
        "high": [10.1, 10.5],
        "low": [9.9, 10.2],
        "close": [10.05, 10.4],
    })
    monkeypatch.setattr("app.services.backtest.load_stock_minutes", lambda code, day, freq: bars)
    params = BacktestParams(start_date=date(2026, 4, 1), end_date=date(2026, 4, 24), take_profit_pct=3)

    price, reason, sell_time = _sell_next_day("A.SZ", pd.Timestamp("2026-04-25"), 10.0, params)

    assert price == 10.3
    assert reason == "take_profit"
    assert sell_time == "09:45"


def test_params_match_article_defaults():
    p = StrategyParams()
    assert p.max_float_mktcap == 80
    assert p.min_turnover_rate == 3
    assert p.min_volume_ratio == 1.2
    assert p.max_volume_ratio == 1.3
    assert p.max_amplitude == 4
    assert p.limitup_lookback == 20
    assert p.require_index_above_ma20 is True
    assert p.min_market_tail_return_pct == 0.05
    assert p.min_tail_return_pct == 0.20
    assert p.min_close_vs_vwap_pct == 0.10
    assert p.max_recent_amplitude_pct == 7.0
    assert p.recent_amplitude_lookback == 5
    assert p.max_positions == 2


def test_backtest_position_cap_default_is_30_percent():
    p = BacktestParams(start_date=date(2026, 4, 1), end_date=date(2026, 4, 24))
    assert p.max_position_pct == 0.30
    assert p.take_profit_pct == 5.0
    assert p.stop_loss_pct == 5.0
    assert p.max_trade_loss_pct == 5.0
    assert p.max_hold_days == 5
    assert p.trend_exit_after_days == 3


def test_drawdown_formula_example():
    nav = pd.Series([1.0, 1.2, 0.9, 1.1])
    dd = (nav - nav.cummax()) / nav.cummax()
    assert round(float(dd.min()), 4) == -0.25


def test_daily_screen_applies_article_five_conditions(monkeypatch):
    raw = pd.DataFrame({
        "trade_date": [pd.Timestamp("2026-04-24")] * 4,
        "ts_code": ["A.SZ", "B.SZ", "C.SZ", "D.SZ"],
        "open": [10, 10, 10, 10],
        "high": [10.3, 11.0, 10.3, 10.3],
        "low": [10.0, 10.0, 10.0, 10.0],
        "close": [10.2, 10.8, 10.2, 10.2],
        "pre_close": [10, 10, 10, 10],
        "pct_chg": [2, 8, 2, 2],
        "vol": [1, 1, 1, 1],
        "amount": [1, 1, 1, 1],
        "turnover_rate": [3.5, 3.5, 2.0, 3.5],
        "volume_ratio": [1.3, 1.3, 1.3, 1.3],
        "circ_mv": [700_000, 700_000, 700_000, 700_000],
        "is_st": [False, False, False, False],
        "listed_days": [200, 200, 200, 200],
        "suspend_type": ["N", "N", "N", "N"],
    })
    basic = pd.DataFrame({
        "ts_code": ["A.SZ", "B.SZ", "C.SZ", "D.SZ"],
        "symbol": ["A", "B", "C", "D"],
        "name": ["A", "B", "C", "*ST测试"],
        "list_date": ["20200101"] * 4,
        "list_status": ["L", "L", "L", "L"],
    })
    hist = pd.DataFrame({"ts_code": ["A.SZ", "D.SZ"], "pct_chg": [10.0, 10.0]})
    monkeypatch.setattr("app.services.strategy.load_daily_date", lambda day: raw)
    monkeypatch.setattr("app.services.data.load_basic", lambda: basic)
    monkeypatch.setattr("app.services.strategy.load_daily_range", lambda start, end, cols: hist)
    monkeypatch.setattr("app.services.strategy.previous_trading_dates", lambda day, n: [pd.Timestamp("2026-04-01")])

    result, base_count = daily_screen("2026-04-24", StrategyParams())

    assert base_count == 3
    assert result["ts_code"].tolist() == ["A.SZ"]


def test_sell_next_day_uses_max_loss_when_no_tighter_stop(monkeypatch):
    bars = pd.DataFrame({
        "trade_time": pd.to_datetime(["2026-04-25 09:30", "2026-04-25 09:45"]),
        "high": [10.0, 10.1],
        "low": [9.6, 9.4],
        "close": [9.7, 9.5],
        "vol": [100, 100],
        "amount": [970, 950],
    })
    monkeypatch.setattr("app.services.backtest.load_stock_minutes", lambda code, day, freq: bars)
    params = BacktestParams(
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 24),
        stop_loss_pct=0,
        max_trade_loss_pct=5,
    )

    price, reason, sell_time = _sell_next_day("A.SZ", pd.Timestamp("2026-04-25"), 10.0, params)

    assert price == 9.5
    assert reason == "max_loss"
    assert sell_time == "09:45"


def test_sell_next_day_exits_when_trend_breaks(monkeypatch):
    bars = pd.DataFrame({
        "trade_time": pd.to_datetime([
            "2026-04-25 09:30", "2026-04-25 09:45", "2026-04-25 10:00",
            "2026-04-25 10:15", "2026-04-25 10:30",
        ]),
        "high": [10.1, 10.2, 10.15, 10.08, 10.02],
        "low": [9.95, 10.0, 9.98, 9.96, 9.94],
        "close": [10.05, 10.1, 10.04, 9.99, 9.96],
        "vol": [100, 100, 100, 100, 100],
        "amount": [1005, 1010, 1004, 999, 996],
    })
    monkeypatch.setattr("app.services.backtest.load_stock_minutes", lambda code, day, freq: bars)
    params = BacktestParams(
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 24),
        take_profit_pct=5,
        stop_loss_pct=0,
        max_trade_loss_pct=0,
        trend_break_ma_window=3,
    )

    price, reason, sell_time = _sell_next_day("A.SZ", pd.Timestamp("2026-04-25"), 10.0, params)

    assert price == 10.04
    assert reason == "trend_broken"
    assert sell_time == "10:00"


def test_holding_period_can_take_profit_after_day_one(monkeypatch):
    days = pd.DatetimeIndex(pd.to_datetime(["2026-04-24", "2026-04-27", "2026-04-28"]))
    day_one = pd.DataFrame({
        "trade_time": pd.to_datetime(["2026-04-27 09:30", "2026-04-27 15:00"]),
        "high": [10.1, 10.2],
        "low": [9.9, 9.8],
        "close": [10.0, 10.1],
        "vol": [100, 100],
        "amount": [1000, 1010],
    })
    day_two = pd.DataFrame({
        "trade_time": pd.to_datetime(["2026-04-28 09:30", "2026-04-28 09:45"]),
        "high": [10.2, 10.5],
        "low": [10.0, 10.2],
        "close": [10.1, 10.4],
        "vol": [100, 100],
        "amount": [1010, 1040],
    })
    monkeypatch.setattr("app.services.backtest.trading_days", lambda: days)
    monkeypatch.setattr(
        "app.services.backtest.load_stock_minutes",
        lambda code, day, freq: day_two if pd.Timestamp(day).date().isoformat() == "2026-04-28" else day_one,
    )
    params = BacktestParams(
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 24),
        take_profit_pct=3,
        stop_loss_pct=0,
        max_trade_loss_pct=0,
        max_hold_days=5,
        trend_exit_after_days=3,
        market_tail_weak_pct=-99,
    )

    price, reason, sell_date, sell_time = _sell_holding_period("A.SZ", pd.Timestamp("2026-04-24"), 10.0, params)

    assert price == 10.3
    assert reason == "take_profit"
    assert sell_date == "2026-04-28"
    assert sell_time == "09:45"


def test_holding_period_does_not_trend_exit_before_configured_day(monkeypatch):
    days = pd.DatetimeIndex(pd.to_datetime(["2026-04-24", "2026-04-27"]))
    bars = pd.DataFrame({
        "trade_time": pd.to_datetime([
            "2026-04-27 09:30", "2026-04-27 09:45", "2026-04-27 10:00",
            "2026-04-27 10:15", "2026-04-27 15:00",
        ]),
        "high": [10.1, 10.2, 10.15, 10.08, 10.02],
        "low": [9.95, 10.0, 9.98, 9.96, 9.94],
        "close": [10.05, 10.1, 10.04, 9.99, 9.96],
        "vol": [100, 100, 100, 100, 100],
        "amount": [1005, 1010, 1004, 999, 996],
    })
    monkeypatch.setattr("app.services.backtest.trading_days", lambda: days)
    monkeypatch.setattr("app.services.backtest.load_stock_minutes", lambda code, day, freq: bars)
    params = BacktestParams(
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 24),
        take_profit_pct=5,
        stop_loss_pct=0,
        max_trade_loss_pct=0,
        max_hold_days=1,
        trend_exit_after_days=3,
        market_tail_weak_pct=-99,
    )

    price, reason, sell_date, sell_time = _sell_holding_period("A.SZ", pd.Timestamp("2026-04-24"), 10.0, params)

    assert price == 9.96
    assert reason == "close"
    assert sell_date == "2026-04-27"
    assert sell_time == "15:00"


def test_sell_next_day_clears_when_market_tail_weak(monkeypatch):
    stock_bars = pd.DataFrame({
        "trade_time": pd.to_datetime(["2026-04-25 14:30", "2026-04-25 14:45", "2026-04-25 15:00"]),
        "high": [10.1, 10.05, 10.0],
        "low": [9.95, 9.95, 9.9],
        "close": [10.0, 9.98, 9.96],
        "vol": [100, 100, 100],
        "amount": [1000, 998, 996],
    })
    index_bars = pd.DataFrame({
        "trade_time": pd.to_datetime(["2026-04-25 14:30", "2026-04-25 14:45", "2026-04-25 15:00"]),
        "open": [100, 100, 100],
        "high": [100, 100, 100],
        "low": [99, 99, 99],
        "close": [100, 99.8, 99.6],
        "vol": [100, 100, 100],
        "amount": [1, 1, 1],
    })
    monkeypatch.setattr("app.services.backtest.load_stock_minutes", lambda code, day, freq: stock_bars)
    monkeypatch.setattr("app.services.backtest.load_index_minutes", lambda code, day, freq: index_bars)
    params = BacktestParams(
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 24),
        take_profit_pct=5,
        stop_loss_pct=0,
        max_trade_loss_pct=0,
        enable_trend_exit=False,
        market_tail_weak_pct=-0.3,
    )

    price, reason, sell_time = _sell_next_day("A.SZ", pd.Timestamp("2026-04-25"), 10.0, params)

    assert price == 9.96
    assert reason == "market_tail_weak"
    assert sell_time == "15:00"


def test_market_filter_flags_volume_crash_with_tail_drop(monkeypatch):
    bars = pd.DataFrame({
        "trade_time": pd.to_datetime([
            "2026-04-24 09:30", "2026-04-24 09:45", "2026-04-24 10:00",
            "2026-04-24 10:15", "2026-04-24 10:30", "2026-04-24 10:45",
            "2026-04-24 11:00", "2026-04-24 13:00", "2026-04-24 14:30",
            "2026-04-24 14:45", "2026-04-24 15:00",
        ]),
        "open": [100, 99.8, 99.6, 99.5, 99.4, 99.3, 99.2, 99.1, 98.9, 98.5, 98.3],
        "high": [100.1] * 11,
        "low": [98.0] * 11,
        "close": [99.8, 99.7, 99.6, 99.5, 99.4, 99.3, 99.2, 99.1, 98.9, 98.5, 98.2],
        "vol": [100] * 8 + [200, 220, 240],
        "amount": [1] * 11,
    })
    monkeypatch.setattr("app.services.strategy.load_index_minutes", lambda code, day, freq: bars)
    monkeypatch.setattr("app.services.strategy.previous_trading_dates", lambda day, n: list(pd.date_range("2026-03-26", periods=22)))
    monkeypatch.setattr(
        "app.services.strategy.load_index_daily",
        lambda code, start, end: pd.DataFrame({
            "trade_date": pd.date_range("2026-03-26", periods=22),
            "close": [100.0] * 21 + [101.0],
        }),
    )

    rules = market_tail_rules("2026-04-24", StrategyParams())
    crash_rule = next(r for r in rules if r.name == "大盘未放量大跌")

    assert crash_rule.passed is False
    assert "day=-1.80%" in crash_rule.actual
    assert "tail=-0.71%" in crash_rule.actual
    assert "tail_vol_ratio=2.20" in crash_rule.actual


def test_market_filter_does_not_flag_without_tail_volume_expansion(monkeypatch):
    bars = pd.DataFrame({
        "trade_time": pd.to_datetime([
            "2026-04-24 09:30", "2026-04-24 09:45", "2026-04-24 10:00",
            "2026-04-24 10:15", "2026-04-24 10:30", "2026-04-24 10:45",
            "2026-04-24 11:00", "2026-04-24 13:00", "2026-04-24 14:30",
            "2026-04-24 14:45", "2026-04-24 15:00",
        ]),
        "open": [100, 99.8, 99.6, 99.5, 99.4, 99.3, 99.2, 99.1, 98.9, 98.5, 98.3],
        "high": [100.1] * 11,
        "low": [98.0] * 11,
        "close": [99.8, 99.7, 99.6, 99.5, 99.4, 99.3, 99.2, 99.1, 98.9, 98.5, 98.2],
        "vol": [100] * 11,
        "amount": [1] * 11,
    })
    monkeypatch.setattr("app.services.strategy.load_index_minutes", lambda code, day, freq: bars)
    monkeypatch.setattr("app.services.strategy.previous_trading_dates", lambda day, n: list(pd.date_range("2026-03-26", periods=22)))
    monkeypatch.setattr(
        "app.services.strategy.load_index_daily",
        lambda code, start, end: pd.DataFrame({
            "trade_date": pd.date_range("2026-03-26", periods=22),
            "close": [100.0] * 21 + [101.0],
        }),
    )

    rules = market_tail_rules("2026-04-24", StrategyParams())
    crash_rule = next(r for r in rules if r.name == "大盘未放量大跌")

    assert crash_rule.passed is True
    assert "tail_vol_ratio=1.00" in crash_rule.actual


def test_tail_metrics_require_uptrend_vwap_and_volume(monkeypatch):
    bars = pd.DataFrame({
        "trade_date": [pd.Timestamp("2026-04-24")] * 6,
        "trade_time": pd.to_datetime([
            "2026-04-24 13:45", "2026-04-24 14:00", "2026-04-24 14:15",
            "2026-04-24 14:30", "2026-04-24 14:45", "2026-04-24 15:00",
        ]),
        "open": [10, 10.01, 10.0, 10.0, 10.1, 10.2],
        "high": [10.02, 10.03, 10.02, 10.1, 10.2, 10.35],
        "low": [9.99, 9.99, 9.98, 10.0, 10.08, 10.18],
        "close": [10, 10.01, 10.0, 10.05, 10.2, 10.3],
        "vol": [100, 100, 100, 200, 220, 250],
        "amount": [1000, 1001, 1000, 2010, 2244, 2575],
    })
    monkeypatch.setattr("app.services.strategy.load_stock_minutes", lambda code, day, freq: bars)

    rules, metrics = stock_tail_metrics("A.SZ", "2026-04-24", StrategyParams())

    assert all(r.passed for r in rules)
    assert metrics["tail_return_pct"] > 0
    assert metrics["tail_volume_ratio"] >= 1


def test_tail_metrics_rejects_weak_tail_bounce(monkeypatch):
    bars = pd.DataFrame({
        "trade_date": [pd.Timestamp("2026-04-24")] * 6,
        "trade_time": pd.to_datetime([
            "2026-04-24 13:45", "2026-04-24 14:00", "2026-04-24 14:15",
            "2026-04-24 14:30", "2026-04-24 14:45", "2026-04-24 15:00",
        ]),
        "open": [10, 10, 10, 10, 10.01, 10.02],
        "high": [10.02, 10.02, 10.02, 10.02, 10.03, 10.04],
        "low": [9.99, 9.99, 9.99, 9.99, 10.0, 10.01],
        "close": [10, 10, 10, 10.0, 10.01, 10.015],
        "vol": [100, 100, 100, 200, 220, 250],
        "amount": [1000, 1000, 1000, 2000, 2202.2, 2503.75],
    })
    monkeypatch.setattr("app.services.strategy.load_stock_minutes", lambda code, day, freq: bars)

    rules, metrics = stock_tail_metrics("A.SZ", "2026-04-24", StrategyParams())
    tail_rule = next(r for r in rules if r.name == "个股14:30后分时有效上升")

    assert tail_rule.passed is False
    assert metrics["tail_return_pct"] < StrategyParams().min_tail_return_pct
