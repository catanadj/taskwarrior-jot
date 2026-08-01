from __future__ import annotations

import csv
import json
import os
import shutil
import sys
from decimal import Decimal, InvalidOperation
from typing import Any

from .models import CommandResult, DoctorCheck


_COLOR_MODE = "auto"


def configure_output(*, color_mode: str) -> None:
    global _COLOR_MODE
    _COLOR_MODE = str(color_mode or "auto").strip().casefold()


def style_text(
    text: str,
    *,
    role: str = "",
    bold: bool = False,
    stream: Any = None,
) -> str:
    return _style(text, color=role, bold=bold, stream=stream)


def emit_result(result: CommandResult, *, json_mode: bool = False) -> None:
    if json_mode:
        sys.stdout.write(json.dumps(result.payload, ensure_ascii=False, indent=2) + "\n")
        return

    command = result.command
    payload = result.payload
    if command == "doctor":
        _emit_doctor(payload)
        return
    if command == "migrate":
        _emit_migrate(payload)
        return
    if command == "paths":
        _emit_paths(payload)
        return
    if command == "rebuild-index":
        _emit_rebuild_index(payload)
        return
    if command == "stats":
        _emit_stats(payload)
        return
    if command == "project-list":
        _emit_project_list(payload)
        return
    if command == "notes":
        _emit_notes(payload)
        return
    if command == "trash-list":
        _emit_trash_list(payload)
        return
    if command == "trash-restore":
        _emit_trash_restore(payload)
        return
    if command == "report-recent":
        _emit_report_recent(payload)
        return
    if command in {"note", "chain", "project"}:
        _emit_note_like(command, payload)
        return
    if command in {"task-delete", "chain-delete", "project-delete"}:
        _emit_delete(command, payload)
        return
    if command == "project-show":
        _emit_project_show(payload)
        return
    if command == "project-report":
        _emit_project_report(payload)
        return
    if command in {"project-cat", "task-cat", "chain-cat", "cat"}:
        _emit_cat(payload)
        return
    if command == "add":
        _emit_add(payload)
        return
    if command == "add-to":
        _emit_add_to(payload)
        return
    if command == "timelog-ingest":
        _emit_timelog_ingest(payload)
        return
    if command == "timelog-start":
        _emit_timelog_start(payload)
        return
    if command == "timelog-stop":
        _emit_timelog_stop(payload)
        return
    if command == "timelog-stop-all":
        _emit_timelog_stop_all(payload)
        return
    if command == "timelog-pending":
        _emit_timelog_pending(payload)
        return
    if command == "timelog-cancel":
        _emit_timelog_cancel(payload)
        return
    if command == "timelog-add":
        _emit_timelog_add(payload)
        return
    if command == "timelog-amend":
        _emit_timelog_amend(payload)
        return
    if command == "timelog-delete":
        _emit_timelog_delete(payload)
        return
    if command == "timelog-trash":
        _emit_timelog_trash(payload)
        return
    if command == "timelog-restore":
        _emit_timelog_restore(payload)
        return
    if command == "timelog-report":
        _emit_timelog_report(payload)
        return
    if command == "timelog-report-csv":
        _emit_timelog_report_csv(payload)
        return
    if command == "timew":
        _emit_timewarrior(payload)
        return
    if command == "headings":
        _emit_headings(payload)
        return
    if command == "section":
        _emit_section(payload)
        return
    if command == "resources":
        _emit_resources(payload)
        return
    if command == "attach":
        _emit_attach(payload)
        return
    if command == "open-resource":
        _emit_open_resource(payload)
        return
    if command == "detach-resource":
        _emit_detach_resource(payload)
        return
    if command == "progress":
        _emit_progress(payload)
        return
    if command in {"note-append", "chain-append", "project-append"}:
        _emit_append_like(command, payload)
        return
    if command == "list":
        _emit_list(payload)
        return
    if command == "show":
        _emit_show(payload)
        return
    if command == "export":
        _emit_export(payload)
        return
    if command == "search":
        _emit_search(payload)
        return
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _emit_doctor(payload: dict[str, Any]) -> None:
    repairs = payload.get("repairs") or []
    if repairs:
        _write_title("Repairs")
        for item in repairs:
            action = str(item.get("action") or "repair")
            detail = str(item.get("detail") or "")
            sys.stdout.write(f"  {_style(action, color='identity', bold=True)}: {detail}\n")
        sys.stdout.write("\n")
        _write_title("Checks")
    checks = payload.get("checks") or []
    for item in checks:
        if item.get("ok"):
            label = "OK"
        elif str(item.get("severity") or "error") == "warning":
            label = "WARN"
        else:
            label = "FAIL"
        name = str(item.get("name") or "check")
        detail = str(item.get("detail") or "")
        color = "success" if item.get("ok") else (
            "warning" if label == "WARN" else "error"
        )
        status = _style(f"[{label}]", color=color, bold=True)
        sys.stdout.write(f"{status} {_style(name, color='label', bold=True)}: {detail}\n")


def _emit_migrate(payload: dict[str, Any]) -> None:
    mode = "Migration plan" if payload.get("dry_run") else "Migration"
    _write_title(mode, blank_after=True)
    _emit_field("schema", payload.get("schema_version"), indent=0)
    _emit_field("notes", payload.get("total"), indent=0)
    _emit_field("planned", payload.get("planned"), indent=0)
    _emit_field("migrated", payload.get("migrated"), indent=0)
    _emit_field("blocked", payload.get("blocked"), indent=0)
    if payload.get("backup_path"):
        _emit_field("backup", payload.get("backup_path"), indent=0)
    blocked = [
        item
        for item in payload.get("items") or []
        if item.get("status") in {"future", "invalid"}
    ]
    if blocked:
        sys.stdout.write("\n")
        _write_section_title("Blocked notes:", color="error")
        for item in blocked:
            errors = "; ".join(str(value) for value in item.get("errors") or [])
            sys.stdout.write(f"  {item.get('path')}: {errors}\n")


def _emit_paths(payload: dict[str, Any]) -> None:
    _write_title("Paths", blank_after=True)
    for key in (
        "config_path",
        "root_dir",
        "trash_dir",
        "tasks_dir",
        "chains_dir",
        "projects_dir",
        "templates_dir",
        "index_path",
        "ops_path",
    ):
        _emit_field(key, payload.get(key), indent=0)


def _emit_rebuild_index(payload: dict[str, Any]) -> None:
    _write_title("Index rebuilt", blank_after=True)
    _emit_field("index", payload.get("index_path"), indent=0)
    _emit_field("updated", payload.get("updated"), indent=0)
    sys.stdout.write("\n")
    _write_section_title("Counts:")
    counts = payload.get("counts") or {}
    for key in ("tasks", "chains", "projects"):
        _emit_field(key, counts.get(key), indent=2)


def _emit_stats(payload: dict[str, Any]) -> None:
    notes = payload.get("notes") or {}
    ops = payload.get("ops") or {}
    index = payload.get("index") or {}

    _write_title("Stats", blank_after=True)
    _write_section_title("Notes:")
    for key in ("tasks", "chains", "projects"):
        _emit_field(key, notes.get(key), indent=2)

    sys.stdout.write("\n")
    _write_section_title("Ops:")
    _emit_field("path", ops.get("path"), indent=2)
    _emit_field("entries", ops.get("entries"), indent=2)
    _emit_field("event_add", ops.get("event_add"), indent=2)
    _emit_field("latest", ops.get("latest"), indent=2)

    sys.stdout.write("\n")
    _write_section_title("Index:")
    _emit_field("path", index.get("path"), indent=2)
    _emit_field("exists", "yes" if index.get("exists") else "no", indent=2)
    _emit_field("valid", "yes" if index.get("valid") else "no", indent=2)
    _emit_field("stale", "yes" if index.get("stale") else "no", indent=2)
    _emit_field("updated", index.get("updated"), indent=2)
    counts = index.get("counts") or {}
    _write_section_title("counts:", indent=2)
    for key in ("tasks", "chains", "projects"):
        _emit_field(key, counts.get(key), indent=4)


def _emit_project_list(payload: dict[str, Any]) -> None:
    items = payload.get("projects") or []
    _write_title("Projects", blank_after=True)
    if not items:
        sys.stdout.write("(none)\n")
        return
    for item in items:
        project = str(item.get("project") or "")
        updated = str(item.get("updated") or "").strip() or "unknown"
        path = str(item.get("path") or "")
        sys.stdout.write(f"{_style(project, color='identity', bold=True)}\n")
        _emit_field("updated", updated, indent=2)
        _emit_field("path", path, indent=2)
        sys.stdout.write("\n")


def _emit_notes(payload: dict[str, Any]) -> None:
    items = payload.get("notes") or []
    _write_title("Notes", blank_after=True)
    if not items:
        sys.stdout.write("(none)\n")
        return
    for item in items:
        kind = str(item.get("kind") or "note")
        ident = str(item.get("id") or "").strip()
        title = str(item.get("title") or "").strip()
        updated = str(item.get("updated") or "").strip() or "unknown"
        path = str(item.get("path") or "")
        heading = f"{kind}"
        if ident:
            heading += f" {ident}"
        if title and title != ident:
            heading += f"  {title}"
        sys.stdout.write(f"{_style(heading, color='identity', bold=True)}\n")
        project = str(item.get("project") or "").strip()
        chain_id = str(item.get("chain_id") or "").strip()
        if project:
            _emit_field("project", project, indent=2)
        if chain_id:
            _emit_field("chain", chain_id, indent=2)
        _emit_field("updated", updated, indent=2)
        _emit_field("path", path, indent=2)
        preview = str(item.get("preview") or "").strip()
        if preview:
            _emit_field("preview", preview, indent=2)
        sys.stdout.write("\n")


def _emit_trash_list(payload: dict[str, Any]) -> None:
    items = payload.get("items") or []
    _write_title("Trash", blank_after=True)
    if not items:
        sys.stdout.write("(empty)\n")
        return
    for item in items:
        ident = (
            str(item.get("task_short_uuid") or "").strip()
            or str(item.get("chain_id") or "").strip()
            or str(item.get("project") or "").strip()
        )
        item_id = _style(str(item.get("id") or ""), color="identity", bold=True)
        sys.stdout.write(f"{item_id}. {item.get('kind')} {ident}  {item.get('deleted_at') or ''}\n")
        _emit_field("from", item.get("path"), indent=2)
        _emit_field("trash", item.get("trash_path"), indent=2)
        sys.stdout.write("\n")


def _emit_trash_restore(payload: dict[str, Any]) -> None:
    _write_status("Restored note from trash")
    _emit_field("kind", payload.get("kind"), indent=0)
    _emit_field("to", payload.get("path"), indent=0)
    _emit_field("from", payload.get("trash_path"), indent=0)


def _emit_report_recent(payload: dict[str, Any]) -> None:
    items = payload.get("items") or []
    limit = payload.get("limit")
    kinds = payload.get("kinds") or []
    _write_title(f"Recent (limit={limit})")
    if kinds:
        _write_inline_field("Kinds", ", ".join(kinds))
    sys.stdout.write("\n")
    if not items:
        sys.stdout.write("(none)\n")
        return
    for item in items:
        ts = str(item.get("ts") or "unknown")
        kind = str(item.get("kind") or "item")
        ident = _recent_identity(item)
        summary = _recent_summary(item)
        sys.stdout.write(f"{_style(ts, color='muted')}  {_style(kind, color='label')}")
        if ident:
            sys.stdout.write(f"  {_style(ident, color='identity', bold=True)}")
        if summary:
            sys.stdout.write(f"  {summary}")
        sys.stdout.write("\n")


def _emit_note_like(command: str, payload: dict[str, Any]) -> None:
    action = "Opened" if payload.get("opened") else "Created"
    kind = {
        "note": "task note",
        "chain": "chain note",
        "project": "project note",
    }[command]
    _write_status(f"{action} {kind}: {payload['path']}")
    post_save_action = payload.get("post_save_action") or {}
    if post_save_action.get("action") == "complete-task":
        _write_status(f"Completed task: {post_save_action.get('task_short_uuid')}")


def _emit_append_like(command: str, payload: dict[str, Any]) -> None:
    created = not payload.get("opened")
    kind = {
        "note-append": "task note",
        "chain-append": "chain note",
        "project-append": "project note",
    }[command]
    prefix = "Created and appended to" if created else "Appended to"
    _write_status(f"{prefix} {kind}: {payload['path']}")


def _emit_delete(command: str, payload: dict[str, Any]) -> None:
    kind = {
        "task-delete": "task note",
        "chain-delete": "chain note",
        "project-delete": "project note",
    }[command]
    original = str(payload.get("path") or "")
    trash = str(payload.get("trash_path") or "")
    _write_status(f"Moved {kind} to trash", color="warning")
    _emit_field("from", original, indent=0)
    _emit_field("to", trash, indent=0)


def _emit_project_show(payload: dict[str, Any]) -> None:
    _write_title(f"Project {payload['project']}", blank_after=True)
    note = payload.get("note") or {}
    exists = bool(note.get("exists"))
    path = note.get("path")
    _write_section_title("Note:")
    if not exists:
        if path:
            _emit_field("exists", "no", indent=2)
            _emit_field("expected", path, indent=2)
        return
    _emit_field("path", path, indent=2)
    created = note.get("created")
    updated = note.get("updated")
    if created:
        _emit_field("created", created, indent=2)
    if updated:
        _emit_field("updated", updated, indent=2)
    preview = str(note.get("preview") or "").strip()
    if preview:
        _emit_field("preview", preview, indent=2)


def _emit_project_report(payload: dict[str, Any]) -> None:
    _write_title(f"Project {payload.get('project')}", blank_after=True)
    note = payload.get("note") or {}
    _write_section_title("Project note:")
    if not note.get("exists"):
        sys.stdout.write("  (none)\n")
    else:
        _emit_field("path", note.get("path"), indent=2)
        _emit_field("updated", note.get("updated"), indent=2)
        preview = str(note.get("preview") or "").strip()
        if preview:
            _emit_field("preview", preview, indent=2)
        headings = note.get("headings") or []
        if headings:
            _emit_field("headings", ", ".join(str(item) for item in headings), indent=2)

    sys.stdout.write("\n")
    _write_section_title("Tasks:")
    tasks = payload.get("tasks") or []
    if not tasks:
        sys.stdout.write("  (none)\n")
    for task in tasks:
        notes = task.get("notes") or {}
        note_labels = [name for name in ("task", "chain", "project") if notes.get(name)]
        line = f"  {task.get('short_uuid')}  {task.get('description') or ''}"
        due = task.get("due")
        if due:
            line += f"  due: {due}"
        if note_labels:
            line += f"  notes: {','.join(note_labels)}"
        sys.stdout.write(line + "\n")

    sys.stdout.write("\n")
    _write_section_title("Recent:")
    recent = payload.get("recent") or []
    if not recent:
        sys.stdout.write("  (none)\n")
    for item in recent:
        summary = _recent_summary(item)
        ident = _recent_identity(item)
        line = f"  {item.get('ts')}  {item.get('kind')}"
        if ident:
            line += f"  {ident}"
        if summary:
            line += f"  {summary}"
        sys.stdout.write(line + "\n")

    sys.stdout.write("\n")
    _write_section_title("Chains:")
    chains = payload.get("chains") or []
    if not chains:
        sys.stdout.write("  (none)\n")
    for chain in chains:
        note = "yes" if chain.get("note") else "no"
        line = f"  {chain.get('chain_id')}  tasks: {chain.get('task_count')}  note: {note}"
        if chain.get("updated"):
            line += f"  updated: {chain.get('updated')}"
        sys.stdout.write(line + "\n")

    timelog = payload.get("timelog") or {}
    sys.stdout.write("\n")
    _write_section_title(f"Time ({timelog.get('period') or 'week'}):")
    sys.stdout.write(
        f"  {timelog.get('total') or '0m'} across {timelog.get('entry_count', 0)} entries\n"
    )


def _emit_cat(payload: dict[str, Any]) -> None:
    sys.stdout.write(str(payload.get("content") or ""))


def _emit_add(payload: dict[str, Any]) -> None:
    _write_status(
        f"Added event to task {payload['task_short_uuid']}: {payload['annotation']}"
    )


def _emit_add_to(payload: dict[str, Any]) -> None:
    kind = str(payload.get("note_kind") or "note")
    heading = str(payload.get("heading") or "")
    match = str(payload.get("heading_match") or "unknown")
    path = str(payload.get("path") or "")
    entry = str(payload.get("entry") or "")
    if kind == "project":
        identity = str(payload.get("project") or "")
    else:
        identity = str(payload.get("task_short_uuid") or "")
    _write_status(f"Added entry to {kind} note {identity}")
    _emit_field("heading", heading, indent=0)
    _emit_field("match", match, indent=0)
    _emit_field("path", path, indent=0)
    _emit_field("entry", entry, indent=0)


def _emit_timelog_ingest(payload: dict[str, Any]) -> None:
    if not payload.get("written"):
        _write_status(
            f"Time log skipped: {payload.get('reason') or 'no entry'}",
            color="warning",
        )
        return
    _write_status(
        f"Time log written to {payload.get('note_kind')} note: {payload.get('path')}"
    )
    _emit_field("task", payload.get("task_short_uuid"), indent=0)
    chain_id = str(payload.get("chain_id") or "").strip()
    if chain_id:
        _emit_field("chain", chain_id, indent=0)
    _emit_field("duration", f"{payload.get('duration_minutes')} minutes", indent=0)


def _emit_timelog_start(payload: dict[str, Any]) -> None:
    if payload.get("already_started"):
        _write_status(
            f"Jot timelog session already pending for task {payload.get('task_short_uuid')}",
            color="warning",
        )
    else:
        _write_status(
            f"Started Jot timelog session for task {payload.get('task_short_uuid')}"
        )
    _emit_field("started", payload.get("started"), indent=0)
    chain_id = str(payload.get("chain_id") or "").strip()
    if chain_id:
        _emit_field("chain", chain_id, indent=0)
    timewarrior = payload.get("timewarrior")
    if not isinstance(timewarrior, dict) or not timewarrior.get("enabled"):
        return
    if timewarrior.get("reason") == "already-started":
        return
    tags = ", ".join(str(tag) for tag in timewarrior.get("tags") or [])
    if timewarrior.get("started"):
        _write_status(f"Timewarrior started: {tags}")
    elif timewarrior.get("error"):
        _write_status(f"Timewarrior unchanged: {timewarrior['error']}", color="warning")
    elif timewarrior.get("reason") == "explicitly-disabled":
        _write_status("Timewarrior unchanged: tag inheritance is disabled for this task")
    else:
        _write_status("Timewarrior unchanged: no tags are configured")


def _emit_timelog_stop(payload: dict[str, Any]) -> None:
    _emit_timelog_ingest(payload)
    if payload.get("session_cleared"):
        _write_status("Pending session cleared")


def _emit_timelog_stop_all(payload: dict[str, Any]) -> None:
    _write_status(f"Stopped {payload.get('count', 0)} pending timelog sessions")
    errors = payload.get("errors") or []
    if errors:
        _write_section_title(f"Errors: {len(errors)}", color="error")
        for item in errors:
            sys.stdout.write(
                f"  {_style(str(item.get('task_uuid') or ''), color='identity')}: "
                f"{_style(str(item.get('error') or ''), color='error')}\n"
            )
    items = payload.get("items") or []
    for item in items:
        status = "written" if item.get("written") else str(item.get("reason") or "skipped")
        status_color = "success" if item.get("written") else "warning"
        identity = _style(str(item.get("task_short_uuid") or ""), color="identity", bold=True)
        sys.stdout.write(
            f"  {identity}  {item.get('duration_minutes')}m  "
            f"{_style(status, color=status_color)}\n"
        )


def _emit_timewarrior(payload: dict[str, Any]) -> None:
    operation = str(payload.get("operation") or "show")
    if operation == "show":
        _write_title("Timewarrior tags", blank_after=True)
        _emit_field("task", payload.get("task_short_uuid"), indent=0)
        if payload.get("chain_id"):
            _emit_field("chain", payload.get("chain_id"), indent=0)
        if payload.get("project"):
            _emit_field("project", payload.get("project"), indent=0)
        _emit_field("integration", "enabled" if payload.get("enabled") else "disabled", indent=0)
        tags = payload.get("tags") or []
        _emit_field("tags", ", ".join(str(tag) for tag in tags) if tags else "(none)", indent=0)
        source = payload.get("source")
        if isinstance(source, dict):
            _emit_field("source", f"{source.get('scope')} {source.get('reference')}", indent=0)
            _emit_field("path", source.get("path"), indent=0)
            if payload.get("explicitly_disabled"):
                _emit_field("inheritance", "disabled by explicit empty tag list", indent=0)
        else:
            _emit_field("source", "(none)", indent=0)
        return

    scope = str(payload.get("scope") or "note")
    reference = str(payload.get("reference") or "")
    changed = bool(payload.get("changed"))
    if operation == "set":
        tags = ", ".join(str(tag) for tag in payload.get("tags") or [])
        message = f"Set Timewarrior tags on {scope} {reference}: {tags}"
    elif operation == "clear":
        message = f"Disabled inherited Timewarrior tags on {scope} {reference}"
    else:
        message = f"Restored Timewarrior tag inheritance on {scope} {reference}"
    if not changed:
        message = f"No change: {message[0].lower()}{message[1:]}"
    _write_status(message)
    if payload.get("path"):
        _emit_field("path", payload.get("path"), indent=0)


def _emit_timelog_pending(payload: dict[str, Any]) -> None:
    sessions = payload.get("sessions") or []
    _write_title("Pending timelog sessions", blank_after=True)
    if not sessions:
        sys.stdout.write("(none)\n")
        return
    for item in sessions:
        elapsed = str(item.get("elapsed") or "").strip()
        suffix = f"  elapsed {elapsed}" if elapsed else ""
        identity = _style(str(item.get("task_short_uuid") or ""), color="identity", bold=True)
        started = _style(str(item.get("started") or ""), color="muted")
        sys.stdout.write(f"{identity}  started {started}{suffix}\n")
        description = str(item.get("description") or "").strip()
        if description:
            _emit_field("description", description, indent=2)
        project = str(item.get("project") or "").strip()
        if project:
            _emit_field("project", project, indent=2)
        chain_id = str(item.get("chain_id") or "").strip()
        if chain_id:
            _emit_field("chain", chain_id, indent=2)


def _emit_timelog_cancel(payload: dict[str, Any]) -> None:
    _write_status(
        f"Cancelled Jot timelog session for task {payload.get('task_short_uuid')}",
        color="warning",
    )
    _emit_field("started", payload.get("started"), indent=0)


def _emit_timelog_add(payload: dict[str, Any]) -> None:
    _write_status(
        f"Added time log {payload.get('timelog_key')} for task {payload.get('task_short_uuid')}"
    )
    _emit_field("duration", f"{payload.get('duration_minutes')} minutes", indent=0)
    _emit_field("path", payload.get("path"), indent=0)


def _emit_timelog_amend(payload: dict[str, Any]) -> None:
    _write_status(f"Amended time log {payload.get('timelog_key')}")
    _emit_field("new key", payload.get("new_timelog_key"), indent=0)
    _emit_field("duration", f"{payload.get('duration_minutes')} minutes", indent=0)
    _emit_field("archive", payload.get("archive_path"), indent=0)


def _emit_timelog_delete(payload: dict[str, Any]) -> None:
    _write_status(f"Deleted time log {payload.get('timelog_key')}", color="warning")
    _emit_field("archive", payload.get("archive_path"), indent=0)


def _emit_timelog_trash(payload: dict[str, Any]) -> None:
    items = payload.get("items") or []
    if not items:
        _write_status("No deleted time logs available for restoration.", color="muted")
        return
    _write_title("Deleted time logs", blank_after=True)
    for item in items:
        identity = str(item.get("chain_id") or item.get("task_short_uuid") or "")
        project = str(item.get("project") or "").strip()
        suffix = f"  {project}" if project else ""
        item_id = _style(f"#{item.get('id')}", color="identity", bold=True)
        key = _style(str(item.get("key") or ""), color="muted")
        sys.stdout.write(f"  {item_id}  {key}  {item.get('duration')}  {identity}{suffix}\n")
        _emit_field("archived", item.get("archived_at"), indent=4)


def _emit_timelog_restore(payload: dict[str, Any]) -> None:
    _write_status(f"Restored time log {payload.get('timelog_key')}")
    _emit_field("path", payload.get("path"), indent=0)


def _emit_timelog_report(payload: dict[str, Any]) -> None:
    period = str(payload.get("period") or "all")
    _write_title(f"Timelog report: {period}", blank_after=True)
    label = _style("Total", color="label", bold=True)
    total = _style(str(payload.get("total") or "0m"), color="success", bold=True)
    sys.stdout.write(f"{label}: {total} across {payload.get('entry_count', 0)} entries\n")
    filters = payload.get("filters") if isinstance(payload.get("filters"), dict) else {}
    active_filters = [f"{key}={value}" for key, value in filters.items() if value]
    if active_filters:
        _write_inline_field("Filters", ", ".join(active_filters))
    _emit_time_log_group("By day", payload.get("by_day") or [])
    _emit_time_log_group("By project", payload.get("by_project") or [])
    _emit_time_log_group("By chain", payload.get("by_chain") or [])
    _emit_time_log_group("By task", payload.get("by_task") or [])
    if payload.get("details"):
        _emit_time_log_details(payload.get("entries") or [])


def _emit_timelog_report_csv(payload: dict[str, Any]) -> None:
    fields = (
        "key",
        "task_uuid",
        "task_short_uuid",
        "chain_id",
        "project",
        "started",
        "stopped",
        "report_started",
        "report_stopped",
        "minutes",
        "duration",
        "note_kind",
        "path",
    )
    writer = csv.DictWriter(sys.stdout, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for item in payload.get("entries") or []:
        if isinstance(item, dict):
            writer.writerow(item)


def _emit_time_log_group(title: str, items: list[object]) -> None:
    sys.stdout.write("\n")
    _write_section_title(title)
    if not items:
        sys.stdout.write("  (none)\n")
        return
    for raw in items:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "(unknown)")
        duration = str(raw.get("duration") or "")
        count = raw.get("entry_count", 0)
        styled_name = _style(f"{name:<24}", color="identity")
        styled_duration = _style(f"{duration:>8}", color="success", bold=True)
        sys.stdout.write(f"  {styled_name} {styled_duration}  {count} entries\n")


def _emit_time_log_details(items: list[object]) -> None:
    sys.stdout.write("\n")
    _write_section_title("Details")
    if not items:
        sys.stdout.write("  (none)\n")
        return
    for raw in items:
        if not isinstance(raw, dict):
            continue
        duration = str(raw.get("duration") or "")
        timerange = str(raw.get("display_range") or "")
        project = str(raw.get("project") or "").strip() or "(no project)"
        task = str(raw.get("task_short_uuid") or "").strip()
        chain = str(raw.get("chain_id") or "").strip()
        suffix = f"  task {task}" if task else ""
        if chain:
            suffix += f"  chain {chain}"
        key = str(raw.get("key") or "").strip()
        key_prefix = f"{_style(f'[{key}]', color='muted')}  " if key else ""
        day = _style(str(raw.get("day") or ""), color="muted")
        duration_text = _style(f"{duration:>8}", color="success", bold=True)
        project_text = _style(project, color="identity")
        sys.stdout.write(
            f"  {key_prefix}{day}  {duration_text}  {timerange}  {project_text}{suffix}\n"
        )


def _emit_headings(payload: dict[str, Any]) -> None:
    _write_title(f"Headings in {payload.get('note_kind')} note")
    _emit_field("path", payload.get("path"), indent=0)
    headings = payload.get("headings") or []
    if not headings:
        sys.stdout.write("\n(none)\n")
        return
    sys.stdout.write("\n")
    for item in headings:
        level = int(item.get("level") or 1)
        title = str(item.get("title") or "")
        line = item.get("line")
        sys.stdout.write(_style(f"{'#' * level} {title}", color="section", bold=True))
        if line:
            sys.stdout.write(f"  (line {line})")
        sys.stdout.write("\n")


def _emit_section(payload: dict[str, Any]) -> None:
    content = str(payload.get("content") or "").strip()
    if content:
        sys.stdout.write(content + "\n")


def _emit_resources(payload: dict[str, Any]) -> None:
    kind = str(payload.get("note_kind") or "note")
    _write_title(f"Resources in {kind} note")
    _emit_field("path", payload.get("path"), indent=0)
    resources = payload.get("resources") or []
    if not resources:
        sys.stdout.write("\n(none)\n")
        return
    sys.stdout.write("\n")
    for item in resources:
        label = str(item.get("label") or "").strip()
        target = str(item.get("target") or "").strip()
        kind = str(item.get("kind") or "resource")
        status = str(item.get("status") or "").strip()
        suffix = f"[{kind}]"
        if status and status != "unchecked":
            suffix += f" {status}"
        prefix = f"{item.get('id')}. "
        if label and label != target:
            sys.stdout.write(
                f"{_style(prefix + label, color='identity', bold=True)}  "
                f"{_style(suffix, color=_resource_status_color(status))}\n"
            )
            _emit_field("target", target, indent=3)
        else:
            sys.stdout.write(
                f"{_style(prefix + target, color='identity')}  "
                f"{_style(suffix, color=_resource_status_color(status))}\n"
            )


def _emit_attach(payload: dict[str, Any]) -> None:
    resource = payload.get("resource") or {}
    _write_status(f"Attached resource to {payload.get('note_kind')} note")
    _emit_field("path", payload.get("path"), indent=0)
    _emit_field("id", resource.get("id"), indent=0)
    _emit_field("label", resource.get("label"), indent=0)
    _emit_field("target", resource.get("target"), indent=0)


def _emit_open_resource(payload: dict[str, Any]) -> None:
    resource = payload.get("resource") or {}
    _write_status("Opened resource")
    _emit_field("target", resource.get("target"), indent=0)
    opener = payload.get("opener") or []
    if opener:
        _emit_field("opener", " ".join(str(part) for part in opener), indent=0)


def _emit_detach_resource(payload: dict[str, Any]) -> None:
    resource = payload.get("resource") or {}
    _write_status(
        f"Detached resource from {payload.get('note_kind')} note",
        color="warning",
    )
    _emit_field("path", payload.get("path"), indent=0)
    _emit_field("id", resource.get("id"), indent=0)
    _emit_field("target", resource.get("target"), indent=0)


def _emit_progress(payload: dict[str, Any]) -> None:
    items = payload.get("items")
    if isinstance(items, list):
        _emit_progress_items(payload, items)
        return
    progress = payload.get("progress")
    tracks = payload.get("tracks") or []
    kind = str(payload.get("note_kind") or "note")
    operation = str(payload.get("operation") or "show")
    _write_title(f"Progress for {kind} note")
    _emit_field("path", payload.get("path"), indent=0)
    _emit_field("operation", operation, indent=0)
    selected_track = str(payload.get("track") or "").strip()
    if operation == "show" and not selected_track and isinstance(tracks, list):
        if not tracks:
            sys.stdout.write("\n(not set)\n")
            return
        sys.stdout.write("\n")
        for item in tracks:
            if isinstance(item, dict):
                _emit_progress_track(item, visual=True)
        _emit_progress_analysis(payload)
        return
    if not isinstance(progress, dict):
        sys.stdout.write("\n(not set)\n")
        return
    _emit_progress_track(progress, visual=operation == "show")
    if operation == "show":
        _emit_progress_analysis(payload, track=selected_track or str(progress.get("track") or "default"))
    entry = str(payload.get("entry") or "").strip()
    if entry:
        _emit_field("history", entry, indent=0)


def _emit_progress_items(payload: dict[str, Any], items: list[object]) -> None:
    kind = str(payload.get("note_kind") or "note")
    selected_track = str(payload.get("track") or "").strip()
    _write_title(f"Progress for {len(items)} {kind} notes")
    for item in items:
        if not isinstance(item, dict):
            continue
        reference = str(item.get("reference") or "")
        identity = (
            item.get("chain_id")
            or item.get("task_short_uuid")
            or item.get("project")
            or reference
        )
        sys.stdout.write(f"\n{_style(str(identity), color='identity', bold=True)}")
        if reference and reference != str(identity):
            sys.stdout.write(f"  ({reference})")
        sys.stdout.write("\n")
        tracks = item.get("tracks") or []
        if selected_track:
            progress = item.get("progress")
            if isinstance(progress, dict):
                _emit_progress_track(progress, visual=True)
                _emit_progress_analysis(item, track=selected_track)
            else:
                sys.stdout.write(f"  track '{selected_track}' is not set\n")
            continue
        if not isinstance(tracks, list) or not tracks:
            sys.stdout.write("  (not set)\n")
            continue
        for progress in tracks:
            if isinstance(progress, dict):
                _emit_progress_track(progress, visual=True)
        _emit_progress_analysis(item)


def _emit_progress_track(progress: dict[str, Any], *, visual: bool = False) -> None:
    if visual:
        _emit_progress_visual(progress)
        return
    _emit_field("track", progress.get("track") or "default", indent=0)
    unit = str(progress.get("unit") or "").strip()
    measurement = f"{progress.get('current')}/{progress.get('target')}"
    if unit:
        measurement += f" {unit}"
    _emit_field("progress", measurement, indent=0)
    percentage = progress.get("percentage")
    if percentage is not None:
        _emit_field("percentage", f"{percentage}%", indent=0)
    status = str(progress.get("status") or "").strip()
    if status:
        _emit_field("status", status, indent=0)
    updated = progress.get("updated")
    if updated:
        _emit_field("updated", updated, indent=0)


def _emit_progress_visual(progress: dict[str, Any]) -> None:
    track = str(progress.get("track") or "default")
    unit = str(progress.get("unit") or "").strip()
    measurement = f"{progress.get('current')}/{progress.get('target')}"
    if unit:
        measurement += f" {unit}"
    percentage = progress.get("percentage")
    percentage_text = f"{percentage}%" if percentage is not None else "no percentage"
    status = str(progress.get("status") or "").strip()

    sys.stdout.write(f"  {_style(track, color='identity', bold=True)}\n")
    sys.stdout.write(f"  {_progress_bar(percentage)}  {_style(percentage_text, bold=True)}\n")
    sys.stdout.write(f"  {measurement}")
    if status:
        sys.stdout.write(f"  ·  {status}")
    sys.stdout.write("\n")
    updated = progress.get("updated")
    if updated:
        sys.stdout.write(f"  updated {updated}\n")
    sys.stdout.write("\n")


def _emit_progress_analysis(payload: dict[str, Any], *, track: str | None = None) -> None:
    trends = payload.get("trends") or []
    history = payload.get("history") or []
    selected_track = str(track or "").strip()
    if isinstance(trends, list):
        filtered = [
            item for item in trends
            if isinstance(item, dict)
            and (not selected_track or str(item.get("track") or "default").casefold() == selected_track.casefold())
        ]
        if filtered:
            _write_section_title("Trends", indent=2)
            for item in filtered:
                _emit_progress_trend(item)
    if isinstance(history, list) and history:
        filtered_history = [
            item for item in history
            if isinstance(item, dict)
            and (not selected_track or str(item.get("track") or "default").casefold() == selected_track.casefold())
        ]
        if filtered_history:
            _write_section_title("Recent history", indent=2)
            for item in filtered_history:
                _emit_progress_history_entry(item)
            sys.stdout.write("\n")


def _emit_progress_trend(trend: dict[str, Any]) -> None:
    track = str(trend.get("track") or "default")
    unit = str(trend.get("unit") or "").strip()
    delta = str(trend.get("delta") or "").strip()
    remaining = str(trend.get("remaining") or "").strip()
    average = str(trend.get("average_change") or "").strip()
    parts = [f"{track}: {trend.get('updates', 0)} updates"]
    if delta:
        parts.append(f"delta {delta}{(' ' + unit) if unit else ''}")
    if remaining:
        parts.append(f"remaining {remaining}{(' ' + unit) if unit else ''}")
    if average:
        parts.append(f"avg/update {average}{(' ' + unit) if unit else ''}")
    last_change = str(trend.get("last_change") or "").strip()
    if last_change:
        parts.append(f"last {last_change}{(' ' + unit) if unit else ''}")
    sys.stdout.write(f"    {' · '.join(parts)}\n")


def _emit_progress_history_entry(entry: dict[str, Any]) -> None:
    timestamp = str(entry.get("timestamp") or "").strip()
    track = str(entry.get("track") or "default")
    action = str(entry.get("action") or "unknown")
    summary = str(entry.get("summary") or "").strip()
    prefix = f"{timestamp}  {track}  {action}"
    if summary:
        sys.stdout.write(f"    {prefix}: {summary}\n")
    else:
        sys.stdout.write(f"    {prefix}\n")


def _progress_bar(percentage: object, width: int | None = None) -> str:
    if width is None:
        width = max(12, min(36, shutil.get_terminal_size(fallback=(80, 24)).columns - 24))
    try:
        value = Decimal(str(percentage))
    except (InvalidOperation, ValueError):
        value = Decimal("0")
    clamped = max(Decimal("0"), min(Decimal("100"), value))
    eighths = int((clamped / Decimal("100") * width * 8).quantize(Decimal("1")))
    full, remainder = divmod(eighths, 8)
    partials = " ▏▎▍▌▋▊▉"
    filled = "█" * full
    if remainder and full < width:
        filled += partials[remainder]
    empty = "░" * max(0, width - full - (1 if remainder else 0))
    bar = f"{filled}{empty}"
    return f"【{_style(bar, color=_progress_color(clamped))}】"


def _progress_color(percentage: Decimal) -> str:
    if percentage >= 100:
        return "green"
    if percentage >= 80:
        return "bright_green"
    if percentage >= 60:
        return "yellow_green"
    if percentage >= 40:
        return "yellow"
    if percentage >= 20:
        return "orange"
    return "red"


def _style(
    text: str,
    *,
    color: str = "",
    bold: bool = False,
    stream: Any = None,
) -> str:
    if not _use_color(stream=stream):
        return text
    codes = []
    if bold:
        codes.append("1")
    color_codes = {
        "red": "31",
        "orange": "38;5;208",
        "yellow": "33",
        "yellow_green": "38;5;154",
        "bright_green": "38;2;52;190;90",
        "green": "38;2;0;255;70",
        "title": "38;5;45",
        "section": "38;5;75",
        "label": "38;5;109",
        "identity": "38;5;220",
        "path": "38;5;117",
        "muted": "38;5;244",
        "success": "38;5;42",
        "warning": "38;5;214",
        "error": "38;5;196",
    }
    if color in color_codes:
        codes.append(color_codes[color])
    if not codes:
        return text
    return f"\033[{';'.join(codes)}m{text}\033[0m"


def _use_color(*, stream: Any = None) -> bool:
    if _COLOR_MODE == "never" or "NO_COLOR" in os.environ:
        return False
    if _COLOR_MODE == "always":
        return True
    output = stream if stream is not None else sys.stdout
    return bool(output.isatty())


def _write_title(text: str, *, blank_after: bool = False) -> None:
    suffix = "\n\n" if blank_after else "\n"
    sys.stdout.write(_style(text, color="title", bold=True) + suffix)


def _write_section_title(
    text: str,
    *,
    indent: int = 0,
    color: str = "section",
) -> None:
    sys.stdout.write(" " * indent + _style(text, color=color, bold=True) + "\n")


def _write_status(text: str, *, color: str = "success") -> None:
    sys.stdout.write(_style(text, color=color, bold=True) + "\n")


def _write_inline_field(label: str, value: Any) -> None:
    styled_label = _style(label, color="label", bold=True)
    sys.stdout.write(f"{styled_label}: {value}\n")


def _resource_status_color(status: str) -> str:
    normalized = str(status or "").strip().casefold()
    if normalized == "exists":
        return "success"
    if normalized in {"missing", "invalid"}:
        return "error"
    return "muted"


def _emit_list(payload: dict[str, Any]) -> None:
    _emit_show(payload)
    events = payload.get("events") or []
    sys.stdout.write("\n")
    _write_section_title("Events:")
    if not events:
        sys.stdout.write("  (none)\n")
        return
    for item in events:
        entry = item.get("entry") or "unknown"
        description = item.get("description") or ""
        sys.stdout.write(f"  {entry}  {description}\n")


def _emit_show(payload: dict[str, Any]) -> None:
    task = payload.get("task") or {}
    notes = payload.get("notes") or {}
    _write_title(f"Task {task.get('short_uuid')}")
    _emit_field("description", task.get("description"), indent=0)
    project = task.get("project")
    if project:
        _emit_field("project", project, indent=0)
    tags = task.get("tags") or []
    if tags:
        _emit_field("tags", ", ".join(tags), indent=0)
    sys.stdout.write("\n")
    _write_section_title("Notes:")
    _emit_note_ref("task", notes.get("task") or {})
    _emit_note_ref("chain", notes.get("chain") or {})
    _emit_note_ref("project", notes.get("project") or {})
    nautical = payload.get("nautical") or {}
    if nautical:
        sys.stdout.write("\n")
        _write_section_title("Nautical:")
        for key, value in sorted(nautical.items()):
            _emit_field(key, value, indent=2)


def _emit_export(payload: dict[str, Any]) -> None:
    _emit_show(payload)
    exported_at = payload.get("exported_at")
    if exported_at:
        sys.stdout.write("\n")
        _emit_field("exported", exported_at, indent=0)
        sys.stdout.write("\n")
    events = payload.get("events") or []
    _write_section_title("Events:")
    if not events:
        sys.stdout.write("  (none)\n")
        return
    for item in events:
        entry = item.get("entry") or "unknown"
        description = item.get("description") or ""
        sys.stdout.write(f"  {entry}  {description}\n")


def _emit_search(payload: dict[str, Any]) -> None:
    _write_inline_field("Query", payload.get("query"))
    kinds = payload.get("kinds") or []
    if kinds:
        _write_inline_field("Kinds", ", ".join(kinds))
    project = str(payload.get("project") or "").strip()
    if project:
        _write_inline_field("Project", project)
    chain_id = str(payload.get("chain_id") or "").strip()
    if chain_id:
        _write_inline_field("Chain", chain_id)
    note_hits = payload.get("notes") or []
    event_hits = payload.get("events") or []
    _write_section_title("Notes:")
    if not note_hits:
        sys.stdout.write("  (none)\n")
    else:
        for item in note_hits:
            kind = _style(f"[{item.get('kind')}]", color="identity", bold=True)
            path = _style(str(item.get("path") or ""), color="path")
            sys.stdout.write(f"  {kind} {path}\n")
            match = item.get("match") or ""
            if match:
                sys.stdout.write(f"    {match}\n")
    _write_section_title("Events:")
    if not event_hits:
        sys.stdout.write("  (none)\n")
        return
    for item in event_hits:
        identity = _style(
            f"[{item.get('task_short_uuid')}]",
            color="identity",
            bold=True,
        )
        timestamp = _style(f"({item.get('ts')})", color="muted")
        sys.stdout.write(f"  {identity} {item.get('annotation')} {timestamp}\n")


def warn(message: str) -> None:
    prefix = _style("[jot]", color="error", bold=True, stream=sys.stderr)
    sys.stderr.write(f"{prefix} {message}\n")


def _emit_note_ref(label: str, item: dict[str, Any]) -> None:
    available = bool(item.get("available"))
    exists = bool(item.get("exists"))
    path = item.get("path")
    if not available:
        _emit_field(label, "(n/a)", indent=2)
        return
    if exists:
        _emit_field(label, path, indent=2)
        return
    _emit_field(label, "(none)", indent=2)
    if path:
        _emit_field("expected", path, indent=4)


def _emit_field(label: str, value: Any, *, indent: int = 0, width: int = 11) -> None:
    pad = " " * indent
    text = "" if value is None else str(value)
    styled_label = _style(f"{label:<{width}}", color="label", bold=True)
    color = _field_value_color(label, text)
    styled_value = _style(text, color=color) if color else text
    sys.stdout.write(f"{pad}{styled_label}: {styled_value}\n")


def _field_value_color(label: str, value: str) -> str:
    normalized_label = str(label or "").strip().casefold()
    normalized_value = str(value or "").strip().casefold()
    if normalized_label in {
        "path",
        "from",
        "to",
        "trash",
        "target",
        "expected",
        "archive",
        "backup",
        "config_path",
        "root_dir",
        "trash_dir",
        "tasks_dir",
        "chains_dir",
        "projects_dir",
        "templates_dir",
        "index_path",
        "ops_path",
    }:
        return "path"
    if normalized_label in {
        "id",
        "task",
        "chain",
        "project",
        "key",
        "new key",
        "track",
    }:
        return "identity"
    if normalized_label in {
        "started",
        "stopped",
        "created",
        "updated",
        "latest",
        "exported",
        "archived",
    }:
        return "muted"
    if normalized_value in {"yes", "ok", "written", "active", "completed"}:
        return "success"
    if normalized_value in {"no", "none", "(none)", "(n/a)", "unknown"}:
        return "muted"
    return ""


def _recent_identity(item: dict[str, Any]) -> str:
    for key in ("task_short_uuid", "chain_id", "project"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return ""


def _recent_summary(item: dict[str, Any]) -> str:
    kind = str(item.get("kind") or "")
    if kind == "event":
        return str(item.get("annotation") or "").strip()
    description = str(item.get("description") or "").strip()
    if description:
        return description
    return str(item.get("path") or "").strip()
