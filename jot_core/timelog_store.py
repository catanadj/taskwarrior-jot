"""Persistence helpers for pending timelog sessions."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from .frontmatter import atomic_write_text
from .models import AppConfig, TimelogSessionRecord


def session_store_path(config: AppConfig) -> Path:
    return config.root_dir / "timelog-pending.json"


def read_sessions(path: Path) -> dict[str, TimelogSessionRecord]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid timelog session store: {path}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"invalid timelog session store: {path}")
    sessions = data.get("sessions", data)
    if not isinstance(sessions, dict):
        raise RuntimeError(f"invalid timelog session store: {path}")
    return {
        str(key): cast(TimelogSessionRecord, value)
        for key, value in sessions.items()
        if isinstance(value, dict)
    }


def write_sessions(path: Path, sessions: dict[str, TimelogSessionRecord]) -> None:
    payload = {
        "version": 1,
        "sessions": sessions,
        "updated": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
