from __future__ import annotations

from pathlib import Path
from typing import Any

from .frontmatter import read_document
from .models import AppConfig
from .notes import find_project_note, list_note_resources
from .ops import read_ops
from .progress import format_progress_tracks_summary, read_note_progress_tracks
from .search import ALLOWED_KINDS


NOTE_KIND_ALIASES = {
    "task": "task-note",
    "task-note": "task-note",
    "chain": "chain-note",
    "chain-note": "chain-note",
    "project": "project-note",
    "project-note": "project-note",
}


def list_notes(
    config: AppConfig,
    *,
    kinds: set[str] | None = None,
    project: str | None = None,
) -> list[dict[str, Any]]:
    selected = set(kinds or {"task-note", "chain-note", "project-note"})
    project_filter = str(project or "").strip()
    items: list[dict[str, Any]] = []
    if "task-note" in selected:
        items.extend(_note_inventory_task_notes(config))
    if "chain-note" in selected:
        items.extend(_note_inventory_chain_notes(config))
    if "project-note" in selected:
        items.extend(_note_inventory_project_notes(config))
    if project_filter:
        items = [
            item for item in items
            if str(item.get("project") or "").casefold() == project_filter.casefold()
        ]
    items.sort(
        key=lambda item: (
            str(item.get("updated") or ""),
            str(item.get("kind") or ""),
            str(item.get("title") or ""),
        ),
        reverse=True,
    )
    return items


def normalize_note_kinds(values: list[str] | tuple[str, ...] | None) -> set[str] | None:
    if not values:
        return None
    kinds: set[str] = set()
    for value in values:
        normalized = str(value or "").strip().casefold()
        kind = NOTE_KIND_ALIASES.get(normalized)
        if kind is None:
            allowed = ", ".join(sorted(NOTE_KIND_ALIASES))
            raise RuntimeError(f"unknown note kind '{value}'; expected one of: {allowed}")
        kinds.add(kind)
    return kinds


def list_project_notes(config: AppConfig) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(config.projects_dir.glob("**/index.md")):
        metadata, _body = read_document(path)
        project = str(metadata.get("project") or "").strip()
        if not project:
            continue
        items.append(
            {
                "project": project,
                "path": str(path),
                "updated": str(metadata.get("updated") or "").strip() or None,
            }
        )
    items.sort(key=lambda item: str(item.get("project") or "").lower())
    return items


def _note_inventory_task_notes(config: AppConfig) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(config.tasks_dir.glob("*.md")):
        metadata, body = read_document(path)
        short_uuid = str(metadata.get("task_short_uuid") or "").strip()
        if not short_uuid:
            continue
        resources = list_note_resources(path).resources
        progress = read_note_progress_tracks(path)
        items.append(
            {
                "kind": "task-note",
                "id": short_uuid,
                "task_short_uuid": short_uuid,
                "title": str(metadata.get("description") or short_uuid).strip(),
                "description": str(metadata.get("description") or "").strip(),
                "project": str(metadata.get("project") or "").strip(),
                "chain_id": str(metadata.get("chain_id") or "").strip() or None,
                "updated": str(metadata.get("updated") or "").strip() or None,
                "path": str(path),
                "preview": _body_preview(body, max_lines=2),
                "resources": len(resources),
                "progress": format_progress_tracks_summary(progress),
            }
        )
    return items


def _note_inventory_chain_notes(config: AppConfig) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(config.chains_dir.glob("*.md")):
        metadata, body = read_document(path)
        chain_id = str(metadata.get("chain_id") or "").strip()
        if not chain_id:
            continue
        resources = list_note_resources(path).resources
        progress = read_note_progress_tracks(path)
        items.append(
            {
                "kind": "chain-note",
                "id": chain_id,
                "chain_id": chain_id,
                "title": str(metadata.get("description") or chain_id).strip(),
                "description": str(metadata.get("description") or "").strip(),
                "project": str(metadata.get("project") or "").strip(),
                "updated": str(metadata.get("updated") or "").strip() or None,
                "path": str(path),
                "preview": _body_preview(body, max_lines=2),
                "resources": len(resources),
                "progress": format_progress_tracks_summary(progress),
            }
        )
    return items


def _note_inventory_project_notes(config: AppConfig) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(config.projects_dir.glob("**/index.md")):
        metadata, body = read_document(path)
        project = str(metadata.get("project") or "").strip()
        if not project:
            continue
        resources = list_note_resources(path).resources
        progress = read_note_progress_tracks(path)
        items.append(
            {
                "kind": "project-note",
                "id": project,
                "project": project,
                "title": project,
                "updated": str(metadata.get("updated") or "").strip() or None,
                "path": str(path),
                "preview": _body_preview(body, max_lines=2),
                "resources": len(resources),
                "progress": format_progress_tracks_summary(progress),
            }
        )
    return items


def recent_activity(
    config: AppConfig,
    *,
    limit: int = 20,
    kinds: set[str] | None = None,
) -> list[dict[str, Any]]:
    if limit <= 0:
        raise RuntimeError("limit must be greater than zero")
    selected = set(kinds or ALLOWED_KINDS)

    items: list[dict[str, Any]] = []
    if "task-note" in selected:
        items.extend(_recent_task_notes(config))
    if "chain-note" in selected:
        items.extend(_recent_chain_notes(config))
    if "project-note" in selected:
        items.extend(_recent_project_notes(config))
    if "event" in selected:
        items.extend(_recent_events(config))
    items.sort(key=lambda item: str(item.get("ts") or ""), reverse=True)
    return items[:limit]


def project_rollup(
    config: AppConfig,
    tasks: list[dict[str, Any]],
    project_name: str,
    *,
    limit: int = 20,
) -> dict[str, Any]:
    if limit <= 0:
        raise RuntimeError("limit must be greater than zero")
    project = str(project_name or "").strip()
    if not project:
        raise RuntimeError("project name is empty")

    exact_tasks = [
        _project_task_payload(config, item)
        for item in tasks
        if str(item.get("project") or "").strip() == project
    ]
    recent = _project_recent_activity(config, project, exact_tasks, limit=limit)
    chains = _project_chains(config, exact_tasks)
    return {
        "project": project,
        "note": _project_note_payload(config, project),
        "tasks": exact_tasks,
        "recent": recent,
        "chains": chains,
    }


def _project_note_payload(config: AppConfig, project: str) -> dict[str, Any]:
    note_path = find_project_note(config, project)
    if note_path is None:
        return {
            "exists": False,
            "path": "",
            "updated": None,
            "preview": "",
            "headings": [],
        }
    metadata, body = read_document(note_path)
    return {
        "exists": True,
        "path": str(note_path),
        "updated": str(metadata.get("updated") or "").strip() or None,
        "preview": _body_preview(body),
        "headings": _body_headings(body),
    }


def _project_task_payload(config: AppConfig, item: dict[str, Any]) -> dict[str, Any]:
    short_uuid = str(item.get("short_uuid") or "").strip()
    chain_id = str(item.get("chain_id") or "").strip()
    project = str(item.get("project") or "").strip()
    has_task_note = bool(short_uuid and list(config.tasks_dir.glob(f"{short_uuid}--*.md")))
    has_chain_note = bool(chain_id and list(config.chains_dir.glob(f"{chain_id}--*.md")))
    has_project_note = bool(project and find_project_note(config, project))
    return {
        "uuid": str(item.get("uuid") or "").strip(),
        "short_uuid": short_uuid,
        "description": str(item.get("description") or "").strip(),
        "project": project,
        "tags": list(item.get("tags") or []),
        "due": item.get("due"),
        "chain_id": chain_id or None,
        "notes": {
            "task": has_task_note,
            "chain": has_chain_note,
            "project": has_project_note,
        },
    }


def _project_recent_activity(
    config: AppConfig,
    project: str,
    tasks: list[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    short_uuids = {str(item.get("short_uuid") or "") for item in tasks if item.get("short_uuid")}
    chain_ids = {str(item.get("chain_id") or "") for item in tasks if item.get("chain_id")}
    items: list[dict[str, Any]] = []
    for item in recent_activity(config, limit=1000):
        kind = str(item.get("kind") or "")
        if kind == "project-note" and str(item.get("project") or "") == project:
            items.append(item)
        elif kind == "task-note" and str(item.get("task_short_uuid") or "") in short_uuids:
            items.append(item)
        elif kind == "chain-note" and str(item.get("chain_id") or "") in chain_ids:
            items.append(item)
        elif kind == "event" and _event_matches_project(item, project, short_uuids, chain_ids):
            items.append(item)
    items.sort(key=lambda entry: str(entry.get("ts") or ""), reverse=True)
    return items[:limit]


def _event_matches_project(
    item: dict[str, Any],
    project: str,
    short_uuids: set[str],
    chain_ids: set[str],
) -> bool:
    return (
        str(item.get("project") or "") == project
        or str(item.get("task_short_uuid") or "") in short_uuids
        or str(item.get("chain_id") or "") in chain_ids
    )


def _project_chains(config: AppConfig, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chains: dict[str, dict[str, Any]] = {}
    for task in tasks:
        chain_id = str(task.get("chain_id") or "").strip()
        if not chain_id:
            continue
        note_files = list(config.chains_dir.glob(f"{chain_id}--*.md"))
        updated = None
        path = ""
        if note_files:
            metadata, _body = read_document(note_files[0])
            updated = str(metadata.get("updated") or "").strip() or None
            path = str(note_files[0])
        row = chains.setdefault(
            chain_id,
            {
                "chain_id": chain_id,
                "task_count": 0,
                "note": bool(note_files),
                "path": path,
                "updated": updated,
            },
        )
        row["task_count"] = int(row.get("task_count") or 0) + 1
    return sorted(chains.values(), key=lambda item: str(item.get("chain_id") or ""))


def _body_preview(body: str, *, max_lines: int = 4) -> str:
    lines = [line.strip() for line in str(body or "").splitlines() if line.strip()]
    return "\n".join(lines[:max_lines])


def _body_headings(body: str) -> list[str]:
    headings: list[str] = []
    for line in str(body or "").splitlines():
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        title = stripped.lstrip("#").strip()
        if title:
            headings.append(title)
    return headings


def _recent_task_notes(config: AppConfig) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(config.tasks_dir.glob("*.md")):
        metadata, _body = read_document(path)
        ts = str(metadata.get("updated") or "").strip()
        short_uuid = str(metadata.get("task_short_uuid") or "").strip()
        if not ts or not short_uuid:
            continue
        items.append(
            {
                "ts": ts,
                "kind": "task-note",
                "task_short_uuid": short_uuid,
                "path": str(path),
                "description": str(metadata.get("description") or "").strip(),
            }
        )
    return items


def _recent_chain_notes(config: AppConfig) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(config.chains_dir.glob("*.md")):
        metadata, _body = read_document(path)
        ts = str(metadata.get("updated") or "").strip()
        chain_id = str(metadata.get("chain_id") or "").strip()
        if not ts or not chain_id:
            continue
        items.append(
            {
                "ts": ts,
                "kind": "chain-note",
                "chain_id": chain_id,
                "path": str(path),
                "description": str(metadata.get("description") or "").strip(),
            }
        )
    return items


def _recent_project_notes(config: AppConfig) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(config.projects_dir.glob("**/index.md")):
        metadata, _body = read_document(path)
        ts = str(metadata.get("updated") or "").strip()
        project = str(metadata.get("project") or "").strip()
        if not ts or not project:
            continue
        items.append(
            {
                "ts": ts,
                "kind": "project-note",
                "project": project,
                "path": str(path),
            }
        )
    return items


def _recent_events(config: AppConfig) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in read_ops(config):
        if str(item.get("op") or "") != "event_add":
            continue
        ts = str(item.get("ts") or "").strip()
        if not ts:
            continue
        items.append(
            {
                "ts": ts,
                "kind": "event",
                "task_short_uuid": str(item.get("task_short_uuid") or "").strip() or None,
                "project": str(item.get("project") or "").strip() or None,
                "chain_id": str(item.get("chain_id") or "").strip() or None,
                "annotation": str(item.get("annotation") or "").strip(),
            }
        )
    return items
