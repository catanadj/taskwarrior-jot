from __future__ import annotations

import argparse
import sys

from . import __version__
from .app import build_app_context
from .config import ensure_app_dirs
from .doctor import run_doctor, run_doctor_config_error
from .editor import open_in_editor
from .events import collect_event_text, format_event_text, validate_event_type
from .frontmatter import read_document
from .index import rebuild_index, read_index_status, save_index
from .models import CommandResult
from .nautical import chain_id_for_task, nautical_summary
from .notes import (
    chain_note_path,
    ensure_chain_note,
    ensure_project_note,
    ensure_task_note,
    find_chain_note,
    find_project_note,
    find_task_note,
    project_note_path,
    task_note_path,
)
from .ops import iso_now, read_ops
from .output import emit_result, warn
from .report import list_project_notes, recent_activity
from .search import normalize_chain_id, normalize_kinds, normalize_project, search_all
from .services import JotService
from .storage import (
    add_to_chain_heading_storage,
    add_to_project_heading_storage,
    add_to_task_heading_storage,
    delete_chain_note_storage,
    delete_project_note_storage,
    delete_task_note_storage,
    append_chain_note_storage,
    append_project_note_storage,
    append_task_note_storage,
    finalize_chain_note_edit,
    finalize_project_note_edit,
    finalize_task_note_edit,
    record_event_add,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jot",
        description=(
            "Note-first companion for Taskwarrior and Taskwarrior-Nautical. "
            "Taskwarrior annotations remain the visible event stream; durable "
            "task, chain, and project context lives in note files under ~/.task/jot/."
        ),
        epilog=(
            "Examples:\n"
            "  jot note 42\n"
            "  jot chain 42\n"
            "  jot project Finances.Expense\n"
            "  jot show 42\n"
            "  jot list 42\n"
            "  jot export 42 --json\n"
            "  jot add --type status 42 waiting on vendor\n"
            "  jot add-to task 42 --heading \"Next steps\" --text \"Call vendor Monday\"\n"
            "  jot project-append Finances.Expense \"baseline updated\"\n"
            "  jot project-show Finances.Expense\n"
            "  jot task-cat 42\n"
            "  jot chain-cat 42\n"
            "  jot search --kind project-note vendor\n"
            "  jot report recent --limit 10\n"
            "  jot stats\n"
            "  jot paths\n"
            "  jot tui"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit machine-readable JSON instead of text",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "doctor",
        help="check configuration, storage paths, and Taskwarrior availability",
        description="Validate jot configuration, storage paths, and Taskwarrior access.",
    )
    subparsers.add_parser(
        "paths",
        help="show the resolved jot config and storage paths",
        description="Show the resolved jot configuration and storage directories.",
    )
    subparsers.add_parser(
        "rebuild-index",
        help="rebuild index.json from note files and ops log",
        description="Rebuild index.json from note files and the append-only ops log.",
    )
    subparsers.add_parser(
        "stats",
        help="show local jot note, ops, and index statistics",
        description="Show local jot note counts, event-log size, and index status without querying Taskwarrior.",
    )
    subparsers.add_parser(
        "tui",
        help="launch terminal UI",
        description="Launch the jot terminal user interface.",
    )
    subparsers.add_parser(
        "project-list",
        help="list known project notes",
        description="List known project notes discovered from the local jot projects directory.",
    )
    report = subparsers.add_parser(
        "report",
        help="show read-only reports from local jot state",
        description="Show read-only reports from local note files and the ops log.",
    )
    report_subparsers = report.add_subparsers(dest="report_command", required=True)
    report_recent = report_subparsers.add_parser(
        "recent",
        help="show recent note and event activity",
        description="Show recent note updates and logged events across the local jot dataset.",
    )
    report_recent.add_argument(
        "--limit",
        type=int,
        default=20,
        help="maximum number of items to return",
    )
    report_recent.add_argument(
        "--kind",
        action="append",
        dest="kinds",
        help="filter by kind: task-note, chain-note, project-note, event",
    )

    task_commands = {
        "note": "open or create the task note in your editor",
        "chain": "open or create the Nautical chain note in your editor",
        "show": "show note paths and Nautical summary for a task",
        "list": "show task summary plus the current annotation event stream",
        "export": "export task summary and events",
        "task-cat": "print the full task note without opening an editor",
        "chain-cat": "print the full chain note without opening an editor",
        "task-delete": "move the task note to trash",
        "chain-delete": "move the chain note to trash",
    }
    for name, help_text in task_commands.items():
        sub = subparsers.add_parser(name, help=help_text, description=help_text[:1].upper() + help_text[1:] + ".")
        sub.add_argument(
            "task_ref",
            help="task ID, full UUID, or unique short UUID",
        )

    project = subparsers.add_parser(
        "project",
        help="open or create a project note in your editor",
        description="Open or create a durable note for an exact Taskwarrior project name.",
    )
    project.add_argument(
        "project_name",
        help="exact Taskwarrior project name, for example Finances.Expense",
    )

    project_show = subparsers.add_parser(
        "project-show",
        help="show project-note path and summary without editing",
        description="Show whether a project note exists, where it lives, and a short preview.",
    )
    project_show.add_argument(
        "project_name",
        help="exact Taskwarrior project name, for example Finances.Expense",
    )

    project_cat = subparsers.add_parser(
        "project-cat",
        help="print the full project note without opening an editor",
        description="Print the full project note content for an exact Taskwarrior project name.",
    )
    project_cat.add_argument(
        "project_name",
        help="exact Taskwarrior project name, for example Finances.Expense",
    )

    project_delete = subparsers.add_parser(
        "project-delete",
        help="move the project note to trash",
        description="Move the project note to the jot trash directory without deleting the file permanently.",
    )
    project_delete.add_argument(
        "project_name",
        help="exact Taskwarrior project name, for example Finances.Expense",
    )

    append_commands = {
        "note-append": "append plain text to a task note",
        "chain-append": "append plain text to a chain note",
    }
    for name, help_text in append_commands.items():
        sub = subparsers.add_parser(name, help=help_text, description=help_text[:1].upper() + help_text[1:] + ".")
        sub.add_argument(
            "task_ref",
            help="task ID, full UUID, or unique short UUID",
        )
        sub.add_argument(
            "text",
            nargs="*",
            help="text to append; if omitted, read stdin",
        )

    project_append = subparsers.add_parser(
        "project-append",
        help="append plain text to a project note",
        description="Append plain text to a project note without opening an editor.",
    )
    project_append.add_argument(
        "project_name",
        help="exact Taskwarrior project name, for example Finances.Expense",
    )
    project_append.add_argument(
        "text",
        nargs="*",
        help="text to append; if omitted, read stdin",
    )

    add_to = subparsers.add_parser(
        "add-to",
        help="add a timestamped entry under a note heading",
        description=(
            "Add a timestamped bullet entry under a heading in a task, chain, or project note. "
            "Heading matching is fuzzy by default."
        ),
    )
    add_to.add_argument(
        "note_kind",
        choices=("task", "chain", "project"),
        help="target note kind",
    )
    add_to.add_argument(
        "note_ref",
        help="task ref for task/chain or project name for project",
    )
    add_to.add_argument(
        "--heading",
        required=True,
        help="target heading title",
    )
    add_to.add_argument(
        "--create-heading",
        action="store_true",
        help="create the heading when no match is found",
    )
    add_to.add_argument(
        "--heading-exact",
        action="store_true",
        help="disable fuzzy matching and require an exact heading match",
    )
    add_to.add_argument(
        "--text",
        help="entry text; if omitted, read stdin",
    )

    add = subparsers.add_parser(
        "add",
        help="add a short event to the task annotation stream",
        description=(
            "Add a short event to the Taskwarrior annotation stream. "
            "Text can come from arguments, stdin, or an editor fallback."
        ),
    )
    add.add_argument(
        "--type",
        default="note",
        dest="event_type",
        help="event type label, for example note, status, decision, blocker",
    )
    add.add_argument(
        "task_ref",
        help="task ID, full UUID, or unique short UUID",
    )
    add.add_argument(
        "text",
        nargs="*",
        help="event text; if omitted, read stdin or open the editor",
    )

    search = subparsers.add_parser(
        "search",
        help="search note files and logged events",
        description="Search task notes, chain notes, project notes, and the logged event stream.",
    )
    search.add_argument("query", help="case-insensitive search text")
    search.add_argument(
        "--kind",
        action="append",
        dest="kinds",
        help="filter by kind: task-note, chain-note, project-note, event",
    )
    search.add_argument(
        "--project",
        help="filter by exact Taskwarrior project name",
    )
    search.add_argument(
        "--chain",
        dest="chain_id",
        help="filter by exact Nautical chainID",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        build_parser().print_help()
        return 0

    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        ctx = build_app_context()
        ensure_app_dirs(ctx.config)
    except Exception as exc:
        if args.command == "doctor":
            emit_result(run_doctor_config_error(f"failed to load config: {exc}"), json_mode=args.json)
            return 0
        warn(str(exc))
        return 1

    try:
        if args.command == "doctor":
            result = run_doctor(ctx.config, ctx.taskwarrior)
        elif args.command == "paths":
            result = _run_paths(ctx)
        elif args.command == "rebuild-index":
            result = _run_rebuild_index(ctx)
        elif args.command == "stats":
            result = _run_stats(ctx)
        elif args.command == "tui":
            return _run_tui(ctx)
        elif args.command == "project-list":
            result = _run_project_list(ctx)
        elif args.command == "report":
            result = _run_report(ctx, args)
        elif args.command == "note":
            result = _run_note(ctx, args.task_ref)
        elif args.command == "chain":
            result = _run_chain(ctx, args.task_ref)
        elif args.command == "task-cat":
            result = _run_task_cat(ctx, args.task_ref)
        elif args.command == "chain-cat":
            result = _run_chain_cat(ctx, args.task_ref)
        elif args.command == "task-delete":
            result = _run_task_delete(ctx, args.task_ref)
        elif args.command == "chain-delete":
            result = _run_chain_delete(ctx, args.task_ref)
        elif args.command == "project":
            result = _run_project(ctx, args.project_name)
        elif args.command == "project-show":
            result = _run_project_show(ctx, args.project_name)
        elif args.command == "project-cat":
            result = _run_project_cat(ctx, args.project_name)
        elif args.command == "project-delete":
            result = _run_project_delete(ctx, args.project_name)
        elif args.command == "add":
            result = _run_add(ctx, args.task_ref, args.text, args.event_type)
        elif args.command == "note-append":
            result = _run_note_append(ctx, args.task_ref, _text_from_args(args.text))
        elif args.command == "chain-append":
            result = _run_chain_append(ctx, args.task_ref, _text_from_args(args.text))
        elif args.command == "project-append":
            result = _run_project_append(ctx, args.project_name, _text_from_args(args.text))
        elif args.command == "add-to":
            result = _run_add_to(ctx, args)
        elif args.command == "list":
            result = _run_list(ctx, args.task_ref)
        elif args.command == "show":
            result = _run_show(ctx, args.task_ref)
        elif args.command == "export":
            result = _run_export(ctx, args.task_ref)
        elif args.command == "search":
            result = _run_search(
                ctx,
                args.query,
                getattr(args, "kinds", None),
                getattr(args, "project", None),
                getattr(args, "chain_id", None),
            )
        else:  # pragma: no cover
            parser.error(f"unknown command {args.command}")
            return 2
    except RuntimeError as exc:
        warn(str(exc))
        return 1

    emit_result(result, json_mode=args.json)
    return 0


def _run_tui(ctx) -> int:
    try:
        from jot_tui.app import run_tui
    except Exception as exc:
        raise RuntimeError(f"failed to load TUI: {exc}") from exc
    service = JotService(config=ctx.config, taskwarrior=ctx.taskwarrior)
    return run_tui(service)


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


def _run_paths(ctx) -> CommandResult:
    config = ctx.config
    return CommandResult(
        command="paths",
        payload={
            "config_path": str(config.config_path),
            "root_dir": str(config.root_dir),
            "trash_dir": str(config.trash_dir),
            "tasks_dir": str(config.tasks_dir),
            "chains_dir": str(config.chains_dir),
            "projects_dir": str(config.projects_dir),
            "templates_dir": str(config.templates_dir),
            "index_path": str(config.root_dir / "index.json"),
            "ops_path": str(config.root_dir / "ops.jsonl"),
        },
    )


def _run_rebuild_index(ctx) -> CommandResult:
    data = rebuild_index(ctx.config)
    save_index(ctx.config, data)
    return CommandResult(
        command="rebuild-index",
        payload={
            "index_path": str(ctx.config.root_dir / "index.json"),
            "updated": data.get("updated"),
            "counts": {
                "tasks": len(data.get("tasks", {})),
                "chains": len(data.get("chains", {})),
                "projects": len(data.get("projects", {})),
            },
        },
    )


def _run_stats(ctx) -> CommandResult:
    task_count = len(list(ctx.config.tasks_dir.glob("*.md")))
    chain_count = len(list(ctx.config.chains_dir.glob("*.md")))
    project_count = len(list(ctx.config.projects_dir.glob("**/index.md")))
    ops_items = read_ops(ctx.config)
    index_status = read_index_status(ctx.config)
    note_counts = {
        "tasks": task_count,
        "chains": chain_count,
        "projects": project_count,
    }
    latest_op_ts = _latest_op_timestamp(ops_items)
    stale = _index_is_stale(index_status, note_counts, latest_op_ts)
    return CommandResult(
        command="stats",
        payload={
            "notes": note_counts,
            "ops": {
                "path": str(ctx.config.root_dir / "ops.jsonl"),
                "entries": len(ops_items),
                "event_add": sum(1 for item in ops_items if item.get("op") == "event_add"),
                "latest": latest_op_ts,
            },
            "index": {
                "path": str(ctx.config.root_dir / "index.json"),
                **index_status,
                "stale": stale,
            },
        },
    )


def _run_project_list(ctx) -> CommandResult:
    return CommandResult(
        command="project-list",
        payload={"projects": list_project_notes(ctx.config)},
    )


def _run_report(ctx, args) -> CommandResult:
    if args.report_command == "recent":
        kinds = normalize_kinds(getattr(args, "kinds", None))
        return CommandResult(
            command="report-recent",
            payload={
                "limit": args.limit,
                "kinds": sorted(kinds),
                "items": recent_activity(ctx.config, limit=args.limit, kinds=kinds),
            },
        )
    raise RuntimeError(f"unknown report '{args.report_command}'")


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


def _run_project(ctx, project_name: str) -> CommandResult:
    note = ensure_project_note(ctx.config, project_name)
    open_in_editor(note.note_path, ctx.config.editor_command)
    finalize_project_note_edit(ctx.config, project_name, note)
    return CommandResult(
        command="project",
        payload={
            "path": str(note.note_path),
            "opened": note.existed,
            "project": project_name,
        },
    )


def _run_project_show(ctx, project_name: str) -> CommandResult:
    note_path = find_project_note(ctx.config, project_name)
    note_summary = _project_note_summary(ctx, project_name)
    if note_path is None:
        return CommandResult(
            command="project-show",
            payload={
                "kind": "project-summary",
                "project": project_name,
                "note": note_summary,
            },
        )

    metadata, body = read_document(note_path)
    return CommandResult(
        command="project-show",
        payload={
            "kind": "project-summary",
            "project": project_name,
            "note": {
                **note_summary,
                "created": metadata.get("created"),
                "updated": metadata.get("updated"),
                "project_path": metadata.get("project_path") or [],
                "preview": _body_preview(body),
            },
        },
    )


def _run_project_cat(ctx, project_name: str) -> CommandResult:
    note_path = find_project_note(ctx.config, project_name)
    if note_path is None:
        raise RuntimeError(f"project note does not exist for {project_name}")
    return _cat_result("project-cat", note_path, project=project_name)


def _run_task_cat(ctx, task_ref: str) -> CommandResult:
    task = ctx.taskwarrior.resolve_task(task_ref)
    note_path = find_task_note(ctx.config, task)
    if note_path is None:
        raise RuntimeError(f"task note does not exist for {task.task_short_uuid}")
    return _cat_result(
        "task-cat",
        note_path,
        task_short_uuid=task.task_short_uuid,
    )


def _run_chain_cat(ctx, task_ref: str) -> CommandResult:
    task = ctx.taskwarrior.resolve_task(task_ref)
    note_path = find_chain_note(ctx.config, task)
    if note_path is None:
        raise RuntimeError(f"chain note does not exist for {task.task_short_uuid}")
    return _cat_result(
        "chain-cat",
        note_path,
        task_short_uuid=task.task_short_uuid,
    )


def _run_task_delete(ctx, task_ref: str) -> CommandResult:
    task = ctx.taskwarrior.resolve_task(task_ref)
    result = delete_task_note_storage(ctx.config, task)
    return CommandResult(
        command="task-delete",
        payload={
            "task_short_uuid": task.task_short_uuid,
            "path": str(result["note_path"]),
            "trash_path": str(result["trash_path"]),
        },
    )


def _run_chain_delete(ctx, task_ref: str) -> CommandResult:
    task = ctx.taskwarrior.resolve_task(task_ref)
    result = delete_chain_note_storage(ctx.config, task)
    return CommandResult(
        command="chain-delete",
        payload={
            "task_short_uuid": task.task_short_uuid,
            "chain_id": result.get("chain_id"),
            "path": str(result["note_path"]),
            "trash_path": str(result["trash_path"]),
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
    payload["exported_at"] = iso_now()
    return CommandResult(command="export", payload=payload)


def _task_summary_payload(ctx, task) -> dict:
    payload: dict[str, object] = {
        "kind": "task-summary",
        "task": {
            "uuid": task.task_uuid,
            "short_uuid": task.task_short_uuid,
            "description": task.description,
            "project": task.project or None,
            "tags": list(task.tags),
        },
        "notes": {
            "task": _task_note_summary(ctx, task),
            "chain": _chain_note_summary(ctx, task),
            "project": _project_note_summary(ctx, task.project),
        },
        "nautical": nautical_summary(task.task),
    }
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


def _run_project_append(ctx, project_name: str, text: str) -> CommandResult:
    result = append_project_note_storage(ctx.config, project_name, text)
    return CommandResult(
        command="project-append",
        payload={
            "path": str(result.note_path),
            "opened": result.existed,
            "project": project_name,
        },
    )


def _run_project_delete(ctx, project_name: str) -> CommandResult:
    result = delete_project_note_storage(ctx.config, project_name)
    return CommandResult(
        command="project-delete",
        payload={
            "project": project_name,
            "path": str(result["note_path"]),
            "trash_path": str(result["trash_path"]),
        },
    )


def _run_add_to(ctx, args) -> CommandResult:
    text = _text_from_optional(args.text)
    if args.note_kind == "task":
        task = ctx.taskwarrior.resolve_task(args.note_ref)
        result = add_to_task_heading_storage(
            ctx.config,
            task,
            heading=args.heading,
            text=text,
            create_heading=bool(args.create_heading),
            exact=bool(args.heading_exact),
        )
        return CommandResult(
            command="add-to",
            payload={
                "note_kind": "task",
                "task_short_uuid": task.task_short_uuid,
                "path": str(result["note_path"]),
                "opened": bool(result["opened"]),
                "heading": result["heading"],
                "heading_match": result["heading_match"],
                "timestamp": result["timestamp"],
                "entry": result["entry"],
            },
        )
    if args.note_kind == "chain":
        task = ctx.taskwarrior.resolve_task(args.note_ref)
        result = add_to_chain_heading_storage(
            ctx.config,
            task,
            heading=args.heading,
            text=text,
            create_heading=bool(args.create_heading),
            exact=bool(args.heading_exact),
        )
        return CommandResult(
            command="add-to",
            payload={
                "note_kind": "chain",
                "task_short_uuid": task.task_short_uuid,
                "path": str(result["note_path"]),
                "opened": bool(result["opened"]),
                "heading": result["heading"],
                "heading_match": result["heading_match"],
                "timestamp": result["timestamp"],
                "entry": result["entry"],
            },
        )
    project_name = str(args.note_ref).strip()
    result = add_to_project_heading_storage(
        ctx.config,
        project_name,
        heading=args.heading,
        text=text,
        create_heading=bool(args.create_heading),
        exact=bool(args.heading_exact),
    )
    return CommandResult(
        command="add-to",
        payload={
            "note_kind": "project",
            "project": project_name,
            "path": str(result["note_path"]),
            "opened": bool(result["opened"]),
            "heading": result["heading"],
            "heading_match": result["heading_match"],
            "timestamp": result["timestamp"],
            "entry": result["entry"],
        },
    )


def _run_search(
    ctx,
    query: str,
    raw_kinds: list[str] | None,
    raw_project: str | None,
    raw_chain_id: str | None,
) -> CommandResult:
    kinds = normalize_kinds(raw_kinds)
    project = normalize_project(raw_project)
    chain_id = normalize_chain_id(raw_chain_id)
    payload = {
        "query": query,
        "kinds": sorted(kinds),
        "project": project,
        "chain_id": chain_id,
        **search_all(ctx.config, query, kinds=kinds, project=project, chain_id=chain_id),
    }
    return CommandResult(command="search", payload=payload)


def _text_from_args(parts: list[str]) -> str:
    if parts:
        return " ".join(parts).strip()
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    raise RuntimeError("no text supplied; provide text or pipe stdin")


def _text_from_optional(value: str | None) -> str:
    if value is not None:
        text = str(value).strip()
        if text:
            return text
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    raise RuntimeError("no text supplied; provide text or pipe stdin")


def _body_preview(body: str, width: int = 120) -> str:
    text = " ".join(str(body or "").split())
    if len(text) <= width:
        return text
    return text[: width - 3].rstrip() + "..."


def _cat_result(command: str, note_path, **extra: str) -> CommandResult:
    metadata, body = read_document(note_path)
    payload = {
        **extra,
        "path": str(note_path),
        "metadata": dict(metadata),
        "body": body,
        "content": note_path.read_text(encoding="utf-8"),
    }
    return CommandResult(command=command, payload=payload)


def _latest_op_timestamp(items: list[dict[str, object]]) -> str | None:
    timestamps = [str(item.get("ts") or "").strip() for item in items if str(item.get("ts") or "").strip()]
    return max(timestamps) if timestamps else None


def _index_is_stale(index_status: dict[str, object], note_counts: dict[str, int], latest_op_ts: str | None) -> bool:
    if not bool(index_status.get("exists")) or not bool(index_status.get("valid")):
        return True
    counts = index_status.get("counts") if isinstance(index_status.get("counts"), dict) else {}
    for key, value in note_counts.items():
        if counts.get(key) != value:
            return True
    updated = str(index_status.get("updated") or "").strip() or None
    if latest_op_ts and (not updated or latest_op_ts > updated):
        return True
    return False


def _task_note_summary(ctx, task) -> dict[str, object]:
    note_path = find_task_note(ctx.config, task)
    expected = task_note_path(ctx.config, task)
    return {
        "available": True,
        "exists": note_path is not None,
        "path": str(note_path or expected),
    }


def _chain_note_summary(ctx, task) -> dict[str, object]:
    chain_id = chain_id_for_task(task.task)
    if not chain_id:
        return {
            "available": False,
            "exists": False,
            "path": None,
        }
    note_path = find_chain_note(ctx.config, task)
    expected = chain_note_path(ctx.config, chain_id, task.description or chain_id)
    return {
        "available": True,
        "exists": note_path is not None,
        "path": str(note_path or expected),
    }


def _project_note_summary(ctx, project_name: str | None) -> dict[str, object]:
    normalized = str(project_name or "").strip()
    if not normalized:
        return {
            "available": False,
            "exists": False,
            "path": None,
        }
    note_path = find_project_note(ctx.config, normalized)
    expected = project_note_path(ctx.config, normalized)
    return {
        "available": True,
        "exists": note_path is not None,
        "path": str(note_path or expected),
    }
