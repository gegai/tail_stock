from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.config import settings
from app.models import (
    OptimizationParams,
    OptimizationProgress,
    OptimizationRecord,
    OptimizationRecordSummary,
    OptimizationResultItem,
)
from app.services.optimizer import _top_results


def optimization_records_dir() -> Path:
    """返回本地参数优化记录目录。"""
    path = settings.storage_root / "optimization_records"
    path.mkdir(parents=True, exist_ok=True)
    return path


def create_optimization_record(record_id: str, request: OptimizationParams) -> OptimizationRecord:
    now = datetime.now().isoformat(timespec="seconds")
    record = OptimizationRecord(
        id=record_id,
        created_at=now,
        updated_at=now,
        request=request,
        progress=OptimizationProgress(
            job_id=record_id,
            status="queued",
            percent=0,
            completed=0,
            total=0,
            stage="排队中",
            best=[],
        ),
        results=[],
    )
    save_optimization_record(record)
    return record


def save_optimization_record(record: OptimizationRecord) -> OptimizationRecord:
    record.updated_at = datetime.now().isoformat(timespec="seconds")
    path = optimization_records_dir() / f"{record.id}.json"
    payload = record.model_dump(mode="json")
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return record


def load_optimization_record(record_id: str) -> OptimizationRecord:
    path = optimization_records_dir() / f"{record_id}.json"
    if not path.exists():
        raise FileNotFoundError(record_id)
    payload = json.loads(path.read_text(encoding="utf-8"))
    return OptimizationRecord.model_validate(payload)


def list_optimization_records() -> list[OptimizationRecordSummary]:
    summaries: list[OptimizationRecordSummary] = []
    for path in optimization_records_dir().glob("*.json"):
        try:
            summaries.append(_summary_from_record(OptimizationRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))))
        except Exception:
            continue
    return sorted(summaries, key=lambda item: item.updated_at, reverse=True)


def append_optimization_result(record_id: str, item: OptimizationResultItem) -> OptimizationRecord:
    record = load_optimization_record(record_id)
    record.results.append(item)
    record.progress.best = _top_results(record.results, record.request.top_n)
    record.progress.completed = len(record.results)
    return save_optimization_record(record)


def update_optimization_progress(record_id: str, progress: OptimizationProgress) -> OptimizationRecord:
    record = load_optimization_record(record_id)
    record.progress = progress
    return save_optimization_record(record)


def _summary_from_record(record: OptimizationRecord) -> OptimizationRecordSummary:
    best = record.progress.best[0] if record.progress.best else None
    params = record.request.base_params
    return OptimizationRecordSummary(
        id=record.id,
        created_at=record.created_at,
        updated_at=record.updated_at,
        status=record.progress.status,
        start_date=str(params.start_date),
        end_date=str(params.end_date),
        completed=record.progress.completed,
        total=record.progress.total,
        best_score=best.score if best else None,
        best_total_return=best.total_return if best else None,
        best_annualized_return=best.annualized_return if best else None,
        error=record.progress.error,
    )
