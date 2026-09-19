from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .contracts import ResourceRequest
from .models import (
    CommandResult,
    ResourceCommandResult,
    ResourceListResult,
    ResourceOpenResult,
    ResourceRecord,
)
from .nautical import chain_id_for_task
from .notes import list_note_resources
from .resources import open_resource_target
from .storage import (
    attach_chain_resource_storage,
    attach_project_resource_storage,
    attach_task_resource_storage,
    detach_chain_resource_storage,
    detach_project_resource_storage,
    detach_task_resource_storage,
)


NotePathResolver = Callable[[Any, str, str], tuple[Path, dict[str, Any]]]


def run_resources(ctx: Any, args: Any, resolve_note_path: NotePathResolver) -> CommandResult:
    note_path, identity = resolve_note_path(ctx, args.note_kind, args.note_ref)
    result = list_note_resources(note_path)
    return CommandResult(
        command="resources",
        data=ResourceListResult(
            note_kind=args.note_kind,
            path=result.note_path,
            resources=tuple(ResourceRecord.from_mapping(item) for item in result.resources),
            identity=identity,
        ),
    )


def run_attach(ctx: Any, args: Any) -> CommandResult:
    request = ResourceRequest(
        kind=args.note_kind,
        reference=args.note_ref,
        target=args.target,
        label=args.label,
    )
    if request.kind == "task":
        task = ctx.taskwarrior.resolve_task(request.reference)
        result = attach_task_resource_storage(ctx.config, task, target=request.target, label=request.label)
        identity = {"task_short_uuid": task.task_short_uuid}
    elif request.kind == "chain":
        task = ctx.taskwarrior.resolve_task(request.reference)
        result = attach_chain_resource_storage(ctx.config, task, target=request.target, label=request.label)
        identity = {
            "task_short_uuid": task.task_short_uuid,
            "chain_id": chain_id_for_task(task.task) or None,
        }
    else:
        result = attach_project_resource_storage(
            ctx.config,
            request.reference,
            target=request.target,
            label=request.label,
        )
        identity = {"project": request.reference}
    return CommandResult(
        command="attach",
        data=ResourceCommandResult(
            note_kind=request.kind,
            path=result.note_path,
            opened=result.opened,
            resource=result.resource,
            resources=result.resources,
            identity=identity,
        ),
    )


def run_open_resource(ctx: Any, args: Any, resolve_note_path: NotePathResolver) -> CommandResult:
    note_path, identity = resolve_note_path(ctx, args.note_kind, args.note_ref)
    resources = list_note_resources(note_path).resources
    resource = next((item for item in resources if int(item.get("id") or 0) == args.resource_id), None)
    if resource is None:
        raise RuntimeError(f"resource {args.resource_id} not found")
    command = open_resource_target(str(resource.get("target") or ""))
    return CommandResult(
        command="open-resource",
        data=ResourceOpenResult(
            note_kind=args.note_kind,
            path=note_path,
            resource=ResourceRecord.from_mapping(resource),
            opener=tuple(command),
            identity=identity,
        ),
    )


def run_detach_resource(ctx: Any, args: Any, resolve_note_path: NotePathResolver) -> CommandResult:
    note_path, identity = resolve_note_path(ctx, args.note_kind, args.note_ref)
    request = ResourceRequest(
        kind=args.note_kind,
        reference=args.note_ref,
        resource_id=args.resource_id,
        note_path=str(note_path),
    )
    if request.kind == "task":
        task = ctx.taskwarrior.resolve_task(request.reference)
        result = detach_task_resource_storage(
            ctx.config,
            task,
            note_path=note_path,
            resource_id=request.resource_id,
        )
    elif request.kind == "chain":
        task = ctx.taskwarrior.resolve_task(request.reference)
        result = detach_chain_resource_storage(
            ctx.config,
            task,
            note_path=note_path,
            resource_id=request.resource_id,
        )
    else:
        result = detach_project_resource_storage(
            ctx.config,
            request.reference,
            note_path=note_path,
            resource_id=request.resource_id,
        )
    return CommandResult(
        command="detach-resource",
        data=ResourceCommandResult(
            note_kind=request.kind,
            path=result.note_path,
            resource=result.resource,
            resources=result.resources,
            identity=identity,
        ),
    )
