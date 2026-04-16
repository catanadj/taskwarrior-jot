from __future__ import annotations

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
    delete_chain_note,
    delete_project_note,
    delete_task_note,
    add_to_chain_heading,
    add_to_project_heading,
    add_to_task_heading,
    append_to_chain_note,
    append_to_project_note,
    append_to_task_note,
    ensure_chain_note,
    ensure_project_note,
    ensure_task_note,
    touch_updated,
)
from .ops import append_op


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
