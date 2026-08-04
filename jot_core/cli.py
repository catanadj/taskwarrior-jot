from __future__ import annotations

import argparse
from datetime import datetime, timezone
import difflib
import os
import shutil
import sys
import textwrap
from pathlib import Path

from . import __version__
from .app import build_app_context
from .command_help import build_command_catalog
from .command_prefix import AmbiguousCommandPrefix, expand_command_prefixes
from .config import ensure_app_dirs
from .doctor import run_doctor, run_doctor_config_error
from .editor import colorize_diff, note_diff, open_in_editor
from .events import collect_event_text, format_event_text, validate_event_type
from .frontmatter import atomic_write_text, exclusive_file_lock, parse_document, read_document
from .index import rebuild_index, read_index_status, save_index
from .migrations import migrate_notes
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
    NoteIdentityConflictError,
    project_note_path,
    read_note_section,
    task_note_path,
)
from .ops import iso_now, read_ops
from .output import configure_output, emit_result, style_text, warn
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
    add_time_log,
    amend_time_log,
    cancel_time_session,
    delete_time_log,
    ingest_time_log,
    list_deleted_time_logs,
    list_time_sessions,
    report_time_logs,
    restore_deleted_time_log,
    stop_all_time_sessions,
    start_time_session,
    stop_time_session,
)
from .timewarrior import (
    clear_timewarrior_tags,
    inherit_timewarrior_tags,
    resolve_timewarrior_tags,
    set_timewarrior_tags,
)
from .trash import cleanup_trash, list_trash, restore_trash_item


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
            "  jot cleanup --trash-older-than 365 --yes\n"
            "  jot migrate --dry-run\n"
            "  jot stats\n"
            "  jot paths\n"
            "  jot timew set chain 42 deep-work client-a\n"
            "  jot timew show 42\n"
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

    doctor = subparsers.add_parser(
        "doctor",
        help="check configuration, storage paths, and Taskwarrior availability",
        description="Validate jot configuration, storage paths, and Taskwarrior access.",
    )
    doctor.add_argument(
        "--repair",
        action="store_true",
        help="repair stale locks, migrate safe notes, and rebuild the index",
    )
    migrate = subparsers.add_parser(
        "migrate",
        help="upgrade note metadata to the current schema",
        description="Inspect and upgrade Jot note metadata, backing up every changed note first.",
    )
    migrate.add_argument(
        "--dry-run",
        action="store_true",
        help="show planned and blocked migrations without changing files",
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
    cleanup = subparsers.add_parser(
        "cleanup",
        help="permanently remove old items from jot trash",
        description="Preview or permanently remove trashed notes and timelog archives older than the selected age.",
    )
    cleanup.add_argument(
        "--trash-older-than",
        type=int,
        default=365,
        metavar="DAYS",
        help="select trash items older than DAYS (default: 365)",
    )
    cleanup.add_argument(
        "--yes",
        action="store_true",
        help="permanently remove the selected items; without this flag, only preview",
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
    project_report.add_argument(
        "--timelog-period",
        choices=("all", "today", "week", "month"),
        default="week",
        help="time window for the project time summary (default: week)",
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
    timelog_add = timelog_subparsers.add_parser(
        "add",
        help="add a completed time interval manually",
        description="Add a completed interval using local time unless an explicit timezone is supplied.",
    )
    timelog_add.add_argument("task_ref", help="task ID, full UUID, or unique short UUID")
    timelog_add.add_argument("--from", dest="started_at", required=True, help="interval start datetime")
    timelog_add.add_argument("--to", dest="stopped_at", required=True, help="interval stop datetime")
    timelog_add.add_argument(
        "--scope",
        choices=("auto", "task", "chain"),
        default="auto",
        help="write to chain notes when chainID exists, otherwise task notes",
    )
    timelog_amend = timelog_subparsers.add_parser(
        "amend",
        help="correct an existing interval by its key",
        description="Replace one interval and archive its original record. Unique key prefixes are accepted.",
    )
    timelog_amend.add_argument("key", help="full timelog key or unique prefix of at least 4 characters")
    timelog_amend.add_argument("--from", dest="started_at", default="", help="replacement start datetime")
    timelog_amend.add_argument("--to", dest="stopped_at", default="", help="replacement stop datetime")
    timelog_delete = timelog_subparsers.add_parser(
        "delete",
        help="archive and remove an existing interval",
        description="Remove one interval after archiving its original record. Unique key prefixes are accepted.",
    )
    timelog_delete.add_argument("key", help="full timelog key or unique prefix of at least 4 characters")
    timelog_delete.add_argument("--yes", action="store_true", help="confirm removal of the interval")
    timelog_subparsers.add_parser(
        "trash",
        help="list deleted intervals available for restoration",
        description="List deletion archives that have not already been restored.",
    )
    timelog_restore = timelog_subparsers.add_parser(
        "restore",
        help="restore a deleted interval from its archive",
        description="Restore an archived interval by unique key prefix or the #ID shown by timelog trash.",
    )
    timelog_restore.add_argument("reference", help="full key, unique key prefix, or trash ID such as #1")
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
        help="local time window; intervals are clipped to its boundaries",
    )
    timelog_report.add_argument("--project", default="", help="only include entries for this project")
    timelog_report.add_argument("--task", default="", help="only include entries for this task UUID or short UUID")
    timelog_report.add_argument("--chain", default="", help="only include entries for this chainID")
    timelog_report.add_argument("--since", default="", help="inclusive local date or ISO datetime boundary")
    timelog_report.add_argument("--until", default="", help="inclusive local date or exclusive ISO datetime boundary")
    timelog_report.add_argument("--details", action="store_true", help="show individual time log entries")
    timelog_report.add_argument("--csv", action="store_true", help="write detailed entries as CSV")

    timew = subparsers.add_parser(
        "timew",
        help="manage note-based Timewarrior tags",
        description=(
            "Store Timewarrior tags in task, chain, or project note metadata and show the effective tags for a task."
        ),
    )
    timew_subparsers = timew.add_subparsers(dest="timew_command", required=True)
    timew_set = timew_subparsers.add_parser(
        "set",
        help="set Timewarrior tags on a note",
        description="Set one or more Timewarrior tags on a task, chain, or project note.",
    )
    timew_set.add_argument("note_kind", choices=("task", "chain", "project"), help="target note kind")
    timew_set.add_argument("note_ref", help="task ref for task/chain or exact project name")
    timew_set.add_argument("tags", nargs="+", help="one or more Timewarrior tags")

    timew_clear = timew_subparsers.add_parser(
        "clear",
        help="disable inherited Timewarrior tags on a note",
        description="Store an explicit empty tag list so lower-priority chain or project tags are not inherited.",
    )
    timew_clear.add_argument("note_kind", choices=("task", "chain", "project"), help="target note kind")
    timew_clear.add_argument("note_ref", help="task ref for task/chain or exact project name")

    timew_inherit = timew_subparsers.add_parser(
        "inherit",
        help="resume inherited Timewarrior tags",
        description="Remove the local tag setting so Jot can use chain or project metadata again.",
    )
    timew_inherit.add_argument("note_kind", choices=("task", "chain", "project"), help="target note kind")
    timew_inherit.add_argument("note_ref", help="task ref for task/chain or exact project name")

    timew_show = timew_subparsers.add_parser(
        "show",
        help="show effective Timewarrior tags for a task",
        description="Resolve task, chain, and nearest-project note metadata and show the first applicable tag setting.",
    )
    timew_show.add_argument("task_ref", help="task ID, full UUID, or unique short UUID")

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
            configure_output(color_mode=ctx.config.color_mode)
            result = _run_auto_note(ctx, shorthand_ref)
        except NoteIdentityConflictError as exc:
            _handle_note_identity_conflict(exc, ctx, color_mode=ctx.config.color_mode)
            return 1
        except RuntimeError as exc:
            warn(str(exc))
            return 1
        except Exception as exc:
            warn(str(exc))
            return 1
        emit_result(
            result,
            json_mode=shorthand_json or ctx.config.default_format == "json",
        )
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
        configure_output(color_mode=ctx.config.color_mode)
    except Exception as exc:
        if args.command == "doctor":
            emit_result(run_doctor_config_error(f"failed to load config: {exc}"), json_mode=args.json)
            return 1
        warn(str(exc))
        return 1

    try:
        if args.command == "doctor":
            result = run_doctor(ctx.config, ctx.taskwarrior, repair=bool(args.repair))
        elif args.command == "migrate":
            result = CommandResult(
                command="migrate",
                payload=migrate_notes(ctx.config, dry_run=bool(args.dry_run)),
            )
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
        elif args.command == "cleanup":
            result = CommandResult(
                command="cleanup",
                payload=cleanup_trash(
                    ctx.config,
                    older_than_days=args.trash_older_than,
                    apply=bool(args.yes),
                ),
            )
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
            result = _run_project_report(ctx, args.project_name, args.limit, args.timelog_period)
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
        elif args.command == "timew":
            result = _run_timewarrior(ctx, args)
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
    except NoteIdentityConflictError as exc:
        _handle_note_identity_conflict(exc, ctx, color_mode=ctx.config.color_mode)
        return 1
    except (RuntimeError, OSError, ValueError, TypeError) as exc:
        warn(str(exc))
        return 1

    emit_result(result, json_mode=args.json or ctx.config.default_format == "json")
    if result.command == "doctor":
        failed = [
            item
            for item in result.payload.get("checks") or []
            if not item.get("ok") and str(item.get("severity") or "error") != "warning"
        ]
        if failed:
            return 1
    if result.command == "migrate" and result.payload.get("blocked"):
        return 1
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


def _handle_note_identity_conflict(
    error: NoteIdentityConflictError,
    ctx,
    *,
    color_mode: str = "auto",
) -> None:
    warn(str(error))
    if len(error.candidates) < 2:
        return
    base = error.candidates[0]
    try:
        before = base.read_text(encoding="utf-8")
    except OSError as exc:
        warn(f"could not read conflict candidate {base}: {exc}")
        return
    secondary = error.candidates[1]
    try:
        after = secondary.read_text(encoding="utf-8")
    except OSError as exc:
        warn(f"could not read conflict candidate {secondary}: {exc}")
        return

    automatic = _automatic_note_merge(before, after)
    if automatic is not None:
        if _commit_merged_note(error, ctx, before=before, merged=automatic):
            return
    sys.stderr.write("Automatic merge was not safe for these changes; manual merge is required.\n")

    if len(error.candidates) != 2:
        return
    if not sys.stdin.isatty():
        return
    while True:
        sys.stderr.write(
            "Conflict options: [s] side-by-side resolver  [d] unified diff  "
            "[m] marker editor  [enter] abort\nChoice: "
        )
        sys.stderr.flush()
        choice = sys.stdin.readline().strip().casefold()
        if choice == "s":
            merged = _resolve_note_conflict_side_by_side(error, ctx, before=before, after=after)
            if merged is not None:
                _commit_merged_note(error, ctx, before=before, merged=merged)
            return
        if choice == "d":
            diff = note_diff(before, after, path=secondary)
            if not diff:
                sys.stderr.write(f"No differences between {base} and {secondary}\n")
            else:
                sys.stderr.write(colorize_diff(diff, color_mode=color_mode))
            continue
        if choice == "m":
            _merge_note_identity_conflict(
                error,
                ctx,
                before=before,
                after=after,
                color_mode=color_mode,
            )
        return


def _resolve_note_conflict_side_by_side(
    error: NoteIdentityConflictError,
    ctx,
    *,
    before: str,
    after: str,
) -> str | None:
    base, secondary = error.candidates
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    opcodes = difflib.SequenceMatcher(
        a=before_lines,
        b=after_lines,
        autojunk=False,
    ).get_opcodes()
    changed = [opcode for opcode in opcodes if opcode[0] != "equal"]
    merged: list[str] = []
    hunk_number = 0
    for tag, i1, i2, j1, j2 in opcodes:
        left = before_lines[i1:i2]
        right = after_lines[j1:j2]
        if tag == "equal":
            merged.extend(left)
            continue
        hunk_number += 1
        in_frontmatter = _hunk_is_frontmatter(before_lines, after_lines, i1, j1)
        while True:
            _write_side_by_side_hunk(
                base,
                secondary,
                left,
                right,
                left_start=i1 + 1,
                right_start=j1 + 1,
                number=hunk_number,
                total=len(changed),
            )
            options = "[1] current  [2] conflict"
            if not in_frontmatter:
                options += "  [b] both"
            options += "  [e] edit  [q] abort"
            sys.stderr.write(f"{options}\nChoice: ")
            sys.stderr.flush()
            choice = sys.stdin.readline().strip().casefold()
            if choice == "1":
                merged.extend(left)
                break
            if choice == "2":
                merged.extend(right)
                break
            if choice == "b" and not in_frontmatter:
                merged.extend(left)
                merged.extend(line for line in right if line not in left)
                break
            if choice == "e":
                edited = _edit_conflict_hunk(
                    base,
                    secondary,
                    ctx,
                    left=left,
                    right=right,
                    number=hunk_number,
                )
                if edited is not None:
                    merged.extend(edited)
                    break
                continue
            if choice in {"q", "", "abort"}:
                sys.stderr.write("Merge aborted; both notes were left unchanged.\n")
                return None
            sys.stderr.write("Choose one of the listed actions.\n")

    result = _join_merged_lines(merged, before, after)
    try:
        parse_document(result)
    except RuntimeError as exc:
        warn(f"resolved note is invalid: {exc}")
        return None
    sys.stderr.write(f"Resolved {len(changed)} changed block(s). Save merged note? [y/N] ")
    sys.stderr.flush()
    if sys.stdin.readline().strip().casefold() not in {"y", "yes"}:
        sys.stderr.write("Merge aborted; both notes were left unchanged.\n")
        return None
    return result


def _write_side_by_side_hunk(
    base: Path,
    secondary: Path,
    left: list[str],
    right: list[str],
    *,
    left_start: int,
    right_start: int,
    number: int,
    total: int,
) -> None:
    terminal_width = min(180, max(80, shutil.get_terminal_size((120, 24)).columns))
    column_width = max(24, (terminal_width - 15) // 2)
    divider = " | "
    sys.stderr.write(f"\nChange {number}/{total}\n")
    left_title = f"CURRENT: {base.name}"[:column_width]
    right_title = f"CONFLICT: {secondary.name}"[:column_width]
    sys.stderr.write(f"     {left_title:<{column_width}}{divider}     {right_title:<{column_width}}\n")
    sys.stderr.write(f"     {'-' * column_width}{divider}     {'-' * column_width}\n")
    count = max(len(left), len(right), 1)
    for index in range(count):
        left_line = left[index] if index < len(left) else ""
        right_line = right[index] if index < len(right) else ""
        left_parts = _wrap_conflict_line(left_line, column_width)
        right_parts = _wrap_conflict_line(right_line, column_width)
        wrapped_count = max(len(left_parts), len(right_parts))
        for wrapped_index in range(wrapped_count):
            left_part = left_parts[wrapped_index] if wrapped_index < len(left_parts) else ""
            right_part = right_parts[wrapped_index] if wrapped_index < len(right_parts) else ""
            left_number = str(left_start + index) if index < len(left) and wrapped_index == 0 else ""
            right_number = str(right_start + index) if index < len(right) and wrapped_index == 0 else ""
            left_cell = f"{left_number:>4} {left_part:<{column_width}}"
            right_cell = f"{right_number:>4} {right_part:<{column_width}}"
            left_cell = style_text(left_cell, role="error", stream=sys.stderr)
            right_cell = style_text(right_cell, role="success", stream=sys.stderr)
            sys.stderr.write(f"{left_cell}{divider}{right_cell}\n")


def _wrap_conflict_line(line: str, width: int) -> list[str]:
    return textwrap.wrap(
        line,
        width=width,
        replace_whitespace=False,
        drop_whitespace=False,
        break_long_words=True,
        break_on_hyphens=False,
    ) or [""]


def _hunk_is_frontmatter(
    before_lines: list[str],
    after_lines: list[str],
    before_index: int,
    after_index: int,
) -> bool:
    return (
        0 <= _frontmatter_end(before_lines) >= before_index
        or 0 <= _frontmatter_end(after_lines) >= after_index
    )


def _frontmatter_end(lines: list[str]) -> int:
    if not lines or lines[0].strip() != "---":
        return -1
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return index
    return -1


def _edit_conflict_hunk(
    base: Path,
    secondary: Path,
    ctx,
    *,
    left: list[str],
    right: list[str],
    number: int,
) -> list[str] | None:
    edit_path = base.with_name(f".{base.name}.hunk-{number}-{os.getpid()}.tmp")
    left_text = "\n".join(left)
    right_text = "\n".join(right)
    content = (
        f"<<<<<<< {base.name}\n"
        f"{left_text}\n"
        f"=======\n"
        f"{right_text}\n"
        f">>>>>>> {secondary.name}\n"
    )
    atomic_write_text(edit_path, content)
    try:
        open_in_editor(
            edit_path,
            ctx.config.editor_command,
            show_diff=False,
            color_mode=ctx.config.editor_diff_color,
        )
        edited = edit_path.read_text(encoding="utf-8")
        if any(
            line.startswith(("<<<<<<<", "=======", ">>>>>>>"))
            for line in edited.splitlines()
        ):
            warn(f"edited block still contains conflict markers: {edit_path}")
            return None
        edit_path.unlink(missing_ok=True)
        return edited.splitlines()
    except Exception:
        raise


def _automatic_note_merge(before: str, after: str) -> str | None:
    if before == after:
        return before
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    opcodes = difflib.SequenceMatcher(
        a=before_lines,
        b=after_lines,
        autojunk=False,
    ).get_opcodes()
    tags = {tag for tag, *_rest in opcodes}
    if tags <= {"equal", "insert"}:
        return after
    if tags <= {"equal", "delete"}:
        return before

    prefix = 0
    while prefix < len(before_lines) and prefix < len(after_lines):
        if before_lines[prefix] != after_lines[prefix]:
            break
        prefix += 1
    before_tail = before_lines[prefix:]
    after_tail = after_lines[prefix:]
    if (
        prefix >= 2
        and before_tail
        and after_tail
        and all(_looks_like_note_entry(line) for line in (*before_tail, *after_tail))
    ):
        merged = [*before_lines]
        merged.extend(line for line in after_tail if line not in before_tail)
        return _join_merged_lines(merged, before, after)
    return None


def _looks_like_note_entry(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith(("- ", "* "))


def _join_merged_lines(lines: list[str], before: str, after: str) -> str:
    result = "\n".join(lines)
    if before.endswith("\n") or after.endswith("\n"):
        result += "\n"
    return result


def _merge_note_identity_conflict(
    error: NoteIdentityConflictError,
    ctx,
    *,
    before: str,
    after: str,
    color_mode: str,
) -> None:
    base, secondary = error.candidates
    merge_path = base.with_name(f".{base.name}.merge-{os.getpid()}.tmp")
    merge_text = (
        f"<<<<<<< {base.name}\n"
        f"{before.rstrip(chr(10))}\n"
        f"=======\n"
        f"{after.rstrip(chr(10))}\n"
        f">>>>>>> {secondary.name}\n"
    )
    atomic_write_text(merge_path, merge_text)
    keep_merge_file = False
    try:
        open_in_editor(
            merge_path,
            ctx.config.editor_command,
            show_diff=False,
            color_mode=color_mode,
        )
        merged = merge_path.read_text(encoding="utf-8")
        if any(
            line.startswith(("<<<<<<<", "=======", ">>>>>>>"))
            for line in merged.splitlines()
        ):
            keep_merge_file = True
            warn(f"merge still contains conflict markers; resolve and save {merge_path}")
            return

        if _commit_merged_note(error, ctx, before=before, merged=merged):
            return
    finally:
        if not keep_merge_file:
            merge_path.unlink(missing_ok=True)


def _commit_merged_note(
    error: NoteIdentityConflictError,
    ctx,
    *,
    before: str,
    merged: str,
) -> bool:
    base, secondary = error.candidates
    with exclusive_file_lock(base):
        current = base.read_text(encoding="utf-8") if base.exists() else ""
        if current != before:
            warn(f"primary note changed during merge; retry the conflict resolution")
            return False
        if not secondary.exists():
            warn(f"secondary note disappeared during merge; retry the conflict resolution")
            return False
        archive_path = _merged_conflict_archive_path(ctx.config, secondary)
        with exclusive_file_lock(secondary):
            archive_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(secondary), str(archive_path))
        atomic_write_text(base, merged)
    sys.stderr.write(f"Merged note saved to {base}\n")
    sys.stderr.write(f"Secondary note preserved at {archive_path}\n")
    return True


def _merged_conflict_archive_path(config, secondary: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory = config.trash_dir / "merged-conflicts" / stamp
    candidate = directory / secondary.name
    counter = 1
    while candidate.exists():
        candidate = directory / f"{secondary.stem}-{counter}{secondary.suffix}"
        counter += 1
    return candidate


def _offer_post_save_task_action(ctx, task) -> dict | None:
    if not ctx.config.editor_post_save_actions or not sys.stdin.isatty():
        return None

    title = style_text("Post-save actions", role="title", bold=True, stream=sys.stderr)
    task_label = style_text("Task", role="label", bold=True, stream=sys.stderr)
    task_id = style_text(
        task.task_short_uuid,
        role="identity",
        bold=True,
        stream=sys.stderr,
    )
    complete_key = style_text("c", role="success", bold=True, stream=sys.stderr)
    enter_key = style_text("enter", role="muted", bold=True, stream=sys.stderr)
    action_label = style_text("Action", role="label", bold=True, stream=sys.stderr)
    sys.stderr.write(f"\n{title}\n")
    sys.stderr.write(f"{task_label}: {task_id}  {task.description}\n")
    sys.stderr.write(f"  {complete_key}  complete task\n")
    sys.stderr.write(f"  {enter_key}  do nothing\n")
    sys.stderr.write(f"{action_label}: ")
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
    if ctx.config.nautical_enabled and chain_id_for_task(task.task):
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


def _run_project_report(ctx, project_name: str, limit: int, timelog_period: str) -> CommandResult:
    tasks = ctx.taskwarrior.list_tasks(limit=1000, status="pending")
    return CommandResult(
        command="project-report",
        payload=project_rollup(
            ctx.config,
            tasks,
            project_name,
            limit=limit,
            timelog_period=timelog_period,
        ),
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
        payload = start_time_session(ctx.config, task, started_at=args.at)
        timewarrior = payload.get("timewarrior")
        if isinstance(timewarrior, dict) and timewarrior.get("error"):
            warn(f"Timewarrior: {timewarrior['error']}")
        return CommandResult(
            command="timelog-start",
            payload=payload,
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
    if args.timelog_command == "add":
        task = ctx.taskwarrior.resolve_task(args.task_ref)
        return CommandResult(
            command="timelog-add",
            payload=add_time_log(
                ctx.config,
                task,
                started_at=args.started_at,
                stopped_at=args.stopped_at,
                scope=args.scope,
            ),
        )
    if args.timelog_command == "amend":
        return CommandResult(
            command="timelog-amend",
            payload=amend_time_log(
                ctx.config,
                args.key,
                started_at=args.started_at,
                stopped_at=args.stopped_at,
            ),
        )
    if args.timelog_command == "delete":
        if not args.yes:
            raise RuntimeError("timelog delete requires --yes")
        return CommandResult(
            command="timelog-delete",
            payload=delete_time_log(ctx.config, args.key),
        )
    if args.timelog_command == "trash":
        return CommandResult(
            command="timelog-trash",
            payload={"items": list_deleted_time_logs(ctx.config)},
        )
    if args.timelog_command == "restore":
        return CommandResult(
            command="timelog-restore",
            payload=restore_deleted_time_log(ctx.config, args.reference),
        )
    if args.timelog_command == "report":
        if args.csv and args.json:
            raise RuntimeError("timelog report --csv cannot be combined with --json")
        return CommandResult(
            command="timelog-report-csv" if args.csv else "timelog-report",
            payload=report_time_logs(
                ctx.config,
                period=args.period,
                project=args.project,
                task_ref=args.task,
                chain_id=args.chain,
                details=bool(args.details or args.csv),
                since=args.since,
                until=args.until,
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


def _run_timewarrior(ctx, args) -> CommandResult:
    if args.timew_command == "show":
        task = ctx.taskwarrior.resolve_task(args.task_ref)
        resolution = resolve_timewarrior_tags(ctx.config, task)
        return CommandResult(
            command="timew",
            payload={
                "operation": "show",
                "task_uuid": task.task_uuid,
                "task_short_uuid": task.task_short_uuid,
                "chain_id": chain_id_for_task(task.task) or None,
                "project": task.project or None,
                **resolution,
            },
        )

    scope = args.note_kind
    task = None
    reference = str(args.note_ref).strip()
    if scope in {"task", "chain"}:
        task = ctx.taskwarrior.resolve_task(reference)
        reference = task.task_short_uuid if scope == "task" else chain_id_for_task(task.task)
        if not reference:
            raise RuntimeError("task is not part of a Nautical chain")
    elif not reference:
        raise RuntimeError("project name is empty")

    common = {
        "scope": scope,
        "reference": reference,
        "task": task,
    }
    if args.timew_command == "set":
        payload = set_timewarrior_tags(ctx.config, tags=args.tags, **common)
    elif args.timew_command == "clear":
        payload = clear_timewarrior_tags(ctx.config, **common)
    elif args.timew_command == "inherit":
        payload = inherit_timewarrior_tags(ctx.config, **common)
    else:  # pragma: no cover
        raise RuntimeError(f"unknown timew command '{args.timew_command}'")
    return CommandResult(command="timew", payload=payload)


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
