from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import difflib
import hashlib
import os
from pathlib import Path
import re
import tempfile

from .frontmatter import atomic_write_text, exclusive_file_lock, parse_document, render_document


HISTORY_LIMIT = 50
NOTE_KINDS = {"task-note", "chain-note", "project-note"}
REVISION_ID_RE = re.compile(r"^\d{8}T\d{12}Z-[a-f0-9]{12}$")


@dataclass(frozen=True, slots=True)
class NoteRevision:
    revision_id: str
    created_at: str
    digest: str
    content: str

    def to_payload(self) -> dict[str, str]:
        return {
            "revision_id": self.revision_id,
            "created_at": self.created_at,
            "digest": self.digest,
        }


def record_note_revision(path: Path, before: str, after: str) -> Path | None:
    if ".jot_history" in path.parts or not before or before == after:
        return None
    try:
        old_metadata, old_body = parse_document(before)
    except Exception:
        return None
    if str(old_metadata.get("kind") or "") not in NOTE_KINDS:
        return None
    try:
        new_metadata, new_body = parse_document(after)
        old_comparable = dict(old_metadata)
        new_comparable = dict(new_metadata)
        old_comparable.pop("updated", None)
        new_comparable.pop("updated", None)
        if old_body == new_body and old_comparable == new_comparable:
            return None
    except Exception:
        pass

    digest = hashlib.sha256(before.encode("utf-8")).hexdigest()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    revision_id = f"{stamp}-{digest[:12]}"
    folder = _history_folder(path)
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / f"{revision_id}.md"
    _write_snapshot(destination, before)
    return destination


def prune_note_history(path: Path) -> None:
    folder = _history_folder(path)
    revisions = sorted(folder.glob("*.md"), key=lambda item: item.name, reverse=True)
    for expired in revisions[HISTORY_LIMIT:]:
        expired.unlink(missing_ok=True)


def list_note_revisions(path: Path) -> tuple[NoteRevision, ...]:
    folder = _history_folder(path)
    if not folder.is_dir():
        return ()
    revisions: list[NoteRevision] = []
    for snapshot in sorted(folder.glob("*.md"), key=lambda item: item.name, reverse=True):
        revision_id = snapshot.stem
        if not REVISION_ID_RE.fullmatch(revision_id):
            continue
        content = snapshot.read_text(encoding="utf-8")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        created_raw = revision_id.split("-", 1)[0]
        created_at = datetime.strptime(created_raw, "%Y%m%dT%H%M%S%fZ").replace(
            tzinfo=timezone.utc
        ).isoformat()
        revisions.append(NoteRevision(revision_id, created_at, digest, content))
    return tuple(revisions)


def note_revision_diff(path: Path, revision_id: str) -> str:
    return note_revision_preview(path, revision_id)[0]


def note_revision_preview(path: Path, revision_id: str) -> tuple[str, str]:
    revision = _read_revision(path, revision_id)
    current_bytes = path.read_bytes()
    current = current_bytes.decode("utf-8")
    lines = difflib.unified_diff(
        revision.content.splitlines(),
        current.splitlines(),
        fromfile=f"revision {revision.revision_id}",
        tofile=str(path),
        lineterm="",
    )
    return "\n".join(lines) + "\n", hashlib.sha256(current_bytes).hexdigest()


def note_content_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def restore_note_revision(
    path: Path,
    revision_id: str,
    *,
    expected_current_digest: str = "",
) -> NoteRevision:
    revision = _read_revision(path, revision_id)
    metadata, body = parse_document(revision.content)
    metadata["updated"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    with exclusive_file_lock(path):
        if expected_current_digest and note_content_digest(path) != expected_current_digest:
            raise RuntimeError("note changed after the revision diff was shown; review the new diff")
        atomic_write_text(path, render_document(metadata, body))
    return revision


def _read_revision(path: Path, revision_id: str) -> NoteRevision:
    if not REVISION_ID_RE.fullmatch(str(revision_id or "")):
        raise RuntimeError("invalid note revision ID")
    match = next(
        (item for item in list_note_revisions(path) if item.revision_id == revision_id),
        None,
    )
    if match is None:
        raise RuntimeError(f"note revision not found: {revision_id}")
    return match


def _history_folder(path: Path) -> Path:
    identity = hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:20]
    return path.parent / ".jot_history" / identity


def _write_snapshot(path: Path, content: str) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".revision-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
