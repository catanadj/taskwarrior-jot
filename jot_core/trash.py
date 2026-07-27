from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .frontmatter import read_document
from .index import rebuild_index, save_index
from .models import AppConfig
from .notes import trash_manifest_path
from .ops import append_op, read_ops


DELETE_OPS = {
    "task_note_delete": "task-note",
    "chain_note_delete": "chain-note",
    "project_note_delete": "project-note",
}


def list_trash(config: AppConfig) -> list[dict[str, Any]]:
    operations = read_ops(config)
    restored = {
        str(item.get("trash_path") or "").strip()
        for item in operations
        if str(item.get("op") or "").strip() == "trash_restore"
    }
    items: list[dict[str, Any]] = []
    known_trash_paths: set[str] = set()
    for item in operations:
        op = str(item.get("op") or "").strip()
        if op not in DELETE_OPS:
            continue
        trash_path = str(item.get("trash_path") or "").strip()
        original_path = str(item.get("path") or "").strip()
        known_trash_paths.add(trash_path)
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
    for note_path in _orphaned_trash_notes(config, known_trash_paths | restored):
        items.append(_orphan_record(config, note_path))
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
    trash_manifest_path(trash_path).unlink(missing_ok=True)
    save_index(config, rebuild_index(config))
    return {
        **item,
        "path": str(original_path),
        "trash_path": str(trash_path),
    }


def repair_trash(config: AppConfig) -> list[dict[str, Any]]:
    repaired: list[dict[str, Any]] = []
    for item in list_trash(config):
        if not item.get("orphaned"):
            continue
        kind = str(item.get("kind") or "")
        op = {
            "task-note": "task_note_delete",
            "chain-note": "chain_note_delete",
            "project-note": "project_note_delete",
        }.get(kind)
        if not op:
            continue
        append_op(
            config,
            op,
            recovered=True,
            path=item.get("path"),
            trash_path=item.get("trash_path"),
            task_short_uuid=item.get("task_short_uuid"),
            task_uuid=item.get("task_uuid"),
            chain_id=item.get("chain_id"),
            project=item.get("project"),
        )
        repaired.append(item)
    return repaired


def _orphaned_trash_notes(config: AppConfig, known_paths: set[str]) -> list[Path]:
    return [
        path
        for path in sorted(config.trash_dir.rglob("*.md"))
        if str(path) not in known_paths and _infer_original_path(config, path) is not None
    ]


def _orphan_record(config: AppConfig, note_path: Path) -> dict[str, Any]:
    manifest = _read_manifest(note_path)
    inferred = _infer_original_path(config, note_path)
    original_path = _safe_manifest_path(config, manifest.get("path")) if manifest else inferred
    if original_path is None:
        raise RuntimeError(f"cannot infer original path for trashed note: {note_path}")
    metadata, _body = _read_note_metadata(note_path)
    kind = str(manifest.get("kind") or "") if manifest else ""
    if not kind:
        kind = _kind_for_original_path(config, original_path)
    record: dict[str, Any] = {
        "id": 0,
        "kind": kind,
        "deleted_at": str(manifest.get("deleted_at") or _trash_stamp(config, note_path)),
        "path": str(original_path),
        "trash_path": str(note_path),
        "orphaned": True,
    }
    for key in ("task_short_uuid", "task_uuid", "chain_id", "project"):
        value = str(manifest.get(key) or metadata.get(key) or "").strip()
        if value:
            record[key] = value
    return record


def _read_manifest(note_path: Path) -> dict[str, Any]:
    path = trash_manifest_path(note_path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid trash manifest {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"invalid trash manifest {path}: expected an object")
    return data


def _read_note_metadata(note_path: Path) -> tuple[dict[str, Any], str]:
    return read_document(note_path)


def _infer_original_path(config: AppConfig, note_path: Path) -> Path | None:
    try:
        relative = note_path.relative_to(config.trash_dir)
    except ValueError:
        return None
    if len(relative.parts) < 2:
        return None
    original = config.root_dir.joinpath(*relative.parts[1:])
    if relative.parts[1] not in {"tasks", "chains", "projects"}:
        return None
    return original


def _safe_manifest_path(config: AppConfig, value: object) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    candidate = Path(raw)
    try:
        candidate.resolve().relative_to(config.root_dir.resolve())
    except ValueError:
        return None
    return candidate


def _kind_for_original_path(config: AppConfig, path: Path) -> str:
    try:
        relative = path.relative_to(config.root_dir)
    except ValueError:
        return ""
    return {
        "tasks": "task-note",
        "chains": "chain-note",
        "projects": "project-note",
    }.get(relative.parts[0] if relative.parts else "", "")


def _trash_stamp(config: AppConfig, note_path: Path) -> str:
    try:
        return note_path.relative_to(config.trash_dir).parts[0]
    except (IndexError, ValueError):
        return ""
