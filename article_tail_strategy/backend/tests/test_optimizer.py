import pytest

from app.models import BacktestParams, OptimizationParams, SweepRange
from app.services.optimizer import _score_item, build_param_combinations


def _base_request(**kwargs):
    base = BacktestParams(
        start_date="2023-01-01",
        end_date="2026-04-24",
    )
    return OptimizationParams(base_params=base, ranges=[], **kwargs)


def test_build_param_combinations_expands_cartesian_product():
    request = _base_request()
    request.ranges = [
        SweepRange(name="max_float_mktcap", values=[80, 120]),
        SweepRange(name="max_positions", values=[2, 3]),
    ]

    combos = build_param_combinations(request)

    assert len(combos) == 4
    assert {combo["max_float_mktcap"] for combo in combos} == {80, 120}
    assert {combo["max_positions"] for combo in combos} == {2, 3}
    assert all(combo["start_date"] == "2023-01-01" for combo in combos)


def test_build_param_combinations_rejects_too_many_variants():
    request = _base_request(max_combinations=2)
    request.ranges = [
        SweepRange(name="max_float_mktcap", values=[80, 120]),
        SweepRange(name="max_positions", values=[2, 3]),
    ]

    with pytest.raises(ValueError):
        build_param_combinations(request)


def test_optimizer_score_penalizes_low_trade_count_and_large_drawdown():
    request_data = {"min_trade_count": 80, "max_drawdown_limit": -0.20}
    weak_score = _score_item(
        total_return=0.20,
        annualized_return=0.08,
        max_drawdown=-0.35,
        win_rate=0.55,
        trade_count=20,
        yearly_returns={"2023": 0.05, "2024": -0.02},
        request_data=request_data,
    )
    stronger_score = _score_item(
        total_return=0.20,
        annualized_return=0.08,
        max_drawdown=-0.12,
        win_rate=0.55,
        trade_count=100,
        yearly_returns={"2023": 0.05, "2024": 0.02},
        request_data=request_data,
    )

    assert stronger_score > weak_score


def test_optimizer_score_does_not_rank_losing_strategy_above_profitable_strategy():
    request_data = {"min_trade_count": 80, "max_drawdown_limit": -0.20}
    losing_high_win_rate = _score_item(
        total_return=-0.08,
        annualized_return=-0.03,
        max_drawdown=-0.10,
        win_rate=0.70,
        trade_count=120,
        yearly_returns={"2023": 0.02, "2024": -0.10},
        request_data=request_data,
    )
    profitable_lower_win_rate = _score_item(
        total_return=0.05,
        annualized_return=0.02,
        max_drawdown=-0.12,
        win_rate=0.45,
        trade_count=80,
        yearly_returns={"2023": -0.01, "2024": 0.06},
        request_data=request_data,
    )

    assert profitable_lower_win_rate > losing_high_win_rate
