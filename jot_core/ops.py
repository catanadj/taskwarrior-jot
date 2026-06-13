from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .frontmatter import exclusive_file_lock
from .models import AppConfig


def ops_log_path(config: AppConfig) -> Path:
    return config.root_dir / "ops.jsonl"


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def append_op(config: AppConfig, op: str, **fields: Any) -> None:
    path = ops_log_path(config)
    payload: dict[str, Any] = {
        "ts": iso_now(),
        "op": op,
        "ok": True,
    }
    payload.update(fields)
    with exclusive_file_lock(path):
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


def read_ops(config: AppConfig) -> list[dict[str, Any]]:
    path = ops_log_path(config)
    items: list[dict[str, Any]] = []
    with exclusive_file_lock(path):
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                try:
                    data = json.loads(text)
                except Exception:
                    continue
                if isinstance(data, dict):
                    items.append(data)
    return items
