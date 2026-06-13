from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from .index import (
    update_chain_note_index,
    update_project_note_index,
    update_task_event_index,
    update_task_note_index,
    remove_chain_note_index,
    remove_project_note_index,
    remove_task_note_index,
)
from .models import AppConfig, AppendResult, NotePaths, ResolvedTask
from .nautical import chain_id_for_task
from .notes import (
    attach_note_resource,
    delete_chain_note,
    delete_project_note,
    delete_task_note,
    detach_note_resource,
    add_to_chain_heading,
    add_to_project_heading,
    add_to_task_heading,
    append_to_chain_note,
    append_to_project_note,
    append_to_task_note,
    ensure_chain_note,
    ensure_project_note,
    ensure_task_note,
    find_chain_note,
    find_project_note,
    find_task_note,
    touch_updated,
)
from .ops import append_op
from .progress import (
    ProgressResult,
    adjust_note_progress,
    clear_note_progress,
    set_note_progress,
    set_note_progress_status,
)


def finalize_task_note_edit(config: AppConfig, task: ResolvedTask, note: NotePaths) -> None:
    touch_updated(note.note_path)
    update_task_note_index(config, task, note.note_path)
    append_op(
        config,
        "task_note_edit",
        task_short_uuid=task.task_short_uuid,
        task_uuid=task.task_uuid,
        path=str(note.note_path),
        created=not note.existed,
    )


def finalize_chain_note_edit(config: AppConfig, task: ResolvedTask, note: NotePaths) -> None:
    touch_updated(note.note_path)
    update_chain_note_index(config, task, note.note_path)
    append_op(
        config,
        "chain_note_edit",
        task_short_uuid=task.task_short_uuid,
        task_uuid=task.task_uuid,
        chain_id=chain_id_for_task(task.task) or None,
        path=str(note.note_path),
        created=not note.existed,
    )


def finalize_project_note_edit(config: AppConfig, project_name: str, note: NotePaths) -> None:
    touch_updated(note.note_path)
    update_project_note_index(config, project_name, note.note_path)
    append_op(
        config,
        "project_note_edit",
        project=project_name,
        path=str(note.note_path),
        created=not note.existed,
    )


def append_task_note_storage(config: AppConfig, task: ResolvedTask, text: str) -> AppendResult:
    result = append_to_task_note(config, task, text)
    update_task_note_index(config, task, result.note_path)
    append_op(
        config,
        "task_note_append",
        task_short_uuid=task.task_short_uuid,
        task_uuid=task.task_uuid,
        path=str(result.note_path),
    )
    return result


def append_chain_note_storage(config: AppConfig, task: ResolvedTask, text: str) -> AppendResult:
    result = append_to_chain_note(config, task, text)
    update_chain_note_index(config, task, result.note_path)
    append_op(
        config,
        "chain_note_append",
        task_short_uuid=task.task_short_uuid,
        task_uuid=task.task_uuid,
        chain_id=chain_id_for_task(task.task) or None,
        path=str(result.note_path),
    )
    return result


def append_project_note_storage(config: AppConfig, project_name: str, text: str) -> AppendResult:
    result = append_to_project_note(config, project_name, text)
    update_project_note_index(config, project_name, result.note_path)
    append_op(
        config,
        "project_note_append",
        project=project_name,
        path=str(result.note_path),
    )
    return result


def delete_task_note_storage(config: AppConfig, task: ResolvedTask) -> dict[str, object]:
    result = delete_task_note(config, task)
    remove_task_note_index(config, task.task_short_uuid)
    append_op(
        config,
        "task_note_delete",
        task_short_uuid=task.task_short_uuid,
        task_uuid=task.task_uuid,
        path=str(result.note_path),
        trash_path=str(result.trash_path),
    )
    return {
        "note_path": result.note_path,
        "trash_path": result.trash_path,
        "task_short_uuid": task.task_short_uuid,
    }


def delete_chain_note_storage(config: AppConfig, task: ResolvedTask) -> dict[str, object]:
    chain_id = chain_id_for_task(task.task)
    result = delete_chain_note(config, task)
    if chain_id:
        remove_chain_note_index(config, chain_id)
    append_op(
        config,
        "chain_note_delete",
        task_short_uuid=task.task_short_uuid,
        task_uuid=task.task_uuid,
        chain_id=chain_id or None,
        path=str(result.note_path),
        trash_path=str(result.trash_path),
    )
    return {
        "note_path": result.note_path,
        "trash_path": result.trash_path,
        "task_short_uuid": task.task_short_uuid,
        "chain_id": chain_id,
    }


def delete_project_note_storage(config: AppConfig, project_name: str) -> dict[str, object]:
    result = delete_project_note(config, project_name)
    remove_project_note_index(config, project_name)
    append_op(
        config,
        "project_note_delete",
        project=project_name,
        path=str(result.note_path),
        trash_path=str(result.trash_path),
    )
    return {
        "note_path": result.note_path,
        "trash_path": result.trash_path,
        "project": project_name,
    }


def add_to_task_heading_storage(
    config: AppConfig,
    task: ResolvedTask,
    *,
    heading: str,
    text: str,
    create_heading: bool,
    exact: bool,
) -> dict[str, object]:
    result = add_to_task_heading(
        config,
        task,
        heading,
        text,
        create_heading=create_heading,
        exact=exact,
    )
    update_task_note_index(config, task, result.note_path)
    append_op(
        config,
        "task_note_add_to_heading",
        task_short_uuid=task.task_short_uuid,
        task_uuid=task.task_uuid,
        heading=result.heading,
        heading_match=result.match,
        entry=result.entry,
        path=str(result.note_path),
    )
    return {
        "note_path": result.note_path,
        "opened": result.existed,
        "heading": result.heading,
        "heading_match": result.match,
        "timestamp": result.timestamp,
        "entry": result.entry,
    }


def add_to_chain_heading_storage(
    config: AppConfig,
    task: ResolvedTask,
    *,
    heading: str,
    text: str,
    create_heading: bool,
    exact: bool,
) -> dict[str, object]:
    result = add_to_chain_heading(
        config,
        task,
        heading,
        text,
        create_heading=create_heading,
        exact=exact,
    )
    update_chain_note_index(config, task, result.note_path)
    append_op(
        config,
        "chain_note_add_to_heading",
        task_short_uuid=task.task_short_uuid,
        task_uuid=task.task_uuid,
        chain_id=chain_id_for_task(task.task) or None,
        heading=result.heading,
        heading_match=result.match,
        entry=result.entry,
        path=str(result.note_path),
    )
    return {
        "note_path": result.note_path,
        "opened": result.existed,
        "heading": result.heading,
        "heading_match": result.match,
        "timestamp": result.timestamp,
        "entry": result.entry,
    }


def add_to_project_heading_storage(
    config: AppConfig,
    project_name: str,
    *,
    heading: str,
    text: str,
    create_heading: bool,
    exact: bool,
) -> dict[str, object]:
    result = add_to_project_heading(
        config,
        project_name,
        heading,
        text,
        create_heading=create_heading,
        exact=exact,
    )
    update_project_note_index(config, project_name, result.note_path)
    append_op(
        config,
        "project_note_add_to_heading",
        project=project_name,
        heading=result.heading,
        heading_match=result.match,
        entry=result.entry,
        path=str(result.note_path),
    )
    return {
        "note_path": result.note_path,
        "opened": result.existed,
        "heading": result.heading,
        "heading_match": result.match,
        "timestamp": result.timestamp,
        "entry": result.entry,
    }


def attach_task_resource_storage(
    config: AppConfig,
    task: ResolvedTask,
    *,
    target: str,
    label: str | None,
) -> dict[str, object]:
    note = ensure_task_note(config, task)
    result = attach_note_resource(note.note_path, target, label)
    update_task_note_index(config, task, result.note_path)
    append_op(
        config,
        "task_resource_attach",
        task_short_uuid=task.task_short_uuid,
        task_uuid=task.task_uuid,
        target=result.resource.get("target"),
        label=result.resource.get("label"),
        path=str(result.note_path),
    )
    return {
        "note_path": result.note_path,
        "opened": note.existed,
        "resource": result.resource,
        "resources": result.resources,
    }


def attach_chain_resource_storage(
    config: AppConfig,
    task: ResolvedTask,
    *,
    target: str,
    label: str | None,
) -> dict[str, object]:
    note = ensure_chain_note(config, task)
    result = attach_note_resource(note.note_path, target, label)
    update_chain_note_index(config, task, result.note_path)
    append_op(
        config,
        "chain_resource_attach",
        task_short_uuid=task.task_short_uuid,
        task_uuid=task.task_uuid,
        chain_id=chain_id_for_task(task.task) or None,
        target=result.resource.get("target"),
        label=result.resource.get("label"),
        path=str(result.note_path),
    )
    return {
        "note_path": result.note_path,
        "opened": note.existed,
        "resource": result.resource,
        "resources": result.resources,
    }


def attach_project_resource_storage(
    config: AppConfig,
    project_name: str,
    *,
    target: str,
    label: str | None,
) -> dict[str, object]:
    note = ensure_project_note(config, project_name)
    result = attach_note_resource(note.note_path, target, label)
    update_project_note_index(config, project_name, result.note_path)
    append_op(
        config,
        "project_resource_attach",
        project=project_name,
        target=result.resource.get("target"),
        label=result.resource.get("label"),
        path=str(result.note_path),
    )
    return {
        "note_path": result.note_path,
        "opened": note.existed,
        "resource": result.resource,
        "resources": result.resources,
    }


def detach_task_resource_storage(
    config: AppConfig,
    task: ResolvedTask,
    *,
    note_path: Path,
    resource_id: int,
) -> dict[str, object]:
    result = detach_note_resource(note_path, resource_id)
    update_task_note_index(config, task, result.note_path)
    append_op(
        config,
        "task_resource_detach",
        task_short_uuid=task.task_short_uuid,
        task_uuid=task.task_uuid,
        resource_id=resource_id,
        target=result.resource.get("target"),
        label=result.resource.get("label"),
        path=str(result.note_path),
    )
    return {"note_path": result.note_path, "resource": result.resource, "resources": result.resources}


def detach_chain_resource_storage(
    config: AppConfig,
    task: ResolvedTask,
    *,
    note_path: Path,
    resource_id: int,
) -> dict[str, object]:
    result = detach_note_resource(note_path, resource_id)
    update_chain_note_index(config, task, result.note_path)
    append_op(
        config,
        "chain_resource_detach",
        task_short_uuid=task.task_short_uuid,
        task_uuid=task.task_uuid,
        chain_id=chain_id_for_task(task.task) or None,
        resource_id=resource_id,
        target=result.resource.get("target"),
        label=result.resource.get("label"),
        path=str(result.note_path),
    )
    return {"note_path": result.note_path, "resource": result.resource, "resources": result.resources}


def detach_project_resource_storage(
    config: AppConfig,
    project_name: str,
    *,
    note_path: Path,
    resource_id: int,
) -> dict[str, object]:
    result = detach_note_resource(note_path, resource_id)
    update_project_note_index(config, project_name, result.note_path)
    append_op(
        config,
        "project_resource_detach",
        project=project_name,
        resource_id=resource_id,
        target=result.resource.get("target"),
        label=result.resource.get("label"),
        path=str(result.note_path),
    )
    return {"note_path": result.note_path, "resource": result.resource, "resources": result.resources}


def mutate_task_progress_storage(
    config: AppConfig,
    task: ResolvedTask,
    *,
    note_kind: str,
    operation: str,
    current: Decimal | None = None,
    target: Decimal | None = None,
    amount: Decimal | None = None,
    unit: str | None = None,
    status: str | None = None,
    track: str = "default",
) -> dict[str, object]:
    if note_kind == "task":
        note = _task_progress_note(config, task, operation)
        chain_id = None
    elif note_kind == "chain":
        note = _chain_progress_note(config, task, operation)
        chain_id = chain_id_for_task(task.task)
    else:
        raise RuntimeError(f"unsupported task progress note kind: {note_kind}")

    result = _mutate_progress(
        note.note_path,
        operation=operation,
        current=current,
        target=target,
        amount=amount,
        unit=unit,
        status=status,
        track=track,
    )
    if note_kind == "task":
        update_task_note_index(config, task, result.note_path)
    else:
        update_chain_note_index(config, task, result.note_path)
    append_op(
        config,
        f"{note_kind}_progress_{operation}",
        task_short_uuid=task.task_short_uuid,
        task_uuid=task.task_uuid,
        chain_id=chain_id or None,
        progress=result.progress,
        progress_track=result.track,
        entry=result.entry,
        path=str(result.note_path),
    )
    return {
        "note_path": result.note_path,
        "opened": note.existed,
        "progress": result.progress,
        "track": result.track,
        "tracks": list(result.tracks),
        "entry": result.entry,
    }


def mutate_project_progress_storage(
    config: AppConfig,
    project_name: str,
    *,
    operation: str,
    current: Decimal | None = None,
    target: Decimal | None = None,
    amount: Decimal | None = None,
    unit: str | None = None,
    status: str | None = None,
    track: str = "default",
) -> dict[str, object]:
    if operation == "set":
        note = ensure_project_note(config, project_name)
    else:
        note_path = find_project_note(config, project_name)
        if note_path is None:
            raise RuntimeError(f"project note does not exist for {project_name}")
        note = NotePaths(note_path=note_path, existed=True)
    result = _mutate_progress(
        note.note_path,
        operation=operation,
        current=current,
        target=target,
        amount=amount,
        unit=unit,
        status=status,
        track=track,
    )
    update_project_note_index(config, project_name, result.note_path)
    append_op(
        config,
        f"project_progress_{operation}",
        project=project_name,
        progress=result.progress,
        progress_track=result.track,
        entry=result.entry,
        path=str(result.note_path),
    )
    return {
        "note_path": result.note_path,
        "opened": note.existed,
        "progress": result.progress,
        "track": result.track,
        "tracks": list(result.tracks),
        "entry": result.entry,
    }


def _mutate_progress(
    note_path: Path,
    *,
    operation: str,
    current: Decimal | None,
    target: Decimal | None,
    amount: Decimal | None,
    unit: str | None,
    status: str | None,
    track: str,
) -> ProgressResult:
    if operation == "set":
        if current is None or target is None:
            raise RuntimeError("set requires current and target values")
        return set_note_progress(note_path, current, target, unit=unit, status=status, track=track)
    if operation == "add":
        if amount is None:
            raise RuntimeError("add requires an amount")
        return adjust_note_progress(note_path, amount, track=track)
    if operation == "subtract":
        if amount is None:
            raise RuntimeError("subtract requires an amount")
        return adjust_note_progress(note_path, -amount, track=track)
    if operation == "status":
        return set_note_progress_status(note_path, str(status or ""), track=track)
    if operation == "clear":
        return clear_note_progress(note_path, track=track)
    raise RuntimeError(f"unknown progress operation: {operation}")


def _task_progress_note(config: AppConfig, task: ResolvedTask, operation: str) -> NotePaths:
    if operation == "set":
        return ensure_task_note(config, task)
    note_path = find_task_note(config, task)
    if note_path is None:
        raise RuntimeError(f"task note does not exist for {task.task_short_uuid}")
    return NotePaths(note_path=note_path, existed=True)


def _chain_progress_note(config: AppConfig, task: ResolvedTask, operation: str) -> NotePaths:
    if operation == "set":
        return ensure_chain_note(config, task)
    note_path = find_chain_note(config, task)
    if note_path is None:
        raise RuntimeError(f"chain note does not exist for {task.task_short_uuid}")
    return NotePaths(note_path=note_path, existed=True)


def record_event_add(
    config: AppConfig,
    task: ResolvedTask,
    *,
    event_type: str,
    annotation: str,
) -> None:
    update_task_event_index(config, task)
    append_op(
        config,
        "event_add",
        task_short_uuid=task.task_short_uuid,
        task_uuid=task.task_uuid,
        project=task.project or None,
        chain_id=chain_id_for_task(task.task) or None,
        event_type=event_type,
        annotation=annotation,
    )
