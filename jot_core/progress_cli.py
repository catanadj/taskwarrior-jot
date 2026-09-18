from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .contracts import ProgressRequest
from .models import CommandResult, ProgressMutationCommandResult, ProgressShowItem, ProgressShowResult
from .nautical import chain_id_for_task
from .progress import (
    parse_progress_pair,
    parse_progress_value,
    read_note_progress,
    read_note_progress_analysis,
)
from .storage import mutate_project_progress_storage, mutate_task_progress_storage


NotePathResolver = Callable[[Any, str, str], tuple[Path, dict[str, Any]]]


def run_progress(ctx: Any, args: Any, resolve_note_path: NotePathResolver) -> CommandResult:
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
            note_path, identity = resolve_note_path(ctx, note_kind, item_ref)
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
                data=ProgressShowResult(
                    note_kind=note_kind,
                    track=track,
                    items=tuple(ProgressShowItem.from_mapping(item) for item in items),
                ),
            )
        return CommandResult(
            command="progress",
            data=ProgressShowResult(
                note_kind=note_kind,
                track=track,
                item=ProgressShowItem.from_mapping(items[0]),
            ),
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

    request = ProgressRequest(
        kind=note_kind,
        reference=note_ref,
        operation=operation,
        value=(
            args.measurement
            if operation == "set"
            else args.amount
            if operation in {"add", "subtract"}
            else args.value
            if operation == "status"
            else ""
        ),
        unit=unit,
        status=status,
        track=track or "default",
        confirm_clear=bool(getattr(args, "yes", False)),
    )
    note_kind = request.kind
    note_ref = request.reference
    operation = request.operation
    # Keep an omitted track as None so storage can infer a sole named track.
    track = request.track if track is not None else None

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
        data=ProgressMutationCommandResult(
            operation=operation,
            note_kind=note_kind,
            identity=identity,
            result=result,
        ),
    )


def _progress_note_refs(value: str) -> list[str]:
    refs = [item.strip() for item in str(value or "").split(",")]
    if not refs or any(not item for item in refs):
        raise RuntimeError("progress references must be a comma-separated list without empty items")
    return refs
