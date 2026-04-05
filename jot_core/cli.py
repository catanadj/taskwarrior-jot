from __future__ import annotations

import argparse
import sys

from .app import build_app_context
from .config import ensure_app_dirs
from .doctor import run_doctor
from .editor import open_in_editor
from .events import collect_event_text, format_event_text, validate_event_type
from .models import CommandResult
from .nautical import nautical_summary
from .notes import (
    ensure_chain_note,
    ensure_task_note,
    find_chain_note,
    find_task_note,
)
from .output import emit_result, warn
from .search import search_all
from .storage import (
    append_chain_note_storage,
    append_task_note_storage,
    finalize_chain_note_edit,
    finalize_task_note_edit,
    record_event_add,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jot")
    parser.add_argument("--json", action="store_true", help="emit JSON output")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("doctor", help="check jot configuration and dependencies")

    for name in ("note", "chain", "show", "list", "export"):
        sub = subparsers.add_parser(name)
        sub.add_argument("task_ref", help="task id, full uuid, or short uuid")

    for name in ("note-append", "chain-append"):
        sub = subparsers.add_parser(name)
        sub.add_argument("task_ref", help="task id, full uuid, or short uuid")
        sub.add_argument("text", nargs="*", help="text to append")

    add = subparsers.add_parser("add")
    add.add_argument("--type", default="note", dest="event_type", help="event type label")
    add.add_argument("task_ref", help="task id, full uuid, or short uuid")
    add.add_argument("text", nargs="*", help="event text")

    search = subparsers.add_parser("search")
    search.add_argument("query", help="search notes and event log")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    ctx = build_app_context()
    ensure_app_dirs(ctx.config)

    try:
        if args.command == "doctor":
            result = run_doctor(ctx.config, ctx.taskwarrior)
        elif args.command == "note":
            result = _run_note(ctx, args.task_ref)
        elif args.command == "chain":
            result = _run_chain(ctx, args.task_ref)
        elif args.command == "add":
            result = _run_add(ctx, args.task_ref, args.text, args.event_type)
        elif args.command == "note-append":
            result = _run_note_append(ctx, args.task_ref, _text_from_args(args.text))
        elif args.command == "chain-append":
            result = _run_chain_append(ctx, args.task_ref, _text_from_args(args.text))
        elif args.command == "list":
            result = _run_list(ctx, args.task_ref)
        elif args.command == "show":
            result = _run_show(ctx, args.task_ref)
        elif args.command == "export":
            result = _run_export(ctx, args.task_ref)
        elif args.command == "search":
            result = _run_search(ctx, args.query)
        else:  # pragma: no cover
            parser.error(f"unknown command {args.command}")
            return 2
    except RuntimeError as exc:
        warn(str(exc))
        return 1

    emit_result(result, json_mode=args.json)
    return 0


def _run_note(ctx, task_ref: str) -> CommandResult:
    task = ctx.taskwarrior.resolve_task(task_ref)
    note = ensure_task_note(ctx.config, task)
    open_in_editor(note.note_path, ctx.config.editor_command)
    finalize_task_note_edit(ctx.config, task, note)
    return CommandResult(
        command="note",
        payload={
            "path": str(note.note_path),
            "opened": note.existed,
            "task_short_uuid": task.task_short_uuid,
        },
    )


def _run_chain(ctx, task_ref: str) -> CommandResult:
    task = ctx.taskwarrior.resolve_task(task_ref)
    note = ensure_chain_note(ctx.config, task)
    open_in_editor(note.note_path, ctx.config.editor_command)
    finalize_chain_note_edit(ctx.config, task, note)
    return CommandResult(
        command="chain",
        payload={
            "path": str(note.note_path),
            "opened": note.existed,
            "task_short_uuid": task.task_short_uuid,
        },
    )


def _run_show(ctx, task_ref: str) -> CommandResult:
    task = ctx.taskwarrior.resolve_task(task_ref)
    payload = _task_summary_payload(ctx, task)
    return CommandResult(command="show", payload=payload)


def _run_export(ctx, task_ref: str) -> CommandResult:
    task = ctx.taskwarrior.resolve_task(task_ref)
    payload = _task_summary_payload(ctx, task)
    payload["events"] = ctx.taskwarrior.annotations_for_task(task)
    return CommandResult(command="export", payload=payload)


def _task_summary_payload(ctx, task) -> dict:
    task_note = find_task_note(ctx.config, task)
    payload: dict[str, object] = {
        "task_short_uuid": task.task_short_uuid,
        "description": task.description,
        "task_note": str(task_note) if task_note is not None else None,
        "nautical": nautical_summary(task.task),
    }
    chain_note = find_chain_note(ctx.config, task)
    if chain_note is not None:
        payload["chain_note"] = str(chain_note)
    return payload


def _run_add(ctx, task_ref: str, text_parts: list[str], event_type: str) -> CommandResult:
    task = ctx.taskwarrior.resolve_task(task_ref)
    normalized_type = validate_event_type(event_type)
    text = collect_event_text(
        parts=text_parts,
        stdin_text=(sys.stdin.read().strip() if not sys.stdin.isatty() else None),
        editor_command=ctx.config.editor_command,
        task_short_uuid=task.task_short_uuid,
        description=task.description,
    )
    annotation = format_event_text(normalized_type, text)
    ctx.taskwarrior.add_annotation(task.task_uuid, annotation)
    record_event_add(ctx.config, task, event_type=normalized_type, annotation=annotation)
    return CommandResult(
        command="add",
        payload={
            "task_short_uuid": task.task_short_uuid,
            "annotation": annotation,
            "event_type": normalized_type,
        },
    )


def _run_list(ctx, task_ref: str) -> CommandResult:
    task = ctx.taskwarrior.resolve_task(task_ref)
    payload = _task_summary_payload(ctx, task)
    payload["events"] = ctx.taskwarrior.annotations_for_task(task)
    return CommandResult(command="list", payload=payload)


def _run_note_append(ctx, task_ref: str, text: str) -> CommandResult:
    task = ctx.taskwarrior.resolve_task(task_ref)
    result = append_task_note_storage(ctx.config, task, text)
    return CommandResult(
        command="note-append",
        payload={
            "path": str(result.note_path),
            "opened": result.existed,
            "task_short_uuid": task.task_short_uuid,
        },
    )


def _run_chain_append(ctx, task_ref: str, text: str) -> CommandResult:
    task = ctx.taskwarrior.resolve_task(task_ref)
    result = append_chain_note_storage(ctx.config, task, text)
    return CommandResult(
        command="chain-append",
        payload={
            "path": str(result.note_path),
            "opened": result.existed,
            "task_short_uuid": task.task_short_uuid,
        },
    )


def _run_search(ctx, query: str) -> CommandResult:
    payload = {
        "query": query,
        **search_all(ctx.config, query),
    }
    return CommandResult(command="search", payload=payload)


def _text_from_args(parts: list[str]) -> str:
    if parts:
        return " ".join(parts).strip()
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    raise RuntimeError("no text supplied; provide text or pipe stdin")
