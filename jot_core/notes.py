from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from difflib import SequenceMatcher
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import re

from .frontmatter import atomic_write_text, exclusive_file_lock, read_document, update_metadata, write_document
from .models import AppConfig, AppendResult, DeleteResult, NotePaths, ResolvedTask
from .nautical import chain_id_for_task
from .ops import iso_now
from .resources import format_resource_line, parse_resource_bullets
from .schema import NOTE_SCHEMA_VERSION
from .templates import apply_template


SLUG_RE = re.compile(r"[^a-z0-9]+")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
HEADING_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


class NoteIdentityConflictError(RuntimeError):
    def __init__(self, label: str, candidates: list[Path], detail: str = "") -> None:
        self.label = label
        self.candidates = tuple(candidates)
        if candidates and len(candidates) > 1:
            message = f"multiple matching {label} notes found: {', '.join(map(str, candidates))}"
        else:
            message = f"note identity conflict for {label}: {detail or 'no matching identity metadata'}"
        super().__init__(message)


@dataclass(slots=True)
class HeadingInsertResult:
    note_path: Path
    existed: bool
    heading: str
    match: str
    timestamp: str
    entry: str


@dataclass(slots=True)
class HeadingReadResult:
    note_path: Path
    headings: list[dict[str, object]]


@dataclass(slots=True)
class SectionReadResult:
    note_path: Path
    heading: str
    match: str
    content: str


@dataclass(slots=True)
class ResourceListResult:
    note_path: Path
    resources: list[dict[str, object]]


@dataclass(slots=True)
class ResourceMutationResult:
    note_path: Path
    resource: dict[str, object]
    resources: list[dict[str, object]]


def slugify(text: str, fallback: str = "task", max_len: int = 40) -> str:
    slug = SLUG_RE.sub("-", text.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        slug = fallback
    return slug[:max_len].rstrip("-") or fallback


def task_note_path(config: AppConfig, task: ResolvedTask) -> Path:
    existing = sorted(config.tasks_dir.glob(f"{task.task_short_uuid}--*.md"))
    if existing:
        return _select_identity_note(
            existing,
            label=f"task {task.task_short_uuid}",
            kind="task-note",
            short_key="task_short_uuid",
            short_value=task.task_short_uuid,
            full_key="task_uuid",
            full_value=task.task_uuid,
        )
    slug = slugify(task.description or "task", fallback="task")
    return config.tasks_dir / f"{task.task_short_uuid}--{slug}.md"


def chain_note_path(config: AppConfig, chain_id: str, description: str) -> Path:
    existing = sorted(config.chains_dir.glob(f"{chain_id}--*.md"))
    if existing:
        return _select_identity_note(
            existing,
            label=f"chain {chain_id}",
            kind="chain-note",
            short_key="chain_id",
            short_value=chain_id,
        )
    slug = slugify(description or "chain", fallback="chain")
    return config.chains_dir / f"{chain_id}--{slug}.md"


def project_note_path(config: AppConfig, project_name: str) -> Path:
    normalized = str(project_name or "").strip()
    if not normalized:
        raise RuntimeError("project name is empty")
    parts = [slugify(part, fallback="project") for part in normalized.split(".") if part.strip()]
    if not parts:
        raise RuntimeError("project name is empty")
    return config.projects_dir.joinpath(*parts, "index.md")


def ensure_task_note(config: AppConfig, task: ResolvedTask) -> NotePaths:
    note_path = task_note_path(config, task)
    with exclusive_file_lock(note_path):
        existed = note_path.exists()
        if not existed:
            metadata, body = _build_task_note_document(config, task)
            write_document(note_path, metadata, body)
    return NotePaths(note_path=note_path, existed=existed)


def find_task_note(config: AppConfig, task: ResolvedTask) -> Path | None:
    existing = sorted(config.tasks_dir.glob(f"{task.task_short_uuid}--*.md"))
    if not existing:
        return None
    return _select_identity_note(
        existing,
        label=f"task {task.task_short_uuid}",
        kind="task-note",
        short_key="task_short_uuid",
        short_value=task.task_short_uuid,
        full_key="task_uuid",
        full_value=task.task_uuid,
    )


def ensure_chain_note(config: AppConfig, task: ResolvedTask) -> NotePaths:
    chain_id = chain_id_for_task(task.task)
    if not chain_id:
        raise RuntimeError("task is not part of a Nautical chain")
    note_path = chain_note_path(config, chain_id, task.description or chain_id)
    with exclusive_file_lock(note_path):
        existed = note_path.exists()
        if not existed:
            metadata, body = _build_chain_note_document(config, task)
            write_document(note_path, metadata, body)
    return NotePaths(note_path=note_path, existed=existed)


def ensure_project_note(config: AppConfig, project_name: str) -> NotePaths:
    normalized = str(project_name or "").strip()
    if not normalized:
        raise RuntimeError("project name is empty")
    existing = find_project_note(config, normalized)
    note_path = existing or project_note_path(config, normalized)
    with exclusive_file_lock(note_path):
        existed = note_path.exists()
        if not existed:
            metadata, body = _build_project_note_document(config, normalized)
            write_document(note_path, metadata, body)
    return NotePaths(note_path=note_path, existed=existed)


def touch_updated(path: Path) -> None:
    with exclusive_file_lock(path):
        _touch_updated_unlocked(path)


def _touch_updated_unlocked(path: Path) -> None:
    update_metadata(path, {"updated": iso_now()})


def append_to_task_note(config: AppConfig, task: ResolvedTask, text: str) -> AppendResult:
    note = ensure_task_note(config, task)
    with exclusive_file_lock(note.note_path):
        _append_text(note.note_path, text)
        _touch_updated_unlocked(note.note_path)
    return AppendResult(note_path=note.note_path, existed=note.existed, appended_text=text)


def append_to_chain_note(config: AppConfig, task: ResolvedTask, text: str) -> AppendResult:
    note = ensure_chain_note(config, task)
    with exclusive_file_lock(note.note_path):
        _append_text(note.note_path, text)
        _touch_updated_unlocked(note.note_path)
    return AppendResult(note_path=note.note_path, existed=note.existed, appended_text=text)


def append_to_project_note(config: AppConfig, project_name: str, text: str) -> AppendResult:
    note = ensure_project_note(config, project_name)
    with exclusive_file_lock(note.note_path):
        _append_text(note.note_path, text)
        _touch_updated_unlocked(note.note_path)
    return AppendResult(note_path=note.note_path, existed=note.existed, appended_text=text)


def delete_task_note(config: AppConfig, task: ResolvedTask) -> DeleteResult:
    note_path = find_task_note(config, task)
    if note_path is None:
        raise RuntimeError(f"task note does not exist for {task.task_short_uuid}")
    trash_path = _trash_note_path(config, note_path)
    with exclusive_file_lock(note_path):
        if not note_path.exists():
            raise RuntimeError(f"task note disappeared during delete: {note_path}")
        _move_to_trash(note_path, trash_path)
        _write_trash_manifest(config, note_path, trash_path, kind="task-note")
    return DeleteResult(note_path=note_path, trash_path=trash_path, existed=True)


def delete_chain_note(config: AppConfig, task: ResolvedTask) -> DeleteResult:
    note_path = find_chain_note(config, task)
    if note_path is None:
        raise RuntimeError(f"chain note does not exist for {task.task_short_uuid}")
    trash_path = _trash_note_path(config, note_path)
    with exclusive_file_lock(note_path):
        if not note_path.exists():
            raise RuntimeError(f"chain note disappeared during delete: {note_path}")
        _move_to_trash(note_path, trash_path)
        _write_trash_manifest(config, note_path, trash_path, kind="chain-note")
    return DeleteResult(note_path=note_path, trash_path=trash_path, existed=True)


def delete_project_note(config: AppConfig, project_name: str) -> DeleteResult:
    note_path = find_project_note(config, project_name)
    if note_path is None:
        raise RuntimeError(f"project note does not exist for {project_name}")
    trash_path = _trash_note_path(config, note_path)
    with exclusive_file_lock(note_path):
        if not note_path.exists():
            raise RuntimeError(f"project note disappeared during delete: {note_path}")
        _move_to_trash(note_path, trash_path)
        _write_trash_manifest(config, note_path, trash_path, kind="project-note")
    return DeleteResult(note_path=note_path, trash_path=trash_path, existed=True)


def preview_trash_path(config: AppConfig, note_path: Path) -> Path:
    return _trash_note_path(config, note_path)


def add_to_task_heading(
    config: AppConfig,
    task: ResolvedTask,
    heading: str,
    text: str,
    *,
    create_heading: bool = False,
    exact: bool = False,
) -> HeadingInsertResult:
    note = ensure_task_note(config, task)
    with exclusive_file_lock(note.note_path):
        result = _append_under_heading(
            note.note_path,
            heading,
            text,
            create_heading=create_heading,
            exact=exact,
        )
        _touch_updated_unlocked(note.note_path)
    return HeadingInsertResult(note_path=note.note_path, existed=note.existed, **result)


def add_to_chain_heading(
    config: AppConfig,
    task: ResolvedTask,
    heading: str,
    text: str,
    *,
    create_heading: bool = False,
    exact: bool = False,
) -> HeadingInsertResult:
    note = ensure_chain_note(config, task)
    with exclusive_file_lock(note.note_path):
        result = _append_under_heading(
            note.note_path,
            heading,
            text,
            create_heading=create_heading,
            exact=exact,
        )
        _touch_updated_unlocked(note.note_path)
    return HeadingInsertResult(note_path=note.note_path, existed=note.existed, **result)


def append_under_heading_once(
    note_path: Path,
    heading: str,
    text: str,
    *,
    guard_key: str,
    create_heading: bool = False,
    exact: bool = False,
    compact: bool = False,
) -> dict[str, str] | None:
    key = str(guard_key or "").strip()
    if not key:
        raise RuntimeError("guard key is empty")
    with exclusive_file_lock(note_path):
        _metadata, body = read_document(note_path)
        if key in body:
            return None
        result = _append_under_heading(
            note_path,
            heading,
            text,
            create_heading=create_heading,
            exact=exact,
            compact=compact,
        )
        _touch_updated_unlocked(note_path)
        return result


def add_to_project_heading(
    config: AppConfig,
    project_name: str,
    heading: str,
    text: str,
    *,
    create_heading: bool = False,
    exact: bool = False,
) -> HeadingInsertResult:
    note = ensure_project_note(config, project_name)
    with exclusive_file_lock(note.note_path):
        result = _append_under_heading(
            note.note_path,
            heading,
            text,
            create_heading=create_heading,
            exact=exact,
        )
        _touch_updated_unlocked(note.note_path)
    return HeadingInsertResult(note_path=note.note_path, existed=note.existed, **result)


def list_note_headings(note_path: Path) -> HeadingReadResult:
    _metadata, body = read_document(note_path)
    headings = [
        {
            "level": int(item["level"]),
            "title": str(item["title"]),
            "line": int(item["index"]) + 1,
        }
        for item in _collect_headings(body.splitlines())
    ]
    return HeadingReadResult(note_path=note_path, headings=headings)


def read_note_section(note_path: Path, heading: str, *, exact: bool = False) -> SectionReadResult:
    _metadata, body = read_document(note_path)
    lines = body.splitlines()
    headings = _collect_headings(lines)
    selected = _resolve_heading(headings, heading, exact=exact)
    if selected is None:
        available = ", ".join(item["title"] for item in headings) or "(none)"
        raise RuntimeError(f"heading not found for '{heading}'. available headings: {available}")
    content = _section_content(lines, selected)
    return SectionReadResult(
        note_path=note_path,
        heading=str(selected["title"]),
        match=str(selected.get("match") or "unknown"),
        content=content,
    )


def list_note_resources(note_path: Path) -> ResourceListResult:
    _metadata, body = read_document(note_path)
    resources = _note_resources(body.splitlines())
    return ResourceListResult(note_path=note_path, resources=resources)


def attach_note_resource(note_path: Path, target: str, label: str | None = None) -> ResourceMutationResult:
    with exclusive_file_lock(note_path):
        metadata, body = read_document(note_path)
        line = format_resource_line(target, label)
        lines = body.splitlines()
        headings = _collect_headings(lines)
        selected = _resolve_resource_heading(headings)
        if selected is None:
            lines = _append_new_heading(lines, "Resources")
            headings = _collect_headings(lines)
            selected = _resolve_resource_heading(headings)
        if selected is None:
            raise RuntimeError("failed to create Resources heading")
        lines = _insert_entry(lines, selected, line)
        write_document(note_path, metadata, "\n".join(lines))
        _touch_updated_unlocked(note_path)
        resources = _note_resources(lines)
        resource = resources[-1] if resources else {}
        return ResourceMutationResult(note_path=note_path, resource=resource, resources=resources)


def detach_note_resource(note_path: Path, resource_id: int) -> ResourceMutationResult:
    with exclusive_file_lock(note_path):
        metadata, body = read_document(note_path)
        lines = body.splitlines()
        section_lines = _resource_section_lines(lines)
        resources = parse_resource_bullets(section_lines)
        selected = next((item for item in resources if item.id == resource_id), None)
        if selected is None:
            raise RuntimeError(f"resource {resource_id} not found")
        del lines[selected.line - 1]
        write_document(note_path, metadata, "\n".join(lines))
        _touch_updated_unlocked(note_path)
        updated_resources = _note_resources(lines)
        return ResourceMutationResult(
            note_path=note_path,
            resource=selected.to_dict(),
            resources=updated_resources,
        )


def find_chain_note(config: AppConfig, task: ResolvedTask) -> Path | None:
    chain_id = chain_id_for_task(task.task)
    if not chain_id:
        return None
    existing = sorted(config.chains_dir.glob(f"{chain_id}--*.md"))
    if not existing:
        return None
    return _select_identity_note(
        existing,
        label=f"chain {chain_id}",
        kind="chain-note",
        short_key="chain_id",
        short_value=chain_id,
    )


def find_project_note(config: AppConfig, project_name: str) -> Path | None:
    normalized = str(project_name or "").strip()
    if not normalized:
        return None
    note_path = project_note_path(config, normalized)
    if not note_path.exists():
        return None
    return _select_identity_note(
        [note_path],
        label=f"project {normalized}",
        kind="project-note",
        short_key="project",
        short_value=normalized,
    )


def _select_identity_note(
    candidates: list[Path],
    *,
    label: str,
    kind: str,
    short_key: str,
    short_value: str,
    full_key: str | None = None,
    full_value: str | None = None,
) -> Path:
    matches: list[Path] = []
    conflicts: list[str] = []
    for path in candidates:
        try:
            metadata, _body = read_document(path)
        except Exception as exc:
            raise RuntimeError(f"cannot validate {label} note {path}: {exc}") from exc
        stored_kind = str(metadata.get("kind") or "").strip()
        stored_short = str(metadata.get(short_key) or "").strip()
        stored_full = str(metadata.get(full_key) or "").strip() if full_key else ""
        if stored_kind and stored_kind != kind:
            conflicts.append(f"{path} (kind={stored_kind})")
            continue
        if stored_short != short_value:
            conflicts.append(f"{path} ({short_key}={stored_short or 'missing'})")
            continue
        if full_key and stored_full and stored_full != str(full_value or "").strip():
            conflicts.append(f"{path} ({full_key}={stored_full})")
            continue
        matches.append(path)

    if len(matches) > 1:
        raise NoteIdentityConflictError(label, matches)
    if not matches:
        details = "; ".join(conflicts) or "no matching identity metadata"
        raise NoteIdentityConflictError(label, [], details)
    return matches[0]


def _build_task_note_document(config: AppConfig, task: ResolvedTask) -> tuple[OrderedDict[str, object], str]:
    created = iso_now()
    template_context = _template_context(
        created,
        task_short_uuid=task.task_short_uuid,
        task_uuid=task.task_uuid,
        description=task.description or "",
        project=task.project or "",
        chain_id=chain_id_for_task(task.task) or "",
        link=str(task.task.get("link") or "").strip(),
        project_path=task.project or "",
    )
    chain_id = chain_id_for_task(task.task)
    link_value = str(task.task.get("link") or "").strip()
    metadata: OrderedDict[str, object] = OrderedDict(
        [
            ("schema_version", NOTE_SCHEMA_VERSION),
            ("kind", "task-note"),
            ("task_uuid", task.task_uuid),
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
    default_body = "\n".join(
        [
            f"# {task.description or task.task_short_uuid}",
            "",
            "Created: {date} {time}",
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
    return apply_template(
        config.templates_dir,
        kind="task-note",
        context=template_context,
        default_metadata=metadata,
        default_body=default_body,
    )


def _build_chain_note_document(config: AppConfig, task: ResolvedTask) -> tuple[OrderedDict[str, object], str]:
    created = iso_now()
    chain_id = chain_id_for_task(task.task)
    template_context = _template_context(
        created,
        task_short_uuid=task.task_short_uuid,
        task_uuid=task.task_uuid,
        description=task.description or "",
        project=task.project or "",
        chain_id=chain_id or "",
        link=str(task.task.get("link") or "").strip(),
        project_path=task.project or "",
    )
    metadata: OrderedDict[str, object] = OrderedDict(
        [
            ("schema_version", NOTE_SCHEMA_VERSION),
            ("kind", "chain-note"),
            ("chain_id", chain_id),
            ("description", task.description or ""),
            ("project", task.project or ""),
            ("anchor", str(task.task.get("anchor") or "").strip() or None),
            ("cp", str(task.task.get("cp") or "").strip() or None),
            ("anchor_mode", str(task.task.get("anchor_mode") or "").strip() or None),
            ("created", created),
            ("updated", created),
        ]
    )
    default_body = "\n".join(
        [
            f"# {task.description or chain_id}",
            "",
            "Created: {date} {time}",
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
    return apply_template(
        config.templates_dir,
        kind="chain-note",
        context=template_context,
        default_metadata=metadata,
        default_body=default_body,
    )


def _build_project_note_document(config: AppConfig, project_name: str) -> tuple[OrderedDict[str, object], str]:
    created = iso_now()
    project_path = [part.strip() for part in project_name.split(".") if part.strip()]
    template_context = _template_context(
        created,
        task_short_uuid="",
        task_uuid="",
        description=project_name,
        project=project_name,
        chain_id="",
        link="",
        project_path=".".join(project_path),
    )
    metadata: OrderedDict[str, object] = OrderedDict(
        [
            ("schema_version", NOTE_SCHEMA_VERSION),
            ("kind", "project-note"),
            ("project", project_name),
            ("project_path", project_path),
            ("created", created),
            ("updated", created),
        ]
    )
    default_body = "\n".join(
        [
            f"# {project_name}",
            "",
            "Created: {date} {time}",
            "",
            "## Purpose",
            "",
            "## Context",
            "",
            "## Standards",
            "",
            "## References",
            "",
            "## Active concerns",
        ]
    )
    return apply_template(
        config.templates_dir,
        kind="project-note",
        context=template_context,
        default_metadata=metadata,
        default_body=default_body,
    )


def _template_context(created: str, **values: str) -> dict[str, str]:
    dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
    context: dict[str, str] = {
        "created": created,
        "updated": created,
        "date": dt.strftime("%Y-%m-%d"),
        "time": dt.strftime("%H:%M:%SZ"),
        "datetime": created,
    }
    context.update({key: str(value or "") for key, value in values.items()})
    return context


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


def _trash_note_path(config: AppConfig, note_path: Path) -> Path:
    stamp = datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y%m%dT%H%M%SZ")
    try:
        rel_path = note_path.relative_to(config.root_dir)
    except ValueError:
        rel_path = Path(note_path.name)
    trash_path = config.trash_dir / stamp / rel_path
    candidate = trash_path
    counter = 1
    while candidate.exists():
        candidate = trash_path.with_name(f"{trash_path.stem}-{counter}{trash_path.suffix}")
        counter += 1
    return candidate


def _move_to_trash(note_path: Path, trash_path: Path) -> None:
    trash_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(note_path), str(trash_path))


def trash_manifest_path(trash_path: Path) -> Path:
    return trash_path.with_name(f".{trash_path.name}.jot-manifest.json")


def _write_trash_manifest(config: AppConfig, note_path: Path, trash_path: Path, *, kind: str) -> None:
    metadata, _body = read_document(trash_path)
    payload: dict[str, object] = {
        "version": 1,
        "kind": kind,
        "deleted_at": iso_now(),
        "path": str(note_path),
        "trash_path": str(trash_path),
    }
    for key in ("task_uuid", "task_short_uuid", "chain_id", "project"):
        value = str(metadata.get(key) or "").strip()
        if value:
            payload[key] = value
    manifest_path = trash_manifest_path(trash_path)
    atomic_write_text(
        manifest_path,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def _append_under_heading(
    path: Path,
    heading_query: str,
    text: str,
    *,
    create_heading: bool,
    exact: bool,
    compact: bool = False,
) -> dict[str, str]:
    metadata, body = read_document(path)
    chunk = text.strip()
    if not chunk:
        raise RuntimeError("cannot append empty text")
    query = str(heading_query or "").strip()
    if not query:
        raise RuntimeError("heading is empty")

    lines = body.splitlines()
    headings = _collect_headings(lines)
    selected = _resolve_heading(headings, query, exact=exact)
    match = selected["match"] if selected else "created"
    if selected is None:
        if not create_heading:
            available = ", ".join(item["title"] for item in headings) or "(none)"
            raise RuntimeError(f"heading not found for '{query}'. available headings: {available}")
        lines = _append_new_heading(lines, query)
        headings = _collect_headings(lines)
        selected = _resolve_heading(headings, query, exact=True)
        if selected is None:
            raise RuntimeError(f"failed to create heading '{query}'")

    timestamp = _local_note_timestamp()
    entry = f"- [{timestamp}] {chunk}"
    lines = _insert_entry(lines, selected, entry, compact=compact)
    write_document(path, metadata, "\n".join(lines))
    return {
        "heading": str(selected["title"]),
        "match": str(match),
        "timestamp": timestamp,
        "entry": entry,
    }


def _local_note_timestamp() -> str:
    local = datetime.now().astimezone().replace(microsecond=0)
    zone = local.tzname() or local.strftime("%z")
    return f"{local:%Y-%m-%d %H:%M:%S} {zone}".strip()


def _collect_headings(lines: list[str]) -> list[dict[str, object]]:
    headings: list[dict[str, object]] = []
    for idx, line in enumerate(lines):
        match = HEADING_RE.match(line.strip())
        if not match:
            continue
        title = match.group(2).strip()
        headings.append(
            {
                "index": idx,
                "level": len(match.group(1)),
                "title": title,
                "norm": _normalize_heading(title),
            }
        )
    return headings


def _normalize_heading(value: str) -> str:
    text = HEADING_NORMALIZE_RE.sub(" ", str(value or "").lower()).strip()
    return re.sub(r"\s+", " ", text)


def _resolve_heading(headings: list[dict[str, object]], query: str, *, exact: bool) -> dict[str, object] | None:
    if not headings:
        return None
    query_norm = _normalize_heading(query)
    if not query_norm:
        return None

    exact_hits = [item for item in headings if item["norm"] == query_norm]
    if exact_hits:
        picked = dict(exact_hits[0])
        picked["match"] = "exact"
        return picked
    if exact:
        return None

    contains_hits = [
        item
        for item in headings
        if query_norm in str(item["norm"]) or str(item["norm"]) in query_norm
    ]
    if len(contains_hits) == 1:
        picked = dict(contains_hits[0])
        picked["match"] = "contains"
        return picked
    if len(contains_hits) > 1:
        scored = sorted(
            (
                (SequenceMatcher(None, query_norm, str(item["norm"])).ratio(), item)
                for item in contains_hits
            ),
            key=lambda pair: pair[0],
            reverse=True,
        )
        if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.08:
            titles = ", ".join(str(item["title"]) for _score, item in scored[:3])
            raise RuntimeError(f"heading '{query}' is ambiguous: {titles}")
        picked = dict(scored[0][1])
        picked["match"] = "contains"
        return picked

    scored_all = sorted(
        (
            (SequenceMatcher(None, query_norm, str(item["norm"])).ratio(), item)
            for item in headings
        ),
        key=lambda pair: pair[0],
        reverse=True,
    )
    best_score, best_item = scored_all[0]
    if best_score < 0.72:
        return None
    if len(scored_all) > 1 and best_score - scored_all[1][0] < 0.06:
        titles = ", ".join(str(item["title"]) for _score, item in scored_all[:3])
        raise RuntimeError(f"heading '{query}' is ambiguous: {titles}")
    picked = dict(best_item)
    picked["match"] = "fuzzy"
    return picked


def _append_new_heading(lines: list[str], title: str) -> list[str]:
    normalized = list(lines)
    while normalized and not normalized[-1].strip():
        normalized.pop()
    if normalized:
        normalized.extend(["", f"## {title}", ""])
    else:
        normalized.extend([f"## {title}", ""])
    return normalized


def _insert_entry(lines: list[str], heading: dict[str, object], entry: str, *, compact: bool = False) -> list[str]:
    heading_index = int(heading["index"])
    heading_level = int(heading["level"])
    next_index = len(lines)
    for idx in range(heading_index + 1, len(lines)):
        match = HEADING_RE.match(lines[idx].strip())
        if not match:
            continue
        level = len(match.group(1))
        if level <= heading_level:
            next_index = idx
            break

    section = list(lines[heading_index + 1 : next_index])
    while section and not section[-1].strip():
        section.pop()
    if section:
        section.extend([entry] if compact else ["", entry])
    else:
        section.extend(["", entry])
    new_lines = list(lines[: heading_index + 1]) + section + list(lines[next_index:])
    return new_lines


def _section_content(lines: list[str], heading: dict[str, object]) -> str:
    heading_index = int(heading["index"])
    heading_level = int(heading["level"])
    next_index = len(lines)
    for idx in range(heading_index + 1, len(lines)):
        match = HEADING_RE.match(lines[idx].strip())
        if not match:
            continue
        level = len(match.group(1))
        if level <= heading_level:
            next_index = idx
            break
    return "\n".join(lines[heading_index + 1 : next_index]).strip()


def _note_resources(lines: list[str]) -> list[dict[str, object]]:
    return [item.to_dict() for item in parse_resource_bullets(_resource_section_lines(lines))]


def _resolve_resource_heading(headings: list[dict[str, object]]) -> dict[str, object] | None:
    for title in ("Resources", "References"):
        selected = _resolve_heading(headings, title, exact=True)
        if selected is not None:
            return selected
    return None


def _resource_section_lines(lines: list[str]) -> list[tuple[int, str]]:
    headings = _collect_headings(lines)
    selected = _resolve_resource_heading(headings)
    if selected is None:
        return []
    heading_index = int(selected["index"])
    heading_level = int(selected["level"])
    next_index = len(lines)
    for idx in range(heading_index + 1, len(lines)):
        match = HEADING_RE.match(lines[idx].strip())
        if match and len(match.group(1)) <= heading_level:
            next_index = idx
            break
    return list(enumerate(lines[heading_index + 1 : next_index], start=heading_index + 1))
