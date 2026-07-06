from __future__ import annotations

import argparse
import sys

from . import __version__
from .app import build_app_context
from .command_help import build_command_catalog
from .command_prefix import AmbiguousCommandPrefix, expand_command_prefixes
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
    list_note_headings,
    list_note_resources,
    project_note_path,
    read_note_section,
    task_note_path,
)
from .ops import iso_now, read_ops
from .output import emit_result, warn
from .report import (
    list_notes,
    list_project_notes,
    normalize_note_kinds,
    project_rollup,
    recent_activity,
)
from .progress import (
    parse_progress_pair,
    parse_progress_value,
    read_note_progress,
    read_note_progress_analysis,
)
from .resources import open_resource_target
from .search import normalize_chain_id, normalize_kinds, normalize_project, search_all
from .services import JotService
from .storage import (
    add_to_chain_heading_storage,
    add_to_project_heading_storage,
    add_to_task_heading_storage,
    attach_chain_resource_storage,
    attach_project_resource_storage,
    attach_task_resource_storage,
    delete_chain_note_storage,
    delete_project_note_storage,
    delete_task_note_storage,
    detach_chain_resource_storage,
    detach_project_resource_storage,
    detach_task_resource_storage,
    append_chain_note_storage,
    append_project_note_storage,
    append_task_note_storage,
    finalize_chain_note_edit,
    finalize_project_note_edit,
    finalize_task_note_edit,
    mutate_project_progress_storage,
    mutate_task_progress_storage,
    record_event_add,
)
from .taskwarrior import INTEGER_RE, SHORT_UUID_RE, UUID_RE
from .timelog import (
    cancel_time_session,
    ingest_time_log,
    list_time_sessions,
    report_time_logs,
    stop_all_time_sessions,
    start_time_session,
    stop_time_session,
)
from .trash import list_trash, restore_trash_item


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
            "  jot 42\n"
            "  jot note 42\n"
            "  jot chain 42\n"
            "  jot project Finances.Expense\n"
            "  jot show 42\n"
            "  jot list 42\n"
            "  jot export 42 --json\n"
            "  jot add --type status 42 waiting on vendor\n"
            "  jot add-to task 42 --heading \"Next steps\" --text \"Call vendor Monday\"\n"
            "  jot attach task 42 ~/invoice.pdf --label invoice\n"
            "  jot resources task 42\n"
            "  jot open-resource task 42 1\n"
            "  jot notes --kind task\n"
            "  jot recent --limit 10\n"
            "  jot open chain 42\n"
            "  jot cat project Finances.Expense\n"
            "  jot progress task 42 set 120/350 --unit pages\n"
            "  jot progress task 42 add 20\n"
            "  jot progress task 42 show\n"
            "  jot project-append Finances.Expense \"baseline updated\"\n"
            "  jot project-show Finances.Expense\n"
            "  jot project-report Finances.Expense\n"
            "  jot task-cat 42\n"
            "  jot chain-cat 42\n"
            "  jot search --kind project-note vendor\n"
            "  jot report recent --limit 10\n"
            "  jot headings task 42\n"
            "  jot section task 42 \"Next steps\"\n"
            "  jot trash-list\n"
            "  jot trash-restore 1\n"
            "  jot stats\n"
            "  jot paths\n"
            "  jot tui\n"
            "\n"
            "Commands accept unique prefixes, for example: jot proj-r Finances.Expense"
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
    notes = subparsers.add_parser(
        "notes",
        help="list existing task, chain, and project notes",
        description="List existing jot notes across task, chain, and project scopes.",
    )
    notes.add_argument(
        "--kind",
        action="append",
        dest="kinds",
        help="filter by note kind: task, chain, project",
    )
    notes.add_argument(
        "--project",
        help="filter notes by exact Taskwarrior project name",
    )
    subparsers.add_parser(
        "trash-list",
        help="list notes currently in jot trash",
        description="List notes moved to the jot trash directory by task-delete, chain-delete, or project-delete.",
    )
    trash_restore = subparsers.add_parser(
        "trash-restore",
        help="restore a note from jot trash",
        description="Restore a trashed note by the ID shown by trash-list.",
    )
    trash_restore.add_argument("trash_id", type=int, help="ID shown by trash-list")
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
    recent = subparsers.add_parser(
        "recent",
        help="show recent note and event activity",
        description="Shortcut for report recent.",
    )
    recent.add_argument(
        "--limit",
        type=int,
        default=20,
        help="maximum number of items to return",
    )
    recent.add_argument(
        "--kind",
        action="append",
        dest="kinds",
        help="filter by kind: task-note, chain-note, project-note, event",
    )

    open_note = subparsers.add_parser(
        "open",
        help="open a task, chain, or project note in your editor",
        description="Open a note using a simpler scope-first command. Omit scope to use task/chain auto routing.",
    )
    open_note.add_argument(
        "target",
        nargs="+",
        help="task ref, or: task <ref>, chain <ref>, project <name>",
    )

    edit_note = subparsers.add_parser(
        "edit",
        help="alias for open",
        description="Alias for open.",
    )
    edit_note.add_argument(
        "target",
        nargs="+",
        help="task ref, or: task <ref>, chain <ref>, project <name>",
    )

    cat_note = subparsers.add_parser(
        "cat",
        help="print a task, chain, or project note without editing",
        description="Print a note using a simpler scope-first command. Omit scope for task notes.",
    )
    cat_note.add_argument(
        "target",
        nargs="+",
        help="task ref, or: task <ref>, chain <ref>, project <name>",
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

    project_report = subparsers.add_parser(
        "project-report",
        help="show project note, active tasks, recent activity, and chains",
        description="Show a read-only rollup for one exact Taskwarrior project.",
    )
    project_report.add_argument(
        "project_name",
        help="exact Taskwarrior project name, for example Finances.Expense",
    )
    project_report.add_argument(
        "--limit",
        type=int,
        default=20,
        help="maximum number of recent activity items to show",
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

    timelog = subparsers.add_parser(
        "timelog",
        help="record time expenditure from Taskwarrior hook JSON",
        description="Record task stop intervals as time expenditure entries in task or chain notes.",
    )
    timelog_subparsers = timelog.add_subparsers(dest="timelog_command", required=True)
    timelog_ingest = timelog_subparsers.add_parser(
        "ingest",
        help="read old/new Taskwarrior JSON from stdin and append a time log entry",
        description=(
            "Read two JSON lines from stdin, as provided to an on-modify hook. "
            "When a task stop is detected, append a time expenditure entry under the Time log heading."
        ),
    )
    timelog_ingest.add_argument(
        "--scope",
        choices=("auto", "task", "chain"),
        default="auto",
        help="write to chain notes when chainID exists, otherwise task notes",
    )
    timelog_ingest.add_argument(
        "--stopped-at",
        default="",
        help="override stop time for backfills/tests; accepts Taskwarrior or ISO timestamps",
    )
    timelog_start = timelog_subparsers.add_parser(
        "start",
        help="record a pending Jot-managed timelog session",
        description="Record a start timestamp for a task. Useful when Taskwarrior hooks cannot run.",
    )
    timelog_start.add_argument("task_ref", help="task ID, full UUID, or unique short UUID")
    timelog_start.add_argument("--at", default="", help="override start time; accepts Taskwarrior or ISO timestamps")
    timelog_stop = timelog_subparsers.add_parser(
        "stop",
        help="stop a pending Jot-managed timelog session and write the note entry",
        description="Use the pending start timestamp and current task metadata to append a time expenditure entry.",
    )
    timelog_stop.add_argument("task_ref", nargs="?", help="task ID, full UUID, or unique short UUID")
    timelog_stop.add_argument("--all", action="store_true", help="stop all pending Jot-managed timelog sessions")
    timelog_stop.add_argument("--at", default="", help="override stop time; accepts Taskwarrior or ISO timestamps")
    timelog_stop.add_argument(
        "--scope",
        choices=("auto", "task", "chain"),
        default="auto",
        help="write to chain notes when chainID exists, otherwise task notes",
    )
    timelog_cancel = timelog_subparsers.add_parser(
        "cancel",
        help="remove a pending Jot-managed timelog session without writing a note",
    )
    timelog_cancel.add_argument("task_ref", help="task ID, full UUID, or unique short UUID")
    timelog_subparsers.add_parser(
        "pending",
        help="list pending Jot-managed timelog sessions",
        description="Show sessions created by 'jot timelog start' that have not been stopped or cancelled.",
    )
    timelog_report = timelog_subparsers.add_parser(
        "report",
        help="summarize recorded time expenditure",
        description="Summarize structured Jot timelog entries stored in task and chain notes.",
    )
    timelog_report.add_argument(
        "period",
        nargs="?",
        choices=("all", "today", "week", "month"),
        default="all",
        help="time window based on the local stop date",
    )
    timelog_report.add_argument("--project", default="", help="only include entries for this project")
    timelog_report.add_argument("--task", default="", help="only include entries for this task UUID or short UUID")
    timelog_report.add_argument("--chain", default="", help="only include entries for this chainID")

    headings = subparsers.add_parser(
        "headings",
        help="list headings in a task, chain, or project note",
        description="List Markdown headings in a task, chain, or project note.",
    )
    headings.add_argument("note_kind", choices=("task", "chain", "project"), help="target note kind")
    headings.add_argument("note_ref", help="task ref for task/chain or project name for project")

    section = subparsers.add_parser(
        "section",
        help="print one note section by heading",
        description="Print one section from a task, chain, or project note. Heading matching is fuzzy by default.",
    )
    section.add_argument("note_kind", choices=("task", "chain", "project"), help="target note kind")
    section.add_argument("note_ref", help="task ref for task/chain or project name for project")
    section.add_argument("heading", help="heading title to print")
    section.add_argument(
        "--heading-exact",
        action="store_true",
        help="disable fuzzy matching and require an exact heading match",
    )

    attach = subparsers.add_parser(
        "attach",
        help="add a file or URL resource to a note",
        description=(
            "Add a file path or URL under the Resources or References heading "
            "in a task, chain, or project note."
        ),
    )
    attach.add_argument("note_kind", choices=("task", "chain", "project"), help="target note kind")
    attach.add_argument("note_ref", help="task ref for task/chain or project name for project")
    attach.add_argument("target", help="file path, URL, or external target to store")
    attach.add_argument("--label", help="optional display label")

    resources = subparsers.add_parser(
        "resources",
        help="list resources stored in a note",
        description="List file paths and URLs from the Resources or References heading in a task, chain, or project note.",
    )
    resources.add_argument("note_kind", choices=("task", "chain", "project"), help="target note kind")
    resources.add_argument("note_ref", help="task ref for task/chain or project name for project")

    open_resource = subparsers.add_parser(
        "open-resource",
        help="open a note resource by ID",
        description="Open a resource listed by the resources command. Set JOT_OPENER to override the opener.",
    )
    open_resource.add_argument("note_kind", choices=("task", "chain", "project"), help="target note kind")
    open_resource.add_argument("note_ref", help="task ref for task/chain or project name for project")
    open_resource.add_argument("resource_id", type=int, help="resource ID shown by resources")

    detach_resource = subparsers.add_parser(
        "detach-resource",
        help="remove a resource from a note",
        description="Remove a resource bullet from the Resources or References heading in a task, chain, or project note.",
    )
    detach_resource.add_argument("note_kind", choices=("task", "chain", "project"), help="target note kind")
    detach_resource.add_argument("note_ref", help="task ref for task/chain or project name for project")
    detach_resource.add_argument("resource_id", type=int, help="resource ID shown by resources")

    progress = subparsers.add_parser(
        "progress",
        help="track generic progress in a task, chain, or project note",
        description="Track content-agnostic progress using decimal current and target values.",
    )
    progress.add_argument("note_kind", choices=("task", "chain", "project"), help="target note kind")
    progress.add_argument(
        "note_ref",
        help="task ref or project name; progress show accepts comma-separated references",
    )
    progress_subparsers = progress.add_subparsers(dest="progress_command", required=True)

    progress_set = progress_subparsers.add_parser(
        "set",
        help="set current and target progress",
        description="Set progress using CURRENT/TARGET values with optional user-defined unit and status.",
    )
    progress_set.add_argument("measurement", help="CURRENT/TARGET, for example 120/350")
    progress_set.add_argument("--unit", help="user-defined unit, for example pages, km, or items")
    progress_set.add_argument("--status", help="optional user-defined status")
    progress_set.add_argument("--track", default="default", help="progress track name; default: default")

    progress_add = progress_subparsers.add_parser(
        "add",
        help="increase current progress",
        description="Increase the current progress value by a decimal amount.",
    )
    progress_add.add_argument("amount", help="decimal amount to add")
    progress_add.add_argument("--track", help="progress track name; inferred when only one track exists")

    progress_subtract = progress_subparsers.add_parser(
        "subtract",
        help="decrease current progress",
        description="Decrease the current progress value by a decimal amount.",
    )
    progress_subtract.add_argument("amount", help="decimal amount to subtract")
    progress_subtract.add_argument("--track", help="progress track name; inferred when only one track exists")

    progress_show = progress_subparsers.add_parser(
        "show",
        help="show current progress",
        description="Show all progress tracks, or one named track, without modifying the note.",
    )
    progress_show.add_argument("--track", help="show only this progress track")
    progress_show.add_argument(
        "--history",
        type=int,
        default=5,
        help="number of recent history entries to show; use 0 to hide history",
    )

    progress_status = progress_subparsers.add_parser(
        "status",
        help="set a user-defined progress status",
        description="Set a free-form status on existing progress.",
    )
    progress_status.add_argument("value", help="status value, for example active, paused, or complete")
    progress_status.add_argument("--track", help="progress track name; inferred when only one track exists")

    progress_clear = progress_subparsers.add_parser(
        "clear",
        help="clear current progress state",
        description="Remove progress state from frontmatter while retaining the human-readable history.",
    )
    progress_clear.add_argument(
        "--yes",
        action="store_true",
        help="confirm clearing the current progress state",
    )
    progress_clear.add_argument("--track", help="progress track name; inferred when only one track exists")

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
        parser = build_parser()
        if sys.stdin.isatty() and sys.stdout.isatty():
            try:
                from jot_tui.command_browser import run_command_browser

                return run_command_browser(build_command_catalog(parser))
            except RuntimeError:
                pass
        parser.print_help()
        return 0
    shorthand_ref, shorthand_json = _parse_task_shorthand(argv)
    if shorthand_ref:
        try:
            ctx = build_app_context()
            ensure_app_dirs(ctx.config)
            result = _run_auto_note(ctx, shorthand_ref)
        except RuntimeError as exc:
            warn(str(exc))
            return 1
        except Exception as exc:
            warn(str(exc))
            return 1
        emit_result(result, json_mode=shorthand_json)
        return 0

    parser = build_parser()
    try:
        argv = expand_command_prefixes(parser, argv)
    except AmbiguousCommandPrefix as exc:
        parser.error(str(exc))
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
        elif args.command == "notes":
            result = _run_notes(ctx, args)
        elif args.command == "trash-list":
            result = _run_trash_list(ctx)
        elif args.command == "trash-restore":
            result = _run_trash_restore(ctx, args.trash_id)
        elif args.command == "report":
            result = _run_report(ctx, args)
        elif args.command == "recent":
            result = _run_recent(ctx, args)
        elif args.command in {"open", "edit"}:
            result = _run_open_alias(ctx, args.target)
        elif args.command == "cat":
            result = _run_cat_alias(ctx, args.target)
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
        elif args.command == "project-report":
            result = _run_project_report(ctx, args.project_name, args.limit)
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
        elif args.command == "timelog":
            result = _run_timelog(ctx, args)
        elif args.command == "headings":
            result = _run_headings(ctx, args)
        elif args.command == "section":
            result = _run_section(ctx, args)
        elif args.command == "attach":
            result = _run_attach(ctx, args)
        elif args.command == "resources":
            result = _run_resources(ctx, args)
        elif args.command == "open-resource":
            result = _run_open_resource(ctx, args)
        elif args.command == "detach-resource":
            result = _run_detach_resource(ctx, args)
        elif args.command == "progress":
            result = _run_progress(ctx, args)
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


def _parse_task_shorthand(argv: list[str]) -> tuple[str | None, bool]:
    json_mode = False
    args = list(argv)
    if args and args[0] == "--json":
        json_mode = True
        args = args[1:]
    if len(args) != 1:
        return None, json_mode
    ref = str(args[0] or "").strip()
    if INTEGER_RE.fullmatch(ref) or SHORT_UUID_RE.fullmatch(ref) or UUID_RE.fullmatch(ref):
        return ref, json_mode
    return None, json_mode


def _run_tui(ctx) -> int:
    try:
        from jot_tui.app import run_tui
    except Exception as exc:
        raise RuntimeError(f"failed to load TUI: {exc}") from exc
    service = JotService(config=ctx.config, taskwarrior=ctx.taskwarrior)
    return run_tui(service)


def _open_note_in_editor(ctx, path) -> None:
    open_in_editor(
        path,
        ctx.config.editor_command,
        show_diff=ctx.config.editor_show_diff_on_save,
        color_mode=ctx.config.editor_diff_color,
    )


def _offer_post_save_task_action(ctx, task) -> dict | None:
    if not ctx.config.editor_post_save_actions or not sys.stdin.isatty():
        return None

    sys.stderr.write("\nPost-save actions\n")
    sys.stderr.write(f"Task: {task.task_short_uuid}  {task.description}\n")
    sys.stderr.write("  c  complete task\n")
    sys.stderr.write("  enter  do nothing\n")
    sys.stderr.write("Action: ")
    sys.stderr.flush()

    choice = sys.stdin.readline().strip().casefold()
    if choice not in {"c", "complete", "complete task", "done"}:
        return None

    ctx.taskwarrior.complete_task(task.task_uuid)
    return {
        "action": "complete-task",
        "task_uuid": task.task_uuid,
        "task_short_uuid": task.task_short_uuid,
        "description": task.description,
    }


def _run_trash_list(ctx) -> CommandResult:
    return CommandResult(command="trash-list", payload={"items": list_trash(ctx.config)})


def _run_trash_restore(ctx, trash_id: int) -> CommandResult:
    return CommandResult(command="trash-restore", payload=restore_trash_item(ctx.config, trash_id))


def _run_auto_note(ctx, task_ref: str) -> CommandResult:
    task = ctx.taskwarrior.resolve_task(task_ref)
    if chain_id_for_task(task.task):
        note = ensure_chain_note(ctx.config, task)
        _open_note_in_editor(ctx, note.note_path)
        finalize_chain_note_edit(ctx.config, task, note)
        post_save_action = _offer_post_save_task_action(ctx, task)
        return CommandResult(
            command="chain",
            payload={
                "path": str(note.note_path),
                "opened": note.existed,
                "task_short_uuid": task.task_short_uuid,
                "post_save_action": post_save_action,
            },
        )
    note = ensure_task_note(ctx.config, task)
    _open_note_in_editor(ctx, note.note_path)
    finalize_task_note_edit(ctx.config, task, note)
    post_save_action = _offer_post_save_task_action(ctx, task)
    return CommandResult(
        command="note",
        payload={
            "path": str(note.note_path),
            "opened": note.existed,
            "task_short_uuid": task.task_short_uuid,
            "post_save_action": post_save_action,
        },
    )


def _run_note(ctx, task_ref: str) -> CommandResult:
    task = ctx.taskwarrior.resolve_task(task_ref)
    note = ensure_task_note(ctx.config, task)
    _open_note_in_editor(ctx, note.note_path)
    finalize_task_note_edit(ctx.config, task, note)
    post_save_action = _offer_post_save_task_action(ctx, task)
    return CommandResult(
        command="note",
        payload={
            "path": str(note.note_path),
            "opened": note.existed,
            "task_short_uuid": task.task_short_uuid,
            "post_save_action": post_save_action,
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


def _run_notes(ctx, args) -> CommandResult:
    kinds = normalize_note_kinds(getattr(args, "kinds", None))
    return CommandResult(
        command="notes",
        payload={
            "kinds": sorted(kinds or {"task-note", "chain-note", "project-note"}),
            "project": getattr(args, "project", None),
            "notes": list_notes(ctx.config, kinds=kinds, project=getattr(args, "project", None)),
        },
    )


def _run_report(ctx, args) -> CommandResult:
    if args.report_command == "recent":
        return _run_recent(ctx, args)
    raise RuntimeError(f"unknown report '{args.report_command}'")


def _run_recent(ctx, args) -> CommandResult:
    kinds = normalize_kinds(getattr(args, "kinds", None))
    return CommandResult(
        command="report-recent",
        payload={
            "limit": args.limit,
            "kinds": sorted(kinds),
            "items": recent_activity(ctx.config, limit=args.limit, kinds=kinds),
        },
    )


def _run_open_alias(ctx, target: list[str]) -> CommandResult:
    scope, value = _parse_scoped_target(target, default_scope="auto")
    if scope == "auto":
        return _run_auto_note(ctx, value)
    if scope == "task":
        return _run_note(ctx, value)
    if scope == "chain":
        return _run_chain(ctx, value)
    if scope == "project":
        return _run_project(ctx, value)
    raise RuntimeError(f"unknown open scope '{scope}'")


def _run_cat_alias(ctx, target: list[str]) -> CommandResult:
    scope, value = _parse_scoped_target(target, default_scope="task")
    if scope == "task":
        return _run_task_cat(ctx, value)
    if scope == "chain":
        return _run_chain_cat(ctx, value)
    if scope == "project":
        return _run_project_cat(ctx, value)
    raise RuntimeError(f"unknown cat scope '{scope}'")


def _parse_scoped_target(parts: list[str], *, default_scope: str) -> tuple[str, str]:
    if not parts:
        raise RuntimeError("target is required")
    first = str(parts[0] or "").strip().casefold()
    scope_aliases = {
        "t": "task",
        "task": "task",
        "c": "chain",
        "ch": "chain",
        "chain": "chain",
        "p": "project",
        "proj": "project",
        "project": "project",
    }
    if first in scope_aliases:
        if len(parts) < 2:
            raise RuntimeError(f"{scope_aliases[first]} target is required")
        return scope_aliases[first], " ".join(parts[1:]).strip()
    return default_scope, " ".join(parts).strip()


def _run_chain(ctx, task_ref: str) -> CommandResult:
    task = ctx.taskwarrior.resolve_task(task_ref)
    note = ensure_chain_note(ctx.config, task)
    _open_note_in_editor(ctx, note.note_path)
    finalize_chain_note_edit(ctx.config, task, note)
    post_save_action = _offer_post_save_task_action(ctx, task)
    return CommandResult(
        command="chain",
        payload={
            "path": str(note.note_path),
            "opened": note.existed,
            "task_short_uuid": task.task_short_uuid,
            "post_save_action": post_save_action,
        },
    )


def _run_project(ctx, project_name: str) -> CommandResult:
    note = ensure_project_note(ctx.config, project_name)
    _open_note_in_editor(ctx, note.note_path)
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


def _run_project_report(ctx, project_name: str, limit: int) -> CommandResult:
    tasks = ctx.taskwarrior.list_tasks(limit=1000, status="pending")
    return CommandResult(
        command="project-report",
        payload=project_rollup(ctx.config, tasks, project_name, limit=limit),
    )


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


def _run_headings(ctx, args) -> CommandResult:
    note_path, identity = _existing_note_path_for_kind(ctx, args.note_kind, args.note_ref)
    result = list_note_headings(note_path)
    return CommandResult(
        command="headings",
        payload={
            "note_kind": args.note_kind,
            **identity,
            "path": str(result.note_path),
            "headings": result.headings,
        },
    )


def _run_section(ctx, args) -> CommandResult:
    note_path, identity = _existing_note_path_for_kind(ctx, args.note_kind, args.note_ref)
    result = read_note_section(note_path, args.heading, exact=bool(args.heading_exact))
    return CommandResult(
        command="section",
        payload={
            "note_kind": args.note_kind,
            **identity,
            "path": str(result.note_path),
            "heading": result.heading,
            "heading_match": result.match,
            "content": result.content,
        },
    )


def _existing_note_path_for_kind(ctx, note_kind: str, note_ref: str):
    if note_kind == "task":
        task = ctx.taskwarrior.resolve_task(note_ref)
        note_path = find_task_note(ctx.config, task)
        if note_path is None:
            raise RuntimeError(f"task note does not exist for {task.task_short_uuid}")
        return note_path, {"task_short_uuid": task.task_short_uuid}
    if note_kind == "chain":
        task = ctx.taskwarrior.resolve_task(note_ref)
        note_path = find_chain_note(ctx.config, task)
        if note_path is None:
            raise RuntimeError(f"chain note does not exist for {task.task_short_uuid}")
        return note_path, {
            "task_short_uuid": task.task_short_uuid,
            "chain_id": chain_id_for_task(task.task) or None,
        }
    project_name = str(note_ref).strip()
    note_path = find_project_note(ctx.config, project_name)
    if note_path is None:
        raise RuntimeError(f"project note does not exist for {project_name}")
    return note_path, {"project": project_name}


def _run_resources(ctx, args) -> CommandResult:
    note_path, identity = _existing_note_path_for_kind(ctx, args.note_kind, args.note_ref)
    result = list_note_resources(note_path)
    return CommandResult(
        command="resources",
        payload={
            "note_kind": args.note_kind,
            **identity,
            "path": str(result.note_path),
            "resources": result.resources,
        },
    )


def _run_attach(ctx, args) -> CommandResult:
    if args.note_kind == "task":
        task = ctx.taskwarrior.resolve_task(args.note_ref)
        result = attach_task_resource_storage(ctx.config, task, target=args.target, label=args.label)
        identity = {"task_short_uuid": task.task_short_uuid}
    elif args.note_kind == "chain":
        task = ctx.taskwarrior.resolve_task(args.note_ref)
        result = attach_chain_resource_storage(ctx.config, task, target=args.target, label=args.label)
        identity = {"task_short_uuid": task.task_short_uuid, "chain_id": chain_id_for_task(task.task) or None}
    else:
        project_name = str(args.note_ref).strip()
        result = attach_project_resource_storage(ctx.config, project_name, target=args.target, label=args.label)
        identity = {"project": project_name}
    return CommandResult(
        command="attach",
        payload={
            "note_kind": args.note_kind,
            **identity,
            "path": str(result["note_path"]),
            "opened": bool(result["opened"]),
            "resource": result["resource"],
            "resources": result["resources"],
        },
    )


def _run_open_resource(ctx, args) -> CommandResult:
    note_path, identity = _existing_note_path_for_kind(ctx, args.note_kind, args.note_ref)
    resources = list_note_resources(note_path).resources
    resource = next((item for item in resources if int(item.get("id") or 0) == args.resource_id), None)
    if resource is None:
        raise RuntimeError(f"resource {args.resource_id} not found")
    command = open_resource_target(str(resource.get("target") or ""))
    return CommandResult(
        command="open-resource",
        payload={
            "note_kind": args.note_kind,
            **identity,
            "path": str(note_path),
            "resource": resource,
            "opener": command,
        },
    )


def _run_detach_resource(ctx, args) -> CommandResult:
    note_path, identity = _existing_note_path_for_kind(ctx, args.note_kind, args.note_ref)
    if args.note_kind == "task":
        task = ctx.taskwarrior.resolve_task(args.note_ref)
        result = detach_task_resource_storage(ctx.config, task, note_path=note_path, resource_id=args.resource_id)
    elif args.note_kind == "chain":
        task = ctx.taskwarrior.resolve_task(args.note_ref)
        result = detach_chain_resource_storage(ctx.config, task, note_path=note_path, resource_id=args.resource_id)
    else:
        project_name = str(args.note_ref).strip()
        result = detach_project_resource_storage(
            ctx.config,
            project_name,
            note_path=note_path,
            resource_id=args.resource_id,
        )
    return CommandResult(
        command="detach-resource",
        payload={
            "note_kind": args.note_kind,
            **identity,
            "path": str(result["note_path"]),
            "resource": result["resource"],
            "resources": result["resources"],
        },
    )


def _run_progress(ctx, args) -> CommandResult:
    note_kind = str(args.note_kind)
    note_ref = str(args.note_ref).strip()
    operation = str(args.progress_command)
    track = getattr(args, "track", None)
    if operation == "show":
        note_refs = _progress_note_refs(note_ref)
        history_limit = int(getattr(args, "history", 5))
        if history_limit < 0:
            raise RuntimeError("--history must be 0 or greater")
        items: list[dict[str, object]] = []
        seen_paths: set[str] = set()
        for item_ref in note_refs:
            note_path, identity = _existing_note_path_for_kind(ctx, note_kind, item_ref)
            path_text = str(note_path)
            if path_text in seen_paths:
                continue
            seen_paths.add(path_text)
            result = read_note_progress(note_path, track or "default")
            analysis = read_note_progress_analysis(
                note_path,
                track=track,
                history_limit=history_limit,
            )
            items.append(
                {
                    "reference": item_ref,
                    **identity,
                    "path": path_text,
                    "progress": result.progress,
                    "track": track,
                    "tracks": list(result.tracks),
                    "history": analysis["history"],
                    "trends": analysis["trends"],
                }
            )
        if len(note_refs) > 1:
            return CommandResult(
                command="progress",
                payload={
                    "operation": operation,
                    "note_kind": note_kind,
                    "track": track,
                    "items": items,
                },
            )
        item = items[0]
        return CommandResult(
            command="progress",
            payload={
                "operation": operation,
                "note_kind": note_kind,
                **item,
                "entry": None,
            },
        )
    if operation == "clear" and not bool(args.yes):
        raise RuntimeError("progress clear requires --yes; history will be retained")

    current = target = amount = None
    unit = status = None
    if operation == "set":
        current, target = parse_progress_pair(args.measurement)
        unit = args.unit
        status = args.status
    elif operation in {"add", "subtract"}:
        amount = parse_progress_value(args.amount)
    elif operation == "status":
        status = args.value

    if note_kind in {"task", "chain"}:
        task = ctx.taskwarrior.resolve_task(note_ref)
        result = mutate_task_progress_storage(
            ctx.config,
            task,
            note_kind=note_kind,
            operation=operation,
            current=current,
            target=target,
            amount=amount,
            unit=unit,
            status=status,
            track=track,
        )
        identity = {
            "task_short_uuid": task.task_short_uuid,
            "chain_id": chain_id_for_task(task.task) if note_kind == "chain" else None,
        }
    else:
        result = mutate_project_progress_storage(
            ctx.config,
            note_ref,
            operation=operation,
            current=current,
            target=target,
            amount=amount,
            unit=unit,
            status=status,
            track=track,
        )
        identity = {"project": note_ref}
    return CommandResult(
        command="progress",
        payload={
            "operation": operation,
            "note_kind": note_kind,
            **identity,
            "path": str(result["note_path"]),
            "progress": result["progress"],
            "track": result["track"],
            "tracks": result["tracks"],
            "entry": result["entry"],
        },
    )


def _progress_note_refs(value: str) -> list[str]:
    refs = [item.strip() for item in str(value or "").split(",")]
    if not refs or any(not item for item in refs):
        raise RuntimeError("progress references must be a comma-separated list without empty items")
    return refs


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


def _run_timelog(ctx, args) -> CommandResult:
    if args.timelog_command == "start":
        task = ctx.taskwarrior.resolve_task(args.task_ref)
        return CommandResult(
            command="timelog-start",
            payload=start_time_session(ctx.config, task, started_at=args.at),
        )
    if args.timelog_command == "stop":
        if args.all:
            if args.task_ref:
                raise RuntimeError("timelog stop --all does not accept a task reference")
            return CommandResult(
                command="timelog-stop-all",
                payload=stop_all_time_sessions(ctx.config, ctx.taskwarrior, stopped_at=args.at, scope=args.scope),
            )
        if not args.task_ref:
            raise RuntimeError("timelog stop requires a task reference or --all")
        task = ctx.taskwarrior.resolve_task(args.task_ref)
        return CommandResult(
            command="timelog-stop",
            payload=stop_time_session(ctx.config, task, stopped_at=args.at, scope=args.scope),
        )
    if args.timelog_command == "pending":
        return CommandResult(
            command="timelog-pending",
            payload={"sessions": list_time_sessions(ctx.config)},
        )
    if args.timelog_command == "cancel":
        task = ctx.taskwarrior.resolve_task(args.task_ref)
        return CommandResult(
            command="timelog-cancel",
            payload=cancel_time_session(ctx.config, task),
        )
    if args.timelog_command == "report":
        return CommandResult(
            command="timelog-report",
            payload=report_time_logs(
                ctx.config,
                period=args.period,
                project=args.project,
                task_ref=args.task,
                chain_id=args.chain,
            ),
        )
    if args.timelog_command != "ingest":
        raise RuntimeError(f"unknown timelog command '{args.timelog_command}'")
    old_line = sys.stdin.readline()
    new_line = sys.stdin.readline()
    if not old_line or not new_line:
        raise RuntimeError("timelog ingest requires two JSON lines on stdin")
    import json

    try:
        old = json.loads(old_line)
        new = json.loads(new_line)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid hook JSON: {exc}") from exc
    return CommandResult(
        command="timelog-ingest",
        payload=ingest_time_log(
            ctx.config,
            old,
            new,
            scope=args.scope,
            stopped_at=args.stopped_at,
        ),
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
