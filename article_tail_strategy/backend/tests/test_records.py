from datetime import date

from app.models import BacktestParams, BacktestResponse, Metrics
from app.services import records


def test_backtest_record_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(records.settings, "storage_root", tmp_path)
    result = BacktestResponse(
        params=BacktestParams(start_date=date(2026, 4, 1), end_date=date(2026, 4, 24)),
        metrics=Metrics(
            total_return=0.12,
            annualized_return=1.2,
            max_drawdown=-0.03,
            win_rate=0.6,
            trade_count=10,
            benchmark_total_return=0.05,
        ),
        nav_series=[],
        trades=[],
        selections=[],
    )

    summary = records.save_backtest_record(result)
    listed = records.list_backtest_records()
    loaded = records.load_backtest_record(summary.id)

    assert listed[0].id == summary.id
    assert listed[0].total_return == 0.12
    assert loaded.metrics.trade_count == 10

    records.delete_backtest_record(summary.id)
    assert records.list_backtest_records() == []
