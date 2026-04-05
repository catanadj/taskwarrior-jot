from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
import re

from .frontmatter import read_document, render_document, update_metadata, write_document
from .models import AppConfig, AppendResult, NotePaths, ResolvedTask
from .nautical import chain_id_for_task
from .ops import iso_now


SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str, fallback: str = "task", max_len: int = 40) -> str:
    slug = SLUG_RE.sub("-", text.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        slug = fallback
    return slug[:max_len].rstrip("-") or fallback


def task_note_path(config: AppConfig, task: ResolvedTask) -> Path:
    existing = sorted(config.tasks_dir.glob(f"{task.task_short_uuid}--*.md"))
    if existing:
        return existing[0]
    slug = slugify(task.description or "task", fallback="task")
    return config.tasks_dir / f"{task.task_short_uuid}--{slug}.md"


def chain_note_path(config: AppConfig, chain_id: str, description: str) -> Path:
    existing = sorted(config.chains_dir.glob(f"{chain_id}--*.md"))
    if existing:
        return existing[0]
    slug = slugify(description or "chain", fallback="chain")
    return config.chains_dir / f"{chain_id}--{slug}.md"


def ensure_task_note(config: AppConfig, task: ResolvedTask) -> NotePaths:
    note_path = task_note_path(config, task)
    existed = note_path.exists()
    if not existed:
        metadata, body = _build_task_note_document(task)
        write_document(note_path, metadata, body)
    return NotePaths(note_path=note_path, existed=existed)


def find_task_note(config: AppConfig, task: ResolvedTask) -> Path | None:
    existing = sorted(config.tasks_dir.glob(f"{task.task_short_uuid}--*.md"))
    return existing[0] if existing else None


def ensure_chain_note(config: AppConfig, task: ResolvedTask) -> NotePaths:
    chain_id = chain_id_for_task(task.task)
    if not chain_id:
        raise RuntimeError("task is not part of a Nautical chain")
    note_path = chain_note_path(config, chain_id, task.description or chain_id)
    existed = note_path.exists()
    if not existed:
        metadata, body = _build_chain_note_document(task)
        write_document(note_path, metadata, body)
    return NotePaths(note_path=note_path, existed=existed)


def touch_updated(path: Path) -> None:
    update_metadata(path, {"updated": iso_now()})


def append_to_task_note(config: AppConfig, task: ResolvedTask, text: str) -> AppendResult:
    note = ensure_task_note(config, task)
    _append_text(note.note_path, text)
    touch_updated(note.note_path)
    return AppendResult(note_path=note.note_path, existed=note.existed, appended_text=text)


def append_to_chain_note(config: AppConfig, task: ResolvedTask, text: str) -> AppendResult:
    note = ensure_chain_note(config, task)
    _append_text(note.note_path, text)
    touch_updated(note.note_path)
    return AppendResult(note_path=note.note_path, existed=note.existed, appended_text=text)


def find_chain_note(config: AppConfig, task: ResolvedTask) -> Path | None:
    chain_id = chain_id_for_task(task.task)
    if not chain_id:
        return None
    existing = sorted(config.chains_dir.glob(f"{chain_id}--*.md"))
    return existing[0] if existing else None


def _render_task_note(task: ResolvedTask) -> str:
    metadata, body = _build_task_note_document(task)
    return _render_document_parts(metadata, body)


def _build_task_note_document(task: ResolvedTask) -> tuple[OrderedDict[str, object], str]:
    created = iso_now()
    chain_id = chain_id_for_task(task.task)
    link_value = str(task.task.get("link") or "").strip()
    metadata: OrderedDict[str, object] = OrderedDict(
        [
            ("kind", "task-note"),
            ("task_short_uuid", task.task_short_uuid),
            ("description", task.description or ""),
            ("project", task.project or ""),
            ("tags", list(task.tags)),
        ]
    )
    if chain_id:
        metadata["chain_id"] = chain_id
    if link_value:
        metadata["link"] = link_value
    metadata["created"] = created
    metadata["updated"] = created
    body = "\n".join(
        [
            f"# {task.description or task.task_short_uuid}",
            "",
            "## Context",
            "",
            "## Notes",
            "",
            "## References",
            "",
            "## Next steps",
        ]
    )
    return metadata, body


def _render_chain_note(task: ResolvedTask) -> str:
    metadata, body = _build_chain_note_document(task)
    return _render_document_parts(metadata, body)


def _build_chain_note_document(task: ResolvedTask) -> tuple[OrderedDict[str, object], str]:
    created = iso_now()
    chain_id = chain_id_for_task(task.task)
    metadata: OrderedDict[str, object] = OrderedDict(
        [
            ("kind", "chain-note"),
            ("chain_id", chain_id),
            ("description", task.description or ""),
            ("anchor", str(task.task.get("anchor") or "").strip() or None),
            ("cp", str(task.task.get("cp") or "").strip() or None),
            ("anchor_mode", str(task.task.get("anchor_mode") or "").strip() or None),
            ("created", created),
            ("updated", created),
        ]
    )
    body = "\n".join(
        [
            f"# {task.description or chain_id}",
            "",
            "## Purpose",
            "",
            "## Operating notes",
            "",
            "## Exceptions",
            "",
            "## References",
        ]
    )
    return metadata, body


def _append_text(path: Path, text: str) -> None:
    metadata, body = read_document(path)
    chunk = text.rstrip()
    if not chunk:
        raise RuntimeError("cannot append empty text")
    normalized = body.rstrip("\n")
    if normalized:
        normalized += "\n\n"
    normalized += chunk
    write_document(path, metadata, normalized)


def _render_document_parts(metadata: OrderedDict[str, object], body: str) -> str:
    return render_document(metadata, body)
