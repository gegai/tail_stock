from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from app.config import settings
from app.models import BacktestRecordSummary, BacktestResponse


def records_dir() -> Path:
    """返回本地回测记录目录，不存在时自动创建。

    回测记录属于用户本机数据，不上传、不外发。Electron 打包后会写到
    APPDATA 下的 article-tail-strategy/storage/backtest_records。
    """
    path = settings.storage_root / "backtest_records"
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_backtest_record(result: BacktestResponse) -> BacktestRecordSummary:
    """保存完整回测结果，并返回列表页需要的摘要。

    文件名里包含创建时间和随机后缀，避免同一秒多次回测产生重名。
    JSON 使用 ensure_ascii=False，中文股票名和规则名可以直接读。
    """
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
    """列出本地保存的回测记录，按创建时间倒序返回。

    如果遇到损坏的 JSON 文件，直接跳过，避免一个坏记录导致整个历史列表打不开。
    """
    summaries: list[BacktestRecordSummary] = []
    for path in records_dir().glob("*.json"):
        try:
            summaries.append(_summary_from_payload(json.loads(path.read_text(encoding="utf-8"))))
        except Exception:
            continue
    return sorted(summaries, key=lambda item: item.created_at, reverse=True)


def load_backtest_record(record_id: str) -> BacktestResponse:
    """按 id 读取一条完整回测记录。"""
    path = records_dir() / f"{record_id}.json"
    if not path.exists():
        raise FileNotFoundError(record_id)
    payload = json.loads(path.read_text(encoding="utf-8"))
    return BacktestResponse.model_validate(payload["result"])


def delete_backtest_record(record_id: str) -> None:
    """删除一条本地回测记录。"""
    path = records_dir() / f"{record_id}.json"
    if not path.exists():
        raise FileNotFoundError(record_id)
    path.unlink()


def _summary_from_payload(payload: dict) -> BacktestRecordSummary:
    """从完整记录数据中抽取历史列表需要的摘要字段。"""
    result = payload["result"]
    params = result["params"]
    metrics = result["metrics"]
    return BacktestRecordSummary(
        id=payload["id"],
        created_at=payload["created_at"],
        start_date=str(params["start_date"]),
        end_date=str(params["end_date"]),
        total_return=float(metrics["total_return"]),
        annualized_return=float(metrics.get("annualized_return", 0.0)),
        max_drawdown=float(metrics["max_drawdown"]),
        win_rate=float(metrics["win_rate"]),
        trade_count=int(metrics["trade_count"]),
    )
