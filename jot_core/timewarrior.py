from __future__ import annotations

from pathlib import Path
from typing import Any

from .frontmatter import locked_document, read_document, write_document
from .index import update_chain_note_index, update_project_note_index, update_task_note_index
from .models import AppConfig, ResolvedTask
from .nautical import chain_id_for_task
from .notes import (
    ensure_chain_note,
    ensure_project_note,
    ensure_task_note,
    find_chain_note,
    find_project_note,
    find_task_note,
)
from .ops import append_op, iso_now


TIMEW_TAGS_KEY = "timew_tags"


def resolve_timewarrior_tags(config: AppConfig, task: ResolvedTask) -> dict[str, Any]:
    candidates: list[tuple[str, str, Path | None]] = [
        ("task", task.task_short_uuid, find_task_note(config, task)),
    ]
    chain_id = chain_id_for_task(task.task)
    if chain_id:
        candidates.append(("chain", chain_id, find_chain_note(config, task)))
    candidates.extend(
        ("project", project_name, find_project_note(config, project_name))
        for project_name in _project_ancestors(task.project)
    )

    for scope, reference, path in candidates:
        if path is None:
            continue
        metadata, _body = read_document(path)
        if TIMEW_TAGS_KEY not in metadata:
            continue
        tags = _tags_from_metadata(metadata[TIMEW_TAGS_KEY], path=path)
        return {
            "enabled": config.timewarrior_enabled,
            "tags": tags,
            "source": {
                "scope": scope,
                "reference": reference,
                "path": str(path),
            },
            "explicitly_disabled": not tags,
        }

    return {
        "enabled": config.timewarrior_enabled,
        "tags": [],
        "source": None,
        "explicitly_disabled": False,
    }


def set_timewarrior_tags(
    config: AppConfig,
    *,
    scope: str,
    reference: str,
    tags: list[str],
    task: ResolvedTask | None = None,
) -> dict[str, Any]:
    normalized_tags = _normalize_tags(tags)
    if not normalized_tags:
        raise RuntimeError("timew set requires at least one non-empty tag")
    return _mutate_timewarrior_tags(
        config,
        scope=scope,
        reference=reference,
        task=task,
        operation="set",
        value=normalized_tags,
    )


def clear_timewarrior_tags(
    config: AppConfig,
    *,
    scope: str,
    reference: str,
    task: ResolvedTask | None = None,
) -> dict[str, Any]:
    return _mutate_timewarrior_tags(
        config,
        scope=scope,
        reference=reference,
        task=task,
        operation="clear",
        value=[],
    )


def inherit_timewarrior_tags(
    config: AppConfig,
    *,
    scope: str,
    reference: str,
    task: ResolvedTask | None = None,
) -> dict[str, Any]:
    note_path = _find_scope_note(config, scope=scope, reference=reference, task=task)
    if note_path is None:
        return _mutation_payload(
            config,
            scope=scope,
            reference=reference,
            operation="inherit",
            note_path=None,
            tags=None,
            changed=False,
        )
    with locked_document(note_path) as (metadata, body):
        changed = TIMEW_TAGS_KEY in metadata
        if changed:
            metadata.pop(TIMEW_TAGS_KEY, None)
            metadata["updated"] = iso_now()
            write_document(note_path, metadata, body)
    if changed:
        _finalize_metadata_change(config, scope, reference, note_path, task)
    return _mutation_payload(
        config,
        scope=scope,
        reference=reference,
        operation="inherit",
        note_path=note_path,
        tags=None,
        changed=changed,
    )


def _mutate_timewarrior_tags(
    config: AppConfig,
    *,
    scope: str,
    reference: str,
    task: ResolvedTask | None,
    operation: str,
    value: list[str],
) -> dict[str, Any]:
    note_path = _ensure_scope_note(config, scope=scope, reference=reference, task=task)
    with locked_document(note_path) as (metadata, body):
        previous = metadata.get(TIMEW_TAGS_KEY, object())
        changed = previous != value
        if changed:
            metadata[TIMEW_TAGS_KEY] = list(value)
            metadata["updated"] = iso_now()
            write_document(note_path, metadata, body)
    if changed:
        _finalize_metadata_change(config, scope, reference, note_path, task)
    return _mutation_payload(
        config,
        scope=scope,
        reference=reference,
        operation=operation,
        note_path=note_path,
        tags=value,
        changed=changed,
    )


def _ensure_scope_note(
    config: AppConfig,
    *,
    scope: str,
    reference: str,
    task: ResolvedTask | None,
) -> Path:
    if scope == "task":
        return ensure_task_note(config, _require_task(task)).note_path
    if scope == "chain":
        return ensure_chain_note(config, _require_task(task)).note_path
    if scope == "project":
        return ensure_project_note(config, reference).note_path
    raise RuntimeError(f"unsupported Timewarrior metadata scope '{scope}'")


def _find_scope_note(
    config: AppConfig,
    *,
    scope: str,
    reference: str,
    task: ResolvedTask | None,
) -> Path | None:
    if scope == "task":
        return find_task_note(config, _require_task(task))
    if scope == "chain":
        return find_chain_note(config, _require_task(task))
    if scope == "project":
        return find_project_note(config, reference)
    raise RuntimeError(f"unsupported Timewarrior metadata scope '{scope}'")


def _finalize_metadata_change(
    config: AppConfig,
    scope: str,
    reference: str,
    note_path: Path,
    task: ResolvedTask | None,
) -> None:
    if scope == "task":
        update_task_note_index(config, _require_task(task), note_path)
    elif scope == "chain":
        update_chain_note_index(config, _require_task(task), note_path)
    else:
        update_project_note_index(config, reference, note_path)
    append_op(
        config,
        "timewarrior_metadata_update",
        note_kind=scope,
        task_short_uuid=task.task_short_uuid if task else None,
        task_uuid=task.task_uuid if task else None,
        chain_id=chain_id_for_task(task.task) if task and scope == "chain" else None,
        project=reference if scope == "project" else None,
        path=str(note_path),
    )


def _mutation_payload(
    config: AppConfig,
    *,
    scope: str,
    reference: str,
    operation: str,
    note_path: Path | None,
    tags: list[str] | None,
    changed: bool,
) -> dict[str, Any]:
    return {
        "enabled": config.timewarrior_enabled,
        "operation": operation,
        "scope": scope,
        "reference": reference,
        "tags": tags,
        "path": str(note_path) if note_path else None,
        "changed": changed,
    }


def _tags_from_metadata(value: object, *, path: Path) -> list[str]:
    if isinstance(value, list):
        return _normalize_tags([str(item) for item in value])
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if value in (None, ""):
        return []
    raise RuntimeError(f"invalid {TIMEW_TAGS_KEY} metadata in {path}; expected a string list")


def _normalize_tags(tags: list[str]) -> list[str]:
    normalized: list[str] = []
    for raw in tags:
        tag = str(raw or "").strip()
        if tag and tag not in normalized:
            normalized.append(tag)
    return normalized


def _project_ancestors(project: str) -> list[str]:
    parts = [part.strip() for part in str(project or "").split(".") if part.strip()]
    return [".".join(parts[:end]) for end in range(len(parts), 0, -1)]


def _require_task(task: ResolvedTask | None) -> ResolvedTask:
    if task is None:
        raise RuntimeError("task or chain Timewarrior metadata requires a resolved task")
    return task
