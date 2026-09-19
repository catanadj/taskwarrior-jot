"""Human-readable rendering for timelog commands."""

from __future__ import annotations

import csv
import sys
from typing import Any, Mapping

from .output_notes import NoteOutputPrimitives


def emit_timelog(command: str, payload: Mapping[str, Any], *, p: NoteOutputPrimitives) -> None:
    if command == "timelog-ingest":
        _ingest(payload, p=p)
    elif command == "timelog-start":
        if payload.get("already_started"):
            p.write_status(f"Jot timelog session already pending for task {payload.get('task_short_uuid')}", color="warning")
        else:
            p.write_status(f"Started Jot timelog session for task {payload.get('task_short_uuid')}")
        p.emit_field("started", payload.get("started"), indent=0)
        _timewarrior(payload, p=p)
    elif command == "timelog-stop":
        _ingest(payload, p=p)
        if payload.get("session_cleared"):
            p.write_status("Pending session cleared")
    elif command == "timelog-stop-all":
        p.write_status(f"Stopped {payload.get('count', 0)} pending timelog sessions")
        errors = payload.get("errors") or []
        if errors:
            p.write_section_title(f"Errors: {len(errors)}", color="error")
            for item in errors:
                sys.stdout.write(f"  {item.get('task_uuid')}: {item.get('error')}\n")
        for item in payload.get("items") or []:
            status = "written" if item.get("written") else str(item.get("reason") or "skipped")
            sys.stdout.write(f"  {p.style(str(item.get('task_short_uuid') or ''), color='identity', bold=True)}  {item.get('duration_minutes')}m  {p.style(status, color='success' if item.get('written') else 'warning')}\n")
    elif command == "timelog-pending":
        p.write_title("Pending timelog sessions", blank_after=True)
        sessions = payload.get("sessions") or []
        if not sessions:
            sys.stdout.write("(none)\n")
        for item in sessions:
            sys.stdout.write(f"{p.style(str(item.get('task_short_uuid') or ''), color='identity', bold=True)}  started {p.style(str(item.get('started') or ''), color='muted')}\n")
    elif command == "timelog-cancel":
        p.write_status(f"Cancelled Jot timelog session for task {payload.get('task_short_uuid')}", color="warning")
        p.emit_field("started", payload.get("started"), indent=0)
    elif command == "timelog-add":
        p.write_status(f"Added time log {payload.get('timelog_key')} for task {payload.get('task_short_uuid')}")
        p.emit_field("duration", f"{payload.get('duration_minutes')} minutes", indent=0)
        p.emit_field("path", payload.get("path"), indent=0)
    elif command == "timelog-amend":
        p.write_status(f"Amended time log {payload.get('timelog_key')}")
        p.emit_field("new key", payload.get("new_timelog_key"), indent=0)
        p.emit_field("duration", f"{payload.get('duration_minutes')} minutes", indent=0)
        p.emit_field("archive", payload.get("archive_path"), indent=0)
    elif command == "timelog-delete":
        p.write_status(f"Deleted time log {payload.get('timelog_key')}", color="warning")
        p.emit_field("archive", payload.get("archive_path"), indent=0)
    elif command == "timelog-trash":
        p.write_title("Deleted time logs", blank_after=True)
        for item in payload.get("items") or []:
            sys.stdout.write(f"  #{item.get('id')}  {item.get('key')}  {item.get('duration')}  {item.get('task_short_uuid') or item.get('chain_id') or ''}\n")
    elif command == "timelog-restore":
        p.write_status(f"Restored time log {payload.get('timelog_key')}")
        p.emit_field("path", payload.get("path"), indent=0)
    elif command == "timelog-report-csv":
        fields = ("key", "task_uuid", "task_short_uuid", "chain_id", "project", "started", "stopped", "report_started", "report_stopped", "minutes", "duration", "note_kind", "path")
        writer = csv.DictWriter(sys.stdout, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for item in payload.get("entries") or []:
            if isinstance(item, dict):
                writer.writerow(item)
    elif command == "timelog-report":
        p.write_title(f"Timelog report: {payload.get('period') or 'all'}", blank_after=True)
        sys.stdout.write(f"Total: {payload.get('total') or '0m'} across {payload.get('entry_count', 0)} entries\n")
        for title, key in (("By day", "by_day"), ("By project", "by_project"), ("By chain", "by_chain"), ("By task", "by_task")):
            sys.stdout.write("\n")
            p.write_section_title(title)
            items = payload.get(key) or []
            if not items:
                sys.stdout.write("  (none)\n")
            for item in items:
                sys.stdout.write(f"  {item.get('name') or '(unknown)'}  {item.get('duration') or ''}  {item.get('entry_count', 0)} entries\n")
        if payload.get("details"):
            sys.stdout.write("\n")
            p.write_section_title("Details")
            for item in payload.get("entries") or []:
                sys.stdout.write(f"  {item.get('day') or ''}  {item.get('duration') or ''}  {item.get('display_range') or ''}\n")


def _ingest(payload: Mapping[str, Any], *, p: NoteOutputPrimitives) -> None:
    if not payload.get("written"):
        p.write_status(f"Time log skipped: {payload.get('reason') or 'no entry'}", color="warning")
        return
    p.write_status(f"Time log written to {payload.get('note_kind')} note: {payload.get('path')}")
    p.emit_field("task", payload.get("task_short_uuid"), indent=0)
    p.emit_field("duration", f"{payload.get('duration_minutes')} minutes", indent=0)


def _timewarrior(payload: Mapping[str, Any], *, p: NoteOutputPrimitives) -> None:
    timewarrior = payload.get("timewarrior")
    if not isinstance(timewarrior, dict) or not timewarrior.get("enabled"):
        return
    tags = ", ".join(str(tag) for tag in timewarrior.get("tags") or [])
    if timewarrior.get("started"):
        p.write_status(f"Timewarrior started: {tags}")
    elif timewarrior.get("error"):
        p.write_status(f"Timewarrior unchanged: {timewarrior['error']}", color="warning")
