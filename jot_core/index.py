from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .frontmatter import read_document
from .models import AppConfig, ResolvedTask
from .nautical import chain_id_for_task
from .ops import iso_now, read_ops


def index_path(config: AppConfig) -> Path:
    return config.root_dir / "index.json"


def load_or_rebuild_index(config: AppConfig) -> dict[str, Any]:
    path = index_path(config)
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if _valid_index_shape(data):
                return data
        except Exception:
            pass
    data = rebuild_index(config)
    save_index(config, data)
    return data


def save_index(config: AppConfig, data: dict[str, Any]) -> None:
    data["updated"] = iso_now()
    path = index_path(config)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def rebuild_index(config: AppConfig) -> dict[str, Any]:
    data = _empty_index()
    for note_path in sorted(config.tasks_dir.glob("*.md")):
        front_matter, _body = read_document(note_path)
        short_uuid = str(front_matter.get("task_short_uuid") or "").strip()
        if not short_uuid:
            continue
        data["tasks"][short_uuid] = {
            "task_short_uuid": short_uuid,
            "task_uuid": str(front_matter.get("task_uuid") or "").strip() or None,
            "note_path": _relative_note_path(config, note_path),
            "chain_id": str(front_matter.get("chain_id") or "").strip() or None,
            "last_note_at": str(front_matter.get("updated") or "").strip() or None,
            "last_event_at": None,
        }
    for note_path in sorted(config.chains_dir.glob("*.md")):
        front_matter, _body = read_document(note_path)
        chain_id = str(front_matter.get("chain_id") or "").strip()
        if not chain_id:
            continue
        data["chains"][chain_id] = {
            "chain_id": chain_id,
            "note_path": _relative_note_path(config, note_path),
            "last_note_at": str(front_matter.get("updated") or "").strip() or None,
        }
    for item in read_ops(config):
        _merge_op(data, config, item)
    return data


def update_task_note_index(config: AppConfig, task: ResolvedTask, note_path: Path) -> None:
    data = load_or_rebuild_index(config)
    existing = data["tasks"].get(task.task_short_uuid, {})
    data["tasks"][task.task_short_uuid] = {
        "task_short_uuid": task.task_short_uuid,
        "task_uuid": task.task_uuid,
        "note_path": _relative_note_path(config, note_path),
        "chain_id": chain_id_for_task(task.task) or None,
        "last_note_at": iso_now(),
        "last_event_at": existing.get("last_event_at"),
    }
    save_index(config, data)


def update_chain_note_index(config: AppConfig, task: ResolvedTask, note_path: Path) -> None:
    chain_id = chain_id_for_task(task.task)
    if not chain_id:
        raise RuntimeError("task is not part of a Nautical chain")
    data = load_or_rebuild_index(config)
    data["chains"][chain_id] = {
        "chain_id": chain_id,
        "note_path": _relative_note_path(config, note_path),
        "last_note_at": iso_now(),
    }
    save_index(config, data)


def update_task_event_index(config: AppConfig, task: ResolvedTask) -> None:
    data = load_or_rebuild_index(config)
    existing = data["tasks"].get(task.task_short_uuid, {})
    data["tasks"][task.task_short_uuid] = {
        "task_short_uuid": task.task_short_uuid,
        "task_uuid": task.task_uuid,
        "note_path": existing.get("note_path"),
        "chain_id": chain_id_for_task(task.task) or existing.get("chain_id"),
        "last_note_at": existing.get("last_note_at"),
        "last_event_at": iso_now(),
    }
    save_index(config, data)


def _empty_index() -> dict[str, Any]:
    return {
        "version": 1,
        "updated": iso_now(),
        "tasks": {},
        "chains": {},
    }


def _merge_op(data: dict[str, Any], config: AppConfig, item: dict[str, Any]) -> None:
    op = str(item.get("op") or "").strip()
    ts = str(item.get("ts") or "").strip() or None
    short_uuid = str(item.get("task_short_uuid") or "").strip()
    task_uuid = str(item.get("task_uuid") or "").strip() or None
    chain_id = str(item.get("chain_id") or "").strip() or None
    path = str(item.get("path") or "").strip() or None

    if short_uuid:
        existing = data["tasks"].get(short_uuid, {})
        merged = {
            "task_short_uuid": short_uuid,
            "task_uuid": task_uuid or existing.get("task_uuid"),
            "note_path": existing.get("note_path"),
            "chain_id": chain_id or existing.get("chain_id"),
            "last_note_at": existing.get("last_note_at"),
            "last_event_at": existing.get("last_event_at"),
        }
        if op.startswith("task_note_"):
            merged["last_note_at"] = ts or merged["last_note_at"]
            if path:
                merged["note_path"] = _relative_note_path(config, Path(path))
        elif op == "event_add":
            merged["last_event_at"] = ts or merged["last_event_at"]
        data["tasks"][short_uuid] = merged

    if chain_id:
        existing_chain = data["chains"].get(chain_id, {})
        merged_chain = {
            "chain_id": chain_id,
            "note_path": existing_chain.get("note_path"),
            "last_note_at": existing_chain.get("last_note_at"),
        }
        if op.startswith("chain_note_"):
            merged_chain["last_note_at"] = ts or merged_chain["last_note_at"]
            if path:
                merged_chain["note_path"] = _relative_note_path(config, Path(path))
        data["chains"][chain_id] = merged_chain


def _relative_note_path(config: AppConfig, path: Path) -> str:
    try:
        return str(path.relative_to(config.root_dir))
    except ValueError:
        return str(path)


def _valid_index_shape(data: Any) -> bool:
    return (
        isinstance(data, dict)
        and isinstance(data.get("tasks"), dict)
        and isinstance(data.get("chains"), dict)
    )
