from __future__ import annotations

import re
import tempfile
from pathlib import Path

from .editor import open_in_editor


EVENT_TYPE_RE = re.compile(r"^[a-z][a-z0-9_-]*$")


def validate_event_type(event_type: str) -> str:
    value = str(event_type or "").strip().lower() or "note"
    if not EVENT_TYPE_RE.fullmatch(value):
        raise RuntimeError(f"invalid event type '{event_type}'")
    return value


def format_event_text(event_type: str, text: str) -> str:
    body = str(text or "").strip()
    if not body:
        raise RuntimeError("event text is empty")
    kind = validate_event_type(event_type)
    if kind == "note":
        return body
    return f"{kind}: {body}"


def collect_event_text(
    *,
    parts: list[str],
    stdin_text: str | None,
    editor_command: str,
    task_short_uuid: str,
    description: str,
) -> str:
    if parts:
        return " ".join(parts).strip()
    if stdin_text:
        return stdin_text.strip()
    return _text_from_editor(editor_command, task_short_uuid, description)


def _text_from_editor(editor_command: str, task_short_uuid: str, description: str) -> str:
    slug = _slugify(description or task_short_uuid)
    with tempfile.NamedTemporaryFile(
        mode="w+",
        encoding="utf-8",
        suffix=".md",
        prefix=f"jot_{task_short_uuid}_{slug}_",
        delete=False,
    ) as handle:
        path = Path(handle.name)
    try:
        open_in_editor(path, editor_command)
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            raise RuntimeError("event text is empty")
        return text
    finally:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass


def _slugify(text: str, max_len: int = 24) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return (slug[:max_len].rstrip("-") or "task")
