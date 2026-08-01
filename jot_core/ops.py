from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .frontmatter import atomic_write_text, exclusive_file_lock
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
        _rotate_ops_unlocked(config, path)


def _rotate_ops_unlocked(config: AppConfig, path: Path) -> None:
    maximum = int(getattr(config, "ops_max_entries", 0) or 0)
    keep = int(getattr(config, "ops_keep_entries", 0) or 0)
    if maximum <= 0 or keep >= maximum:
        return
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    if len(lines) <= maximum:
        return
    archived = lines[:-keep] if keep else lines
    retained = lines[-keep:] if keep else []
    archive_dir = config.root_dir / "ops-archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    archive_path = archive_dir / f"ops-{stamp}.jsonl"
    counter = 1
    while archive_path.exists():
        archive_path = archive_dir / f"ops-{stamp}-{counter}.jsonl"
        counter += 1
    atomic_write_text(archive_path, "".join(archived))
    atomic_write_text(path, "".join(retained))


def read_ops(config: AppConfig) -> list[dict[str, Any]]:
    path = ops_log_path(config)
    items: list[dict[str, Any]] = []
    with exclusive_file_lock(path):
        for source in (*_ops_archive_paths(config), path):
            if not source.exists():
                continue
            with source.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    text = line.strip()
                    if not text:
                        continue
                    try:
                        data = json.loads(text)
                    except json.JSONDecodeError as exc:
                        raise RuntimeError(
                            f"invalid operations log record at {source}:{line_number}: {exc.msg}"
                        ) from exc
                    if not isinstance(data, dict):
                        raise RuntimeError(
                            f"invalid operations log record at {source}:{line_number}: expected an object"
                        )
                    items.append(data)
    return items


def _ops_archive_paths(config: AppConfig) -> list[Path]:
    archive_dir = config.root_dir / "ops-archive"
    if not archive_dir.exists():
        return []
    return sorted(archive_dir.glob("ops-*.jsonl"))
