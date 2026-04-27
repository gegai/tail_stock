from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from app.config import settings
from app.models import BacktestRecordSummary, BacktestResponse


def records_dir() -> Path:
    """Return the local folder used for durable backtest records."""
    path = settings.storage_root / "backtest_records"
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_backtest_record(result: BacktestResponse) -> BacktestRecordSummary:
    """Persist a full backtest response and return its compact summary."""
    created_at = datetime.now().isoformat(timespec="seconds")
    record_id = f"{created_at.replace(':', '').replace('-', '').replace('T', '-')}-{uuid4().hex[:8]}"
    payload = {
        "id": record_id,
        "created_at": created_at,
        "result": result.model_dump(mode="json"),
    }
    path = records_dir() / f"{record_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return _summary_from_payload(payload)


def list_backtest_records() -> list[BacktestRecordSummary]:
    """List saved backtests, newest first."""
    summaries: list[BacktestRecordSummary] = []
    for path in records_dir().glob("*.json"):
        try:
            summaries.append(_summary_from_payload(json.loads(path.read_text(encoding="utf-8"))))
        except Exception:
            continue
    return sorted(summaries, key=lambda item: item.created_at, reverse=True)


def load_backtest_record(record_id: str) -> BacktestResponse:
    """Load one saved backtest by id."""
    path = records_dir() / f"{record_id}.json"
    if not path.exists():
        raise FileNotFoundError(record_id)
    payload = json.loads(path.read_text(encoding="utf-8"))
    return BacktestResponse.model_validate(payload["result"])


def delete_backtest_record(record_id: str) -> None:
    """Delete one saved backtest record from local storage."""
    path = records_dir() / f"{record_id}.json"
    if not path.exists():
        raise FileNotFoundError(record_id)
    path.unlink()


def _summary_from_payload(payload: dict) -> BacktestRecordSummary:
    result = payload["result"]
    params = result["params"]
    metrics = result["metrics"]
    return BacktestRecordSummary(
        id=payload["id"],
        created_at=payload["created_at"],
        start_date=str(params["start_date"]),
        end_date=str(params["end_date"]),
        total_return=float(metrics["total_return"]),
        max_drawdown=float(metrics["max_drawdown"]),
        win_rate=float(metrics["win_rate"]),
        trade_count=int(metrics["trade_count"]),
    )
