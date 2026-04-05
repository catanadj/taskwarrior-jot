from __future__ import annotations

import json
import sys
from typing import Any

from .models import CommandResult, DoctorCheck


def emit_result(result: CommandResult, *, json_mode: bool = False) -> None:
    if json_mode:
        sys.stdout.write(json.dumps(result.payload, ensure_ascii=False, indent=2) + "\n")
        return

    command = result.command
    payload = result.payload
    if command == "doctor":
        _emit_doctor(payload.get("checks", []))
        return
    if command in {"note", "chain"}:
        _emit_note_like(command, payload)
        return
    if command == "add":
        _emit_add(payload)
        return
    if command in {"note-append", "chain-append"}:
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


def _emit_doctor(checks: list[dict[str, Any]]) -> None:
    for item in checks:
        label = "OK" if item.get("ok") else "FAIL"
        name = str(item.get("name") or "check")
        detail = str(item.get("detail") or "")
        sys.stdout.write(f"[{label}] {name}: {detail}\n")


def _emit_note_like(command: str, payload: dict[str, Any]) -> None:
    action = "Opened" if payload.get("opened") else "Created"
    kind = "task note" if command == "note" else "chain note"
    sys.stdout.write(f"{action} {kind}: {payload['path']}\n")


def _emit_append_like(command: str, payload: dict[str, Any]) -> None:
    created = not payload.get("opened")
    kind = "task note" if command == "note-append" else "chain note"
    prefix = "Created and appended to" if created else "Appended to"
    sys.stdout.write(f"{prefix} {kind}: {payload['path']}\n")


def _emit_add(payload: dict[str, Any]) -> None:
    sys.stdout.write(
        f"Added event to task {payload['task_short_uuid']}: {payload['annotation']}\n"
    )


def _emit_list(payload: dict[str, Any]) -> None:
    sys.stdout.write(f"Task {payload['task_short_uuid']}: {payload['description']}\n")
    task_note = payload.get("task_note") or "(none)"
    sys.stdout.write(f"Task note: {task_note}\n")
    chain_note = payload.get("chain_note")
    if chain_note:
        sys.stdout.write(f"Chain note: {chain_note}\n")
    events = payload.get("events") or []
    sys.stdout.write("Events:\n")
    if not events:
        sys.stdout.write("  (none)\n")
        return
    for item in events:
        entry = item.get("entry") or "unknown"
        description = item.get("description") or ""
        sys.stdout.write(f"  [{entry}] {description}\n")


def _emit_show(payload: dict[str, Any]) -> None:
    sys.stdout.write(f"Task {payload['task_short_uuid']}: {payload['description']}\n")
    task_note = payload.get("task_note") or "(none)"
    sys.stdout.write(f"Task note: {task_note}\n")
    chain_note = payload.get("chain_note")
    if chain_note:
        sys.stdout.write(f"Chain note: {chain_note}\n")
    nautical = payload.get("nautical") or {}
    if nautical:
        sys.stdout.write("Nautical:\n")
        for key, value in nautical.items():
            sys.stdout.write(f"  {key}: {value}\n")


def _emit_export(payload: dict[str, Any]) -> None:
    _emit_show(payload)
    events = payload.get("events") or []
    sys.stdout.write("Events:\n")
    if not events:
        sys.stdout.write("  (none)\n")
        return
    for item in events:
        entry = item.get("entry") or "unknown"
        description = item.get("description") or ""
        sys.stdout.write(f"  [{entry}] {description}\n")


def _emit_search(payload: dict[str, Any]) -> None:
    sys.stdout.write(f"Query: {payload.get('query')}\n")
    note_hits = payload.get("notes") or []
    event_hits = payload.get("events") or []
    sys.stdout.write("Notes:\n")
    if not note_hits:
        sys.stdout.write("  (none)\n")
    else:
        for item in note_hits:
            sys.stdout.write(f"  [{item.get('kind')}] {item.get('path')}\n")
            match = item.get("match") or ""
            if match:
                sys.stdout.write(f"    {match}\n")
    sys.stdout.write("Events:\n")
    if not event_hits:
        sys.stdout.write("  (none)\n")
        return
    for item in event_hits:
        sys.stdout.write(
            f"  [{item.get('task_short_uuid')}] {item.get('annotation')} ({item.get('ts')})\n"
        )


def warn(message: str) -> None:
    sys.stderr.write(f"[jot] {message}\n")
