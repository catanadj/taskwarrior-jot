from __future__ import annotations

from pathlib import Path

from .index import update_chain_note_index, update_task_event_index, update_task_note_index
from .models import AppConfig, AppendResult, NotePaths, ResolvedTask
from .nautical import chain_id_for_task
from .notes import (
    append_to_chain_note,
    append_to_task_note,
    ensure_chain_note,
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
        chain_id=chain_id_for_task(task.task) or None,
        event_type=event_type,
        annotation=annotation,
    )
