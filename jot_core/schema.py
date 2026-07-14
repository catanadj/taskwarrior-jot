from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from .frontmatter import read_document
from .models import AppConfig


NOTE_SCHEMA_VERSION = 1
NOTE_REQUIRED_FIELDS = {
    "task-note": ("task_short_uuid",),
    "chain-note": ("chain_id",),
    "project-note": ("project",),
}


def iter_note_paths(config: AppConfig) -> Iterator[Path]:
    yield from sorted(config.tasks_dir.glob("*.md"))
    yield from sorted(config.chains_dir.glob("*.md"))
    yield from sorted(config.projects_dir.glob("**/index.md"))


def inspect_note_schema(path: Path) -> dict[str, Any]:
    try:
        metadata, _body = read_document(path)
    except Exception as exc:
        return _inspection(path, status="invalid", errors=[f"cannot read note: {exc}"])

    kind = str(metadata.get("kind") or "").strip()
    errors: list[str] = []
    if kind not in NOTE_REQUIRED_FIELDS:
        errors.append(f"unknown or missing note kind '{kind}'")
    else:
        for key in NOTE_REQUIRED_FIELDS[kind]:
            if not str(metadata.get(key) or "").strip():
                errors.append(f"missing required field '{key}'")

    raw_version = metadata.get("schema_version")
    if raw_version in (None, ""):
        version = 0
    else:
        try:
            version = int(str(raw_version))
        except ValueError:
            errors.append(f"invalid schema_version '{raw_version}'")
            version = -1
        else:
            if version < 0:
                errors.append(f"invalid schema_version '{raw_version}'")

    if errors:
        status = "invalid"
    elif version > NOTE_SCHEMA_VERSION:
        status = "future"
        errors.append(
            f"schema version {version} is newer than supported version {NOTE_SCHEMA_VERSION}"
        )
    elif version < NOTE_SCHEMA_VERSION:
        status = "legacy"
    else:
        status = "current"
    return _inspection(path, kind=kind, version=version, status=status, errors=errors)


def inspect_note_schemas(config: AppConfig) -> dict[str, Any]:
    items = [inspect_note_schema(path) for path in iter_note_paths(config)]
    counts = {status: 0 for status in ("current", "legacy", "future", "invalid")}
    for item in items:
        status = str(item.get("status") or "invalid")
        counts[status] = counts.get(status, 0) + 1
    return {
        "schema_version": NOTE_SCHEMA_VERSION,
        "total": len(items),
        "counts": counts,
        "items": items,
    }


def _inspection(
    path: Path,
    *,
    kind: str = "",
    version: int | None = None,
    status: str,
    errors: list[str],
) -> dict[str, Any]:
    return {
        "path": str(path),
        "kind": kind or None,
        "version": version,
        "target_version": NOTE_SCHEMA_VERSION,
        "status": status,
        "errors": errors,
    }
