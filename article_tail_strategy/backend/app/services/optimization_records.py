from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from threading import RLock
from uuid import uuid4

from app.config import settings
from app.models import (
    OptimizationParams,
    OptimizationProgress,
    OptimizationRecord,
    OptimizationRecordSummary,
    OptimizationResultItem,
)
from app.services.optimizer import _top_results

_records_lock = RLock()
_RETRYABLE_WINERRORS = {5, 32, 33}


def optimization_records_dir() -> Path:
    """返回本地参数优化记录目录。"""
    path = settings.storage_root / "optimization_records"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _record_path(record_id: str) -> Path:
    """生成某条优化记录的绝对路径，避免相对路径受工作目录影响。"""
    return (optimization_records_dir() / f"{record_id}.json").resolve()


def _replace_with_retry(temp_path: Path, path: Path) -> None:
    """用临时文件替换正式记录文件，并处理 Windows 上的短暂文件占用。

    参数优化运行时会频繁写入同一条记录，前端也会同时轮询读取记录。
    在 Windows 上，杀毒扫描、索引服务、浏览器触发的读取，或者另一个后端线程刚好打开文件时，
    `os.replace` 可能抛出 `WinError 5/32/33`。这些错误通常是几十毫秒级别的瞬时锁，
    所以这里采用短暂退避重试，而不是直接把整轮参数优化标记为失败。
    """
    delay = 0.05
    last_error: OSError | None = None
    for _ in range(30):
        try:
            os.replace(temp_path, path)
            return
        except PermissionError as exc:
            last_error = exc
        except OSError as exc:
            if getattr(exc, "winerror", None) not in _RETRYABLE_WINERRORS:
                raise
            last_error = exc
        time.sleep(delay)
        delay = min(delay * 1.5, 0.5)

    try:
        temp_path.unlink(missing_ok=True)
    except OSError:
        pass
    if last_error is not None:
        raise last_error
    raise PermissionError(path)


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
    """保存优化记录。

    参数优化会频繁追加结果和更新进度，前端也会同时读取记录。Windows 下直接覆盖
    写同一个文件，偶发会因为读写重叠抛出文件参数错误。这里先写临时文件，再原子
    替换正式文件，并用锁串行化当前后端进程内的读写。
    """
    with _records_lock:
        record.updated_at = datetime.now().isoformat(timespec="seconds")
        path = _record_path(record.id)
        payload = record.model_dump(mode="json")
        temp_path = path.with_name(f"{path.stem}.{uuid4().hex}.tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        _replace_with_retry(temp_path, path)
        return record


def load_optimization_record(record_id: str) -> OptimizationRecord:
    with _records_lock:
        path = _record_path(record_id)
        if not path.exists():
            raise FileNotFoundError(record_id)
        payload = json.loads(path.read_text(encoding="utf-8"))
        return OptimizationRecord.model_validate(payload)


def delete_optimization_record(record_id: str) -> None:
    with _records_lock:
        path = _record_path(record_id)
        if not path.exists():
            raise FileNotFoundError(record_id)
        path.unlink()


def list_optimization_records() -> list[OptimizationRecordSummary]:
    with _records_lock:
        summaries: list[OptimizationRecordSummary] = []
        for path in optimization_records_dir().glob("*.json"):
            try:
                summaries.append(_summary_from_record(OptimizationRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))))
            except Exception:
                continue
        return sorted(summaries, key=lambda item: item.updated_at, reverse=True)


def append_optimization_result(record_id: str, item: OptimizationResultItem) -> OptimizationRecord:
    with _records_lock:
        record = load_optimization_record(record_id)
        record.results.append(item)
        record.progress.best = _top_results(record.results, record.request.top_n)
        record.progress.completed = len(record.results)
        return save_optimization_record(record)


def update_optimization_progress(record_id: str, progress: OptimizationProgress) -> OptimizationRecord:
    with _records_lock:
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
