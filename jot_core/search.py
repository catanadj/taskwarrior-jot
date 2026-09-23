from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
import re
from typing import Any

from .frontmatter import read_document
from .models import AppConfig, SearchResults
from .ops import read_ops

ALLOWED_KINDS = {"task-note", "chain-note", "project-note", "event"}
HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$")
MATCH_RANK = {"title": 0, "heading": 1, "content": 2, "event": 0}


def search_all(
    config: AppConfig,
    query: str,
    *,
    kinds: set[str] | None = None,
    project: str | None = None,
    chain_id: str | None = None,
) -> SearchResults:
    needle = str(query or "").strip().lower()
    if not needle:
        raise RuntimeError("search query is empty")
    selected = set(kinds or ALLOWED_KINDS)
    task_metadata = _task_note_metadata(config)

    notes = _search_notes(config, needle, selected, project=project, chain_id=chain_id)
    trash = _search_trash_notes(config, needle, selected, project=project, chain_id=chain_id)
    events = _search_events(
        config,
        needle,
        selected,
        project=project,
        chain_id=chain_id,
        task_metadata=task_metadata,
    )
    return SearchResults.from_mapping({"notes": notes, "trash": trash, "events": events})


def _search_notes(
    config: AppConfig,
    needle: str,
    kinds: set[str],
    *,
    project: str | None,
    chain_id: str | None,
) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for base, pattern, kind in (
        (config.tasks_dir, "*.md", "task-note"),
        (config.chains_dir, "*.md", "chain-note"),
        (config.projects_dir, "**/index.md", "project-note"),
    ):
        if kind not in kinds:
            continue
        for path in sorted(base.glob(pattern)):
            metadata, body = read_document(path)
            project_name = str(metadata.get("project") or "").strip()
            note_chain_id = str(metadata.get("chain_id") or "").strip()
            if project and project_name != project:
                continue
            if chain_id and note_chain_id != chain_id:
                continue
            match_type, excerpt = _classify_match(
                needle,
                description=str(metadata.get("description") or ""),
                project=project_name,
                chain_id=note_chain_id,
                task_short_uuid=str(metadata.get("task_short_uuid") or ""),
                body=str(body or ""),
                identity=path.name,
            )
            if not match_type:
                continue
            item = {
                "kind": kind,
                "path": str(path),
                "description": str(metadata.get("description") or ""),
                "match": excerpt,
                "match_type": match_type,
                "updated": str(metadata.get("updated") or ""),
            }
            task_short_uuid = str(metadata.get("task_short_uuid") or "").strip()
            if project_name:
                item["project"] = project_name
            if note_chain_id:
                item["chain_id"] = note_chain_id
            if task_short_uuid:
                item["task_short_uuid"] = task_short_uuid
            hits.append(item)
    return _rank_note_hits(hits)


def _search_trash_notes(
    config: AppConfig,
    needle: str,
    kinds: set[str],
    *,
    project: str | None,
    chain_id: str | None,
) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    if not config.trash_dir.exists():
        return hits
    for path in sorted(config.trash_dir.rglob("*.md")):
        manifest = _read_trash_manifest(path)
        metadata, body = read_document(path)
        original_path = str(manifest.get("path") or "").strip()
        kind = str(manifest.get("kind") or metadata.get("kind") or "").strip()
        if not kind:
            kind = _infer_trash_kind(config, original_path)
        if kind not in {"task-note", "chain-note", "project-note"} or kind not in kinds:
            continue
        project_name = str(manifest.get("project") or metadata.get("project") or "").strip()
        note_chain_id = str(manifest.get("chain_id") or metadata.get("chain_id") or "").strip()
        if project and project_name != project:
            continue
        if chain_id and note_chain_id != chain_id:
            continue
        match_type, excerpt = _classify_match(
            needle,
            description=str(metadata.get("description") or ""),
            project=project_name,
            chain_id=note_chain_id,
            task_short_uuid=str(manifest.get("task_short_uuid") or metadata.get("task_short_uuid") or ""),
            body=str(body or ""),
            identity=f"{path.name} {original_path}",
        )
        if not match_type:
            continue
        item: dict[str, Any] = {
            "kind": kind,
            "path": str(path),
            "original_path": original_path,
            "deleted_at": str(manifest.get("deleted_at") or ""),
            "description": str(metadata.get("description") or ""),
            "match": excerpt,
            "match_type": match_type,
            "updated": str(metadata.get("updated") or ""),
        }
        item["_rank"] = MATCH_RANK[match_type]
        item["_sort_time"] = _timestamp_value(str(manifest.get("deleted_at") or metadata.get("updated") or ""))
        for key, value in (
            ("project", project_name),
            ("chain_id", note_chain_id),
            ("task_short_uuid", str(manifest.get("task_short_uuid") or metadata.get("task_short_uuid") or "").strip()),
        ):
            if value:
                item[key] = value
        hits.append(item)
    return _sort_ranked_hits(hits)


def _read_trash_manifest(note_path: Path) -> dict[str, Any]:
    manifest_path = note_path.with_name(f".{note_path.name}.jot-manifest.json")
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _infer_trash_kind(config: AppConfig, original_path: str) -> str:
    try:
        relative = Path(original_path).relative_to(config.root_dir)
    except ValueError:
        return ""
    if relative.parts and relative.parts[0] == config.tasks_dir.name:
        return "task-note"
    if relative.parts and relative.parts[0] == config.chains_dir.name:
        return "chain-note"
    if relative.parts and relative.parts[0] == config.projects_dir.name:
        return "project-note"
    return ""


def _search_events(
    config: AppConfig,
    needle: str,
    kinds: set[str],
    *,
    project: str | None,
    chain_id: str | None,
    task_metadata: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    if "event" not in kinds:
        return []
    hits: list[dict[str, Any]] = []
    for item in read_ops(config):
        if str(item.get("op") or "") != "event_add":
            continue
        short_uuid = str(item.get("task_short_uuid") or "").strip()
        inferred = task_metadata.get(short_uuid, {})
        event_project = str(item.get("project") or "").strip() or inferred.get("project", "")
        event_chain_id = str(item.get("chain_id") or "").strip() or inferred.get("chain_id", "")
        if project and event_project != project:
            continue
        if chain_id and event_chain_id != chain_id:
            continue
        annotation = str(item.get("annotation") or "")
        if needle not in annotation.lower():
            continue
        event = {
            "kind": "event",
            "task_short_uuid": short_uuid,
            "ts": str(item.get("ts") or ""),
            "annotation": annotation,
            "match": _excerpt(annotation, needle),
            "match_type": "event",
        }
        if event_project:
            event["project"] = event_project
        if event_chain_id:
            event["chain_id"] = event_chain_id
        hits.append(event)
    hits.sort(
        key=lambda item: (
            -_timestamp_value(str(item.get("ts") or "")),
            str(item.get("task_short_uuid") or "").casefold(),
            str(item.get("annotation") or "").casefold(),
        )
    )
    return hits


def _classify_match(
    needle: str,
    *,
    description: str,
    project: str,
    chain_id: str,
    task_short_uuid: str,
    body: str,
    identity: str,
) -> tuple[str, str]:
    for title in (description, project):
        if needle in title.casefold():
            return "title", _excerpt(title, needle)
    for line in body.splitlines():
        heading = HEADING_RE.match(line.strip())
        if heading and needle in heading.group(1).casefold():
            return "heading", _excerpt(heading.group(1), needle)
    if needle in body.casefold():
        return "content", _excerpt(body, needle)
    identity_text = " ".join((chain_id, task_short_uuid, identity))
    if needle in identity_text.casefold():
        return "content", _excerpt(identity_text, needle)
    return "", ""


def _rank_note_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for item in hits:
        item["_rank"] = MATCH_RANK[str(item.get("match_type") or "content")]
        item["_sort_time"] = _timestamp_value(str(item.get("updated") or ""))
    return _sort_ranked_hits(hits)


def _sort_ranked_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hits.sort(
        key=lambda item: (
            int(item.pop("_rank", 2)),
            -float(item.pop("_sort_time", 0.0)),
            str(item.get("path") or "").casefold(),
            str(item.get("kind") or "").casefold(),
        )
    )
    return hits


def _timestamp_value(raw: str) -> float:
    value = str(raw or "").strip()
    if not value:
        return 0.0
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.astimezone()
        return parsed.timestamp()
    except (ValueError, OverflowError, OSError):
        return 0.0


def _task_note_metadata(config: AppConfig) -> dict[str, dict[str, str]]:
    items: dict[str, dict[str, str]] = {}
    for path in sorted(config.tasks_dir.glob("*.md")):
        metadata, _body = read_document(path)
        short_uuid = str(metadata.get("task_short_uuid") or "").strip()
        if not short_uuid:
            continue
        items[short_uuid] = {
            "project": str(metadata.get("project") or "").strip(),
            "chain_id": str(metadata.get("chain_id") or "").strip(),
        }
    return items


def _excerpt(body: str, needle: str, width: int = 80) -> str:
    text = " ".join(str(body or "").split())
    if not text:
        return ""
    idx = text.lower().find(needle)
    if idx < 0:
        return text[:width]
    start = max(0, idx - width // 3)
    end = min(len(text), start + width)
    excerpt = text[start:end]
    if start > 0:
        excerpt = "..." + excerpt
    if end < len(text):
        excerpt += "..."
    return excerpt


def normalize_kinds(raw_kinds: list[str] | None) -> set[str]:
    if not raw_kinds:
        return set(ALLOWED_KINDS)
    selected = {str(item).strip() for item in raw_kinds if str(item).strip()}
    invalid = sorted(selected - ALLOWED_KINDS)
    if invalid:
        raise RuntimeError(f"unsupported kind filter: {', '.join(invalid)}")
    return selected


def normalize_project(raw_project: str | None) -> str | None:
    if raw_project is None:
        return None
    project = str(raw_project).strip()
    if not project:
        raise RuntimeError("project filter is empty")
    return project


def normalize_chain_id(raw_chain_id: str | None) -> str | None:
    if raw_chain_id is None:
        return None
    chain_id = str(raw_chain_id).strip()
    if not chain_id:
        raise RuntimeError("chain filter is empty")
    return chain_id
