from datetime import date

from app.models import BacktestParams, OptimizationParams, OptimizationProgress, OptimizationResultItem
from app.services import optimization_records


def test_optimization_record_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(optimization_records.settings, "storage_root", tmp_path)
    request = OptimizationParams(
        base_params=BacktestParams(start_date=date(2026, 4, 1), end_date=date(2026, 4, 24)),
        ranges=[],
    )
    record = optimization_records.create_optimization_record("job-1", request)
    item = OptimizationResultItem(
        params=request.base_params.model_dump(mode="json"),
        total_return=0.12,
        annualized_return=0.8,
        max_drawdown=-0.03,
        win_rate=0.6,
        trade_count=10,
        benchmark_total_return=0.05,
        score=12.3,
    )

    optimization_records.append_optimization_result(record.id, item)
    optimization_records.update_optimization_progress(
        record.id,
        OptimizationProgress(
            job_id=record.id,
            status="error",
            percent=100,
            completed=1,
            total=2,
            stage="失败",
            best=[item],
            error="boom",
        ),
    )

    loaded = optimization_records.load_optimization_record(record.id)
    listed = optimization_records.list_optimization_records()

    assert loaded.results[0].score == 12.3
    assert listed[0].status == "error"
    assert listed[0].completed == 1
    assert listed[0].best_annualized_return == 0.8
