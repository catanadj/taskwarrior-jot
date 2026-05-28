from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .index import rebuild_index, save_index
from .models import AppConfig
from .ops import append_op, read_ops


DELETE_OPS = {
    "task_note_delete": "task-note",
    "chain_note_delete": "chain-note",
    "project_note_delete": "project-note",
}


def list_trash(config: AppConfig) -> list[dict[str, Any]]:
    restored = {
        str(item.get("trash_path") or "").strip()
        for item in read_ops(config)
        if str(item.get("op") or "").strip() == "trash_restore"
    }
    items: list[dict[str, Any]] = []
    for item in read_ops(config):
        op = str(item.get("op") or "").strip()
        if op not in DELETE_OPS:
            continue
        trash_path = str(item.get("trash_path") or "").strip()
        original_path = str(item.get("path") or "").strip()
        if not trash_path or trash_path in restored or not Path(trash_path).exists():
            continue
        record = {
            "id": len(items) + 1,
            "kind": DELETE_OPS[op],
            "deleted_at": str(item.get("ts") or "").strip(),
            "path": original_path,
            "trash_path": trash_path,
        }
        for key in ("task_short_uuid", "task_uuid", "chain_id", "project"):
            value = str(item.get(key) or "").strip()
            if value:
                record[key] = value
        items.append(record)
    items.sort(key=lambda entry: str(entry.get("deleted_at") or ""), reverse=True)
    for index, item in enumerate(items, start=1):
        item["id"] = index
    return items


def restore_trash_item(config: AppConfig, item_id: int) -> dict[str, Any]:
    items = list_trash(config)
    if item_id < 1 or item_id > len(items):
        raise RuntimeError(f"trash item {item_id} does not exist")
    item = items[item_id - 1]
    trash_path = Path(str(item.get("trash_path") or ""))
    original_path = Path(str(item.get("path") or ""))
    if not trash_path.exists():
        raise RuntimeError(f"trash path does not exist: {trash_path}")
    if original_path.exists():
        raise RuntimeError(f"restore target already exists: {original_path}")
    original_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(trash_path), str(original_path))
    append_op(
        config,
        "trash_restore",
        kind=item.get("kind"),
        path=str(original_path),
        trash_path=str(trash_path),
        task_short_uuid=item.get("task_short_uuid"),
        task_uuid=item.get("task_uuid"),
        chain_id=item.get("chain_id"),
        project=item.get("project"),
    )
    save_index(config, rebuild_index(config))
    return {
        **item,
        "path": str(original_path),
        "trash_path": str(trash_path),
    }
