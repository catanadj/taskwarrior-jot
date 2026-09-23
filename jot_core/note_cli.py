"""CLI orchestration for note and project read commands."""

from __future__ import annotations

from pathlib import Path

from .date_filter import NoteDateFilter
from .models import (
    CommandResult,
    NoteContentResult,
    NoteSummary,
    NotesCommandResult,
    NoteOpenResult,
    NoteSectionResult,
    NoteHeadingsResult,
    ProjectListItem,
    ProjectListResult,
    ProjectShowResult,
    RecentReport,
)
from .nautical import chain_id_for_task
from .notes import (
    chain_note_path,
    find_chain_note,
    find_project_note,
    find_task_note,
    list_note_headings,
    project_note_path,
    read_note_section,
    task_note_path,
)
from .report import (
    list_notes,
    list_project_notes,
    normalize_note_kinds,
    project_rollup,
    recent_activity,
)
from .frontmatter import read_document
from .search import normalize_kinds


def parse_scoped_target(parts: list[str], *, default_scope: str) -> tuple[str, str]:
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


def run_project_list(ctx) -> CommandResult:
    return CommandResult(
        command="project-list",
        data=ProjectListResult(
            projects=tuple(ProjectListItem.from_mapping(item) for item in list_project_notes(ctx.config)),
        ),
    )


def run_notes(ctx, args) -> CommandResult:
    return _run_notes(ctx, args, command="notes")


def run_all_notes(ctx, *, date_filter: NoteDateFilter | None = None) -> CommandResult:
    return _run_notes(ctx, None, command="list", date_filter=date_filter)


def _run_notes(
    ctx,
    args,
    *,
    command: str,
    date_filter: NoteDateFilter | None = None,
) -> CommandResult:
    kinds = normalize_note_kinds(getattr(args, "kinds", None) if args is not None else None)
    project = getattr(args, "project", None) if args is not None else None
    return CommandResult(
        command=command,
        data=NotesCommandResult(
            kinds=tuple(sorted(kinds or {"task-note", "chain-note", "project-note"})),
            project=project,
            notes=tuple(
                NoteSummary.from_mapping(item)
                for item in list_notes(
                    ctx.config,
                    kinds=kinds,
                    project=project,
                    date_filter=date_filter,
                )
            ),
            date_filter=date_filter.to_payload() if date_filter else None,
        ),
    )


def run_recent(ctx, args) -> CommandResult:
    kinds = normalize_kinds(getattr(args, "kinds", None))
    return CommandResult(
        command="report-recent",
        data=RecentReport(
            limit=args.limit,
            kinds=tuple(sorted(kinds)),
            items=tuple(recent_activity(ctx.config, limit=args.limit, kinds=kinds)),
        ),
    )


def run_project_show(ctx, project_name: str) -> CommandResult:
    note_path = find_project_note(ctx.config, project_name)
    note_summary = project_note_summary(ctx, project_name)
    if note_path is None:
        return CommandResult(
            command="project-show",
            data=ProjectShowResult(kind="project-summary", project=project_name, note=note_summary),
        )

    metadata, body = read_document(note_path)
    return CommandResult(
        command="project-show",
        data=ProjectShowResult(
            kind="project-summary",
            project=project_name,
            note={
                **note_summary,
                "created": metadata.get("created"),
                "updated": metadata.get("updated"),
                "project_path": metadata.get("project_path") or [],
                "preview": body_preview(body),
            },
        ),
    )


def run_project_cat(ctx, project_name: str) -> CommandResult:
    note_path = find_project_note(ctx.config, project_name)
    if note_path is None:
        raise RuntimeError(f"project note does not exist for {project_name}")
    return cat_result("project-cat", note_path, project=project_name)


def run_project_report(ctx, project_name: str, limit: int, timelog_period: str) -> CommandResult:
    tasks = ctx.taskwarrior.list_tasks(limit=1000, status="pending")
    return CommandResult(
        command="project-report",
        data=project_rollup(ctx.config, tasks, project_name, limit=limit, timelog_period=timelog_period),
    )


def run_task_cat(ctx, task_ref: str) -> CommandResult:
    task = ctx.taskwarrior.resolve_task(task_ref)
    note_path = find_task_note(ctx.config, task)
    if note_path is None:
        raise RuntimeError(f"task note does not exist for {task.task_short_uuid}")
    return cat_result("task-cat", note_path, task_short_uuid=task.task_short_uuid)


def run_chain_cat(ctx, task_ref: str) -> CommandResult:
    task = ctx.taskwarrior.resolve_task(task_ref)
    note_path = find_chain_note(ctx.config, task)
    if note_path is None:
        raise RuntimeError(f"chain note does not exist for {task.task_short_uuid}")
    return cat_result("chain-cat", note_path, task_short_uuid=task.task_short_uuid)


def existing_note_path_for_kind(ctx, note_kind: str, note_ref: str):
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


def run_headings(ctx, args) -> CommandResult:
    note_path, identity = existing_note_path_for_kind(ctx, args.note_kind, args.note_ref)
    result = list_note_headings(note_path)
    return CommandResult(
        command="headings",
        data=NoteHeadingsResult(
            note_kind=args.note_kind,
            path=result.note_path,
            headings=tuple(result.headings),
            identity=identity,
        ),
    )


def run_section(ctx, args) -> CommandResult:
    note_path, identity = existing_note_path_for_kind(ctx, args.note_kind, args.note_ref)
    result = read_note_section(note_path, args.heading, exact=bool(args.heading_exact))
    return CommandResult(
        command="section",
        data=NoteSectionResult(
            note_kind=args.note_kind,
            path=result.note_path,
            heading=result.heading,
            heading_match=result.match,
            content=result.content,
            identity=identity,
        ),
    )


def body_preview(body: str, width: int = 120) -> str:
    text = " ".join(str(body or "").split())
    if len(text) <= width:
        return text
    return text[: width - 3].rstrip() + "..."


def cat_result(command: str, note_path: Path, **extra: str) -> CommandResult:
    metadata, body = read_document(note_path)
    return CommandResult(
        command=command,
        data=NoteContentResult(
            path=note_path,
            metadata=metadata,
            body=body,
            content=note_path.read_text(encoding="utf-8"),
            identity=extra,
        ),
    )


def task_note_summary(ctx, task) -> dict[str, object]:
    note_path = find_task_note(ctx.config, task)
    expected = task_note_path(ctx.config, task)
    return {"available": True, "exists": note_path is not None, "path": str(note_path or expected)}


def chain_note_summary(ctx, task) -> dict[str, object]:
    chain_id = chain_id_for_task(task.task)
    if not chain_id:
        return {"available": False, "exists": False, "path": None}
    note_path = find_chain_note(ctx.config, task)
    expected = chain_note_path(ctx.config, chain_id, task.description or chain_id)
    return {"available": True, "exists": note_path is not None, "path": str(note_path or expected)}


def project_note_summary(ctx, project_name: str | None) -> dict[str, object]:
    normalized = str(project_name or "").strip()
    if not normalized:
        return {"available": False, "exists": False, "path": None}
    note_path = find_project_note(ctx.config, normalized)
    expected = project_note_path(ctx.config, normalized)
    return {"available": True, "exists": note_path is not None, "path": str(note_path or expected)}
