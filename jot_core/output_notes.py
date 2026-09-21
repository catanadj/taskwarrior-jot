"""Human-readable rendering for note, project, and resource commands."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any, Callable, Mapping


@dataclass(frozen=True)
class NoteOutputPrimitives:
    style: Callable[..., str]
    write_title: Callable[..., None]
    write_section_title: Callable[..., None]
    write_status: Callable[..., None]
    emit_field: Callable[..., None]
    resource_status_color: Callable[[str], str]
    recent_identity: Callable[[Mapping[str, Any]], str]
    recent_summary: Callable[[Mapping[str, Any]], str]


def emit_project_list(payload: Mapping[str, Any], *, p: NoteOutputPrimitives) -> None:
    items = payload.get("projects") or []
    p.write_title("Projects", blank_after=True)
    if not items:
        sys.stdout.write("(none)\n")
        return
    for item in items:
        project = str(item.get("project") or "")
        updated = str(item.get("updated") or "").strip() or "unknown"
        p.style(project, color="identity", bold=True)
        sys.stdout.write(f"{p.style(project, color='identity', bold=True)}\n")
        p.emit_field("updated", updated, indent=2)
        p.emit_field("path", str(item.get("path") or ""), indent=2)
        sys.stdout.write("\n")


def emit_notes(payload: Mapping[str, Any], *, p: NoteOutputPrimitives) -> None:
    items = payload.get("notes") or []
    p.write_title("Notes", blank_after=True)
    if not items:
        sys.stdout.write("(none)\n")
        return
    for item in items:
        kind = str(item.get("kind") or "note")
        ident = str(item.get("id") or "").strip()
        title = str(item.get("title") or "").strip()
        heading = kind + (f" {ident}" if ident else "")
        if title and title != ident:
            heading += f"  {title}"
        sys.stdout.write(f"{p.style(heading, color='identity', bold=True)}\n")
        if item.get("project"):
            p.emit_field("project", item.get("project"), indent=2)
        if item.get("chain_id"):
            p.emit_field("chain", item.get("chain_id"), indent=2)
        p.emit_field("updated", str(item.get("updated") or "").strip() or "unknown", indent=2)
        p.emit_field("path", item.get("path"), indent=2)
        if str(item.get("preview") or "").strip():
            p.emit_field("preview", item.get("preview"), indent=2)
        sys.stdout.write("\n")


def emit_compact_notes(payload: Mapping[str, Any], *, p: NoteOutputPrimitives) -> None:
    items = payload.get("notes") or []
    p.write_title("Notes", blank_after=True)
    if not items:
        sys.stdout.write("(none)\n")
        return
    groups = (
        ("task-note", "Task notes"),
        ("chain-note", "Chain notes"),
        ("project-note", "Project notes"),
    )
    for kind, label in groups:
        group = [item for item in items if str(item.get("kind") or "") == kind]
        if not group:
            continue
        p.write_section_title(f"{label} ({len(group)})")
        for item in group:
            updated = str(item.get("updated") or "unknown").strip()
            identifier = str(item.get("id") or "").strip()
            title = str(item.get("title") or "").strip()
            summary = "  ".join(part for part in (identifier, title) if part)
            line = f"{updated}  {summary}" if summary else updated
            sys.stdout.write(f"  {p.style(line, color='identity', bold=True)}\n")


def emit_note_like(command: str, payload: Mapping[str, Any], *, p: NoteOutputPrimitives) -> None:
    action = "Opened" if payload.get("opened") else "Created"
    kind = {"note": "task note", "chain": "chain note", "project": "project note"}[command]
    p.write_status(f"{action} {kind}: {payload['path']}")
    post_save = payload.get("post_save_action") or {}
    if post_save.get("action") == "complete-task":
        p.write_status(f"Completed task: {post_save.get('task_short_uuid')}")


def emit_append_like(command: str, payload: Mapping[str, Any], *, p: NoteOutputPrimitives) -> None:
    kind = {"note-append": "task note", "chain-append": "chain note", "project-append": "project note"}[command]
    prefix = "Created and appended to" if not payload.get("opened") else "Appended to"
    p.write_status(f"{prefix} {kind}: {payload['path']}")


def emit_delete(command: str, payload: Mapping[str, Any], *, p: NoteOutputPrimitives) -> None:
    kind = {"task-delete": "task note", "chain-delete": "chain note", "project-delete": "project note"}[command]
    p.write_status(f"Moved {kind} to trash", color="warning")
    p.emit_field("from", payload.get("path"), indent=0)
    p.emit_field("to", payload.get("trash_path"), indent=0)


def emit_project_show(payload: Mapping[str, Any], *, p: NoteOutputPrimitives) -> None:
    p.write_title(f"Project {payload['project']}", blank_after=True)
    note = payload.get("note") or {}
    p.write_section_title("Note:")
    if not note.get("exists"):
        if note.get("path"):
            p.emit_field("exists", "no", indent=2)
            p.emit_field("expected", note.get("path"), indent=2)
        return
    p.emit_field("path", note.get("path"), indent=2)
    for key in ("created", "updated", "preview"):
        if note.get(key):
            p.emit_field(key, note.get(key), indent=2)


def emit_project_report(payload: Mapping[str, Any], *, p: NoteOutputPrimitives) -> None:
    p.write_title(f"Project {payload.get('project')}", blank_after=True)
    note = payload.get("note") or {}
    p.write_section_title("Project note:")
    if not note.get("exists"):
        sys.stdout.write("  (none)\n")
    else:
        p.emit_field("path", note.get("path"), indent=2)
        p.emit_field("updated", note.get("updated"), indent=2)
        if note.get("preview"):
            p.emit_field("preview", note.get("preview"), indent=2)
        if note.get("headings"):
            p.emit_field("headings", ", ".join(str(item) for item in note["headings"]), indent=2)
    sys.stdout.write("\n")
    p.write_section_title("Tasks:")
    tasks = payload.get("tasks") or []
    if not tasks:
        sys.stdout.write("  (none)\n")
    for task in tasks:
        notes = task.get("notes") or {}
        labels = [name for name in ("task", "chain", "project") if notes.get(name)]
        line = f"  {task.get('short_uuid')}  {task.get('description') or ''}"
        if task.get("due"):
            line += f"  due: {task['due']}"
        if labels:
            line += f"  notes: {','.join(labels)}"
        sys.stdout.write(line + "\n")
    sys.stdout.write("\n")
    p.write_section_title("Recent:")
    recent = payload.get("recent") or []
    if not recent:
        sys.stdout.write("  (none)\n")
    for item in recent:
        line = f"  {item.get('ts')}  {item.get('kind')}"
        ident = p.recent_identity(item)
        summary = p.recent_summary(item)
        if ident:
            line += f"  {ident}"
        if summary:
            line += f"  {summary}"
        sys.stdout.write(line + "\n")
    sys.stdout.write("\n")
    p.write_section_title("Chains:")
    chains = payload.get("chains") or []
    if not chains:
        sys.stdout.write("  (none)\n")
    for chain in chains:
        note_label = "yes" if chain.get("note") else "no"
        line = f"  {chain.get('chain_id')}  tasks: {chain.get('task_count')}  note: {note_label}"
        if chain.get("updated"):
            line += f"  updated: {chain['updated']}"
        sys.stdout.write(line + "\n")
    timelog = payload.get("timelog") or {}
    sys.stdout.write("\n")
    p.write_section_title(f"Time ({timelog.get('period') or 'week'}):")
    sys.stdout.write(f"  {timelog.get('total') or '0m'} across {timelog.get('entry_count', 0)} entries\n")


def emit_cat(payload: Mapping[str, Any]) -> None:
    sys.stdout.write(str(payload.get("content") or ""))


def emit_headings(payload: Mapping[str, Any], *, p: NoteOutputPrimitives) -> None:
    p.write_title(f"Headings in {payload.get('note_kind')} note")
    p.emit_field("path", payload.get("path"), indent=0)
    headings = payload.get("headings") or []
    if not headings:
        sys.stdout.write("\n(none)\n")
        return
    sys.stdout.write("\n")
    for item in headings:
        level = int(item.get("level") or 1)
        line = p.style(f"{'#' * level} {item.get('title') or ''}", color="section", bold=True)
        if item.get("line"):
            line += f"  (line {item['line']})"
        sys.stdout.write(line + "\n")


def emit_section(payload: Mapping[str, Any]) -> None:
    content = str(payload.get("content") or "").strip()
    if content:
        sys.stdout.write(content + "\n")


def emit_resources(payload: Mapping[str, Any], *, p: NoteOutputPrimitives) -> None:
    kind = str(payload.get("note_kind") or "note")
    p.write_title(f"Resources in {kind} note")
    p.emit_field("path", payload.get("path"), indent=0)
    resources = payload.get("resources") or []
    if not resources:
        sys.stdout.write("\n(none)\n")
        return
    sys.stdout.write("\n")
    for item in resources:
        label = str(item.get("label") or "").strip()
        target = str(item.get("target") or "").strip()
        status = str(item.get("status") or "").strip()
        suffix = f"[{item.get('kind') or 'resource'}]"
        if status and status != "unchecked":
            suffix += f" {status}"
        prefix = f"{item.get('id')}. "
        shown = label if label and label != target else target
        sys.stdout.write(f"{p.style(prefix + shown, color='identity', bold=bool(label and label != target))}  {p.style(suffix, color=p.resource_status_color(status))}\n")
        if label and label != target:
            p.emit_field("target", target, indent=3)


def emit_attach(payload: Mapping[str, Any], *, p: NoteOutputPrimitives) -> None:
    resource = payload.get("resource") or {}
    p.write_status(f"Attached resource to {payload.get('note_kind')} note")
    for key in ("path",):
        p.emit_field(key, payload.get(key), indent=0)
    for key in ("id", "label", "target"):
        p.emit_field(key, resource.get(key), indent=0)


def emit_open_resource(payload: Mapping[str, Any], *, p: NoteOutputPrimitives) -> None:
    resource = payload.get("resource") or {}
    p.write_status("Opened resource")
    p.emit_field("target", resource.get("target"), indent=0)
    opener = payload.get("opener") or []
    if opener:
        p.emit_field("opener", " ".join(str(part) for part in opener), indent=0)


def emit_detach_resource(payload: Mapping[str, Any], *, p: NoteOutputPrimitives) -> None:
    resource = payload.get("resource") or {}
    p.write_status(f"Detached resource from {payload.get('note_kind')} note", color="warning")
    p.emit_field("path", payload.get("path"), indent=0)
    p.emit_field("id", resource.get("id"), indent=0)
    p.emit_field("target", resource.get("target"), indent=0)
