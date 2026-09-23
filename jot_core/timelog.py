from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from .frontmatter import atomic_write_text, exclusive_file_lock, read_document, write_document
from .index import update_chain_note_index, update_task_note_index
from .models import (
    AppConfig,
    ResolvedTask,
    TimelogSessionRecord,
    TaskRef,
    TimelogEntryMutation,
    TimelogReport,
    TimelogSession,
    TimelogSessionResult,
    TimelogStopAllResult,
    TimelogStopResult,
    TimelogWriteResult,
)
from .nautical import chain_id_for_task
from .notes import append_under_heading_once, ensure_chain_note, ensure_task_note
from .ops import append_op, iso_now, read_ops
from .taskwarrior import TaskwarriorClient
from .timewarrior import start_timewarrior_for_task
from .timelog_report import build_time_log_report
from . import timelog_store


TIME_LOG_HEADING = "Time log"
TIME_LOG_DATA_RE = re.compile(r"<!--\s*jot-time-log\s+({.*?})\s*-->")
TIME_LOG_HEADING_RE = re.compile(r"^##\s+Time log\s*$", re.IGNORECASE)
SECTION_END_RE = re.compile(r"^#{1,2}\s+")
TIMEW_ATTEMPT_LEASE_SECONDS = 60


def ingest_time_log(
    config: AppConfig,
    old: dict[str, Any],
    new: dict[str, Any],
    *,
    scope: str = "auto",
    stopped_at: str = "",
) -> dict[str, Any] | TimelogWriteResult:
    if not isinstance(old, dict) or not isinstance(new, dict):
        raise RuntimeError("timelog ingest expects old and new task JSON objects")
    started_text = str(old.get("start") or "").strip()
    new_start_text = str(new.get("start") or "").strip()
    if not started_text or new_start_text:
        return {"written": False, "reason": "not a task stop"}

    task = _resolved_task_from_json(new)
    started = _parse_datetime(started_text)
    stopped = _parse_datetime(stopped_at) if stopped_at else datetime.now(timezone.utc)
    if stopped < started:
        raise RuntimeError("stop time is before start time")

    return write_time_log(config, task, started=started, stopped=stopped, scope=scope)


def start_time_session(config: AppConfig, task: ResolvedTask, *, started_at: str = "") -> TimelogSessionResult:
    started = _parse_datetime(started_at) if started_at else datetime.now(timezone.utc)
    path = timelog_store.session_store_path(config)
    existing = None
    with exclusive_file_lock(path):
        sessions = timelog_store.read_sessions(path)
        existing = sessions.get(task.task_uuid)
        if isinstance(existing, dict):
            result = {
                "task_uuid": task.task_uuid,
                "task_short_uuid": task.task_short_uuid,
                "chain_id": existing.get("chain_id") or chain_id_for_task(task.task) or None,
                "started": existing.get("started"),
                "path": str(path),
                "already_started": True,
            }
        else:
            sessions[task.task_uuid] = {
                "task_uuid": task.task_uuid,
                "task_short_uuid": task.task_short_uuid,
                "description": task.description,
                "project": task.project,
                "chain_id": chain_id_for_task(task.task) or None,
                "started": _iso_z(started),
                "timewarrior_attempted": False,
                "timewarrior_started": False,
                "timewarrior_state": "pending",
            }
            timelog_store.write_sessions(path, sessions)
            result = {
                "task_uuid": task.task_uuid,
                "task_short_uuid": task.task_short_uuid,
                "chain_id": chain_id_for_task(task.task) or None,
                "started": _iso_z(started),
                "path": str(path),
            }

    # A successful external start is idempotent. Failed and interrupted
    # attempts remain retryable; a recent in-flight attempt gets a short lease
    # so two concurrent starts do not invoke Timewarrior twice.
    retry_timewarrior, attempt_in_progress = _timewarrior_retry_state(existing)
    if isinstance(existing, dict) and not retry_timewarrior:
        result["timewarrior"] = {
            "enabled": bool(config.timewarrior_enabled),
            "attempted": False,
            "started": False,
            "reason": "timewarrior-attempt-in-progress" if attempt_in_progress else "already-started",
            "error": None,
        }
        return TimelogSessionResult.from_mapping(result, operation="start")

    if not isinstance(existing, dict):
        append_op(
            config,
            "timelog_session_start",
            task_short_uuid=task.task_short_uuid,
            task_uuid=task.task_uuid,
            chain_id=chain_id_for_task(task.task) or None,
            started=_iso_z(started),
        )

    with exclusive_file_lock(path):
        sessions = timelog_store.read_sessions(path)
        current = sessions.get(task.task_uuid)
        if isinstance(current, dict) and current.get("started") == result.get("started"):
            current["timewarrior_state"] = "attempting"
            current["timewarrior_attempted_at"] = _iso_z(datetime.now(timezone.utc))
            timelog_store.write_sessions(path, sessions)

    result["timewarrior"] = start_timewarrior_for_task(config, task)
    if retry_timewarrior:
        result["timewarrior_retry"] = True

    with exclusive_file_lock(path):
        sessions = timelog_store.read_sessions(path)
        current = sessions.get(task.task_uuid)
        if isinstance(current, dict) and current.get("started") == result.get("started"):
            timewarrior = result["timewarrior"]
            current["timewarrior_attempted"] = bool(timewarrior.get("attempted"))
            current["timewarrior_started"] = bool(timewarrior.get("started"))
            current["timewarrior_state"] = _timewarrior_result_state(timewarrior)
            current.pop("timewarrior_attempted_at", None)
            if timewarrior.get("error"):
                current["timewarrior_error"] = str(timewarrior["error"])
            else:
                current.pop("timewarrior_error", None)
            timelog_store.write_sessions(path, sessions)
    return TimelogSessionResult.from_mapping(result, operation="start")


def _timewarrior_retry_state(existing: dict[str, Any] | None) -> tuple[bool, bool]:
    if not isinstance(existing, dict):
        return True, False
    state = str(existing.get("timewarrior_state") or "").strip().lower()
    if state in {"succeeded", "skipped"}:
        return False, False
    if state == "attempting":
        raw_attempted_at = str(existing.get("timewarrior_attempted_at") or "").strip()
        if raw_attempted_at:
            try:
                attempted_at = _parse_datetime(raw_attempted_at)
            except RuntimeError:
                return True, False
            age = (datetime.now(timezone.utc) - attempted_at).total_seconds()
            if age < TIMEW_ATTEMPT_LEASE_SECONDS:
                return False, True
        return True, False
    if state in {"pending", "failed"}:
        return True, False

    # Legacy sessions have no explicit state. Preserve their old behavior:
    # only attempted or incomplete records are retryable.
    return (
        existing.get("timewarrior_started") is not True
        and (
            existing.get("timewarrior_attempted") is True
            or "timewarrior_attempted" not in existing
        ),
        False,
    )


def _timewarrior_result_state(result: dict[str, Any]) -> str:
    if result.get("started") is True:
        return "succeeded"
    if result.get("attempted") is True:
        return "failed"
    return "skipped"


def stop_time_session(config: AppConfig, task: ResolvedTask, *, stopped_at: str = "", scope: str = "auto") -> TimelogStopResult:
    stopped = _parse_datetime(stopped_at) if stopped_at else datetime.now(timezone.utc)
    path = timelog_store.session_store_path(config)
    with exclusive_file_lock(path):
        sessions = timelog_store.read_sessions(path)
        session = sessions.get(task.task_uuid)
        if not isinstance(session, dict):
            raise RuntimeError(f"no pending timelog session for {task.task_short_uuid}")
        started = _parse_datetime(str(session.get("started") or ""))
        if stopped < started:
            raise RuntimeError("stop time is before start time")
        result = write_time_log(config, task, started=started, stopped=stopped, scope=scope)
        sessions.pop(task.task_uuid, None)
        timelog_store.write_sessions(path, sessions)
    append_op(
        config,
        "timelog_session_stop",
        task_short_uuid=task.task_short_uuid,
        task_uuid=task.task_uuid,
        chain_id=chain_id_for_task(task.task) or None,
        started=_iso_z(started),
        stopped=_iso_z(stopped),
        written=bool(result.get("written")),
        duplicate=bool(result.get("duplicate")),
        timelog_key=result.get("timelog_key"),
    )
    return TimelogStopResult.from_mapping({
        **result,
        "session_cleared": True,
        "session_path": str(path),
    })


def stop_all_time_sessions(config: AppConfig, taskwarrior: TaskwarriorClient, *, stopped_at: str = "", scope: str = "auto") -> TimelogStopAllResult:
    stopped = _parse_datetime(stopped_at) if stopped_at else datetime.now(timezone.utc)
    sessions = list_time_sessions(config, now=stopped)
    results: list[TimelogStopResult] = []
    errors: list[dict[str, str]] = []
    for session in sessions:
        task_uuid = str(session.get("task_uuid") or "").strip()
        if not task_uuid:
            continue
        try:
            task = taskwarrior.resolve_task(task_uuid)
            results.append(stop_time_session(config, task, stopped_at=_iso_z(stopped), scope=scope))
        except Exception as exc:
            errors.append({"task_uuid": task_uuid, "error": str(exc)})
    return TimelogStopAllResult.from_mapping({
        "stopped": _iso_z(stopped),
        "count": len(results),
        "error_count": len(errors),
        "items": [item.to_payload() for item in results],
        "errors": errors,
    })


def list_time_sessions(config: AppConfig, *, now: datetime | None = None) -> list[TimelogSession]:
    current = now or datetime.now(timezone.utc)
    path = timelog_store.session_store_path(config)
    with exclusive_file_lock(path):
        sessions = timelog_store.read_sessions(path)
    enriched = []
    for item in sessions.values():
        if not isinstance(item, dict):
            continue
        enriched.append(_session_with_elapsed(item, current))
    sorted_items = sorted(
        enriched,
        key=lambda item: str(item.get("started") or ""),
    )
    return [TimelogSession.from_mapping(item) for item in sorted_items]


def cancel_time_session(config: AppConfig, task: ResolvedTask) -> TimelogSessionResult:
    path = timelog_store.session_store_path(config)
    with exclusive_file_lock(path):
        sessions = timelog_store.read_sessions(path)
        session = sessions.pop(task.task_uuid, None)
        if not isinstance(session, dict):
            raise RuntimeError(f"no pending timelog session for {task.task_short_uuid}")
        timelog_store.write_sessions(path, sessions)
    append_op(
        config,
        "timelog_session_cancel",
        task_short_uuid=task.task_short_uuid,
        task_uuid=task.task_uuid,
        chain_id=chain_id_for_task(task.task) or None,
        started=session.get("started"),
    )
    return TimelogSessionResult.from_mapping({
        "task_uuid": task.task_uuid,
        "task_short_uuid": task.task_short_uuid,
        "chain_id": chain_id_for_task(task.task) or None,
        "started": session.get("started"),
        "path": str(path),
    }, operation="cancel")


def write_time_log(
    config: AppConfig,
    task: ResolvedTask,
    *,
    started: datetime,
    stopped: datetime,
    scope: str = "auto",
) -> TimelogWriteResult:
    if stopped < started:
        raise RuntimeError("stop time is before start time")
    note_kind = _resolve_scope(
        scope,
        task.task,
        nautical_enabled=bool(getattr(config, "nautical_enabled", True)),
    )
    guard_key = _time_log_key(task.task_uuid, started, stopped)
    text = _format_time_entry(task, started, stopped, note_kind=note_kind, guard_key=guard_key)
    if note_kind == "chain":
        note = ensure_chain_note(config, task)
        result = append_under_heading_once(
            note.note_path,
            heading=TIME_LOG_HEADING,
            text=text,
            guard_key=guard_key,
            create_heading=True,
            exact=True,
            compact=True,
        )
        if result is not None:
            update_chain_note_index(config, task, note.note_path)
            append_op(
                config,
                "chain_note_timelog",
                task_short_uuid=task.task_short_uuid,
                task_uuid=task.task_uuid,
                chain_id=chain_id_for_task(task.task) or None,
                path=str(note.note_path),
                timelog_key=guard_key,
            )
    else:
        note = ensure_task_note(config, task)
        result = append_under_heading_once(
            note.note_path,
            heading=TIME_LOG_HEADING,
            text=text,
            guard_key=guard_key,
            create_heading=True,
            exact=True,
            compact=True,
        )
        if result is not None:
            update_task_note_index(config, task, note.note_path)
            append_op(
                config,
                "task_note_timelog",
                task_short_uuid=task.task_short_uuid,
                task_uuid=task.task_uuid,
                path=str(note.note_path),
                timelog_key=guard_key,
            )

    if result is None:
        return TimelogWriteResult.from_mapping({
            "written": False,
            "reason": "duplicate time log",
            "duplicate": True,
            "note_kind": note_kind,
            "path": str(note.note_path),
            "task_short_uuid": task.task_short_uuid,
            "task_uuid": task.task_uuid,
            "chain_id": chain_id_for_task(task.task) or None,
            "started": _iso_z(started),
            "stopped": _iso_z(stopped),
            "duration_minutes": round((stopped - started).total_seconds() / 60, 2),
            "timelog_key": guard_key,
        })

    return TimelogWriteResult.from_mapping({
        "written": True,
        "note_kind": note_kind,
        "path": str(note.note_path),
        "heading": result["heading"],
        "task_short_uuid": task.task_short_uuid,
        "task_uuid": task.task_uuid,
        "chain_id": chain_id_for_task(task.task) or None,
        "started": _iso_z(started),
        "stopped": _iso_z(stopped),
        "duration_minutes": round((stopped - started).total_seconds() / 60, 2),
        "timelog_key": guard_key,
        "entry": result["entry"],
    })


def add_time_log(
    config: AppConfig,
    task: ResolvedTask,
    *,
    started_at: str,
    stopped_at: str,
    scope: str = "auto",
) -> TimelogWriteResult:
    started = _parse_user_datetime(started_at)
    stopped = _parse_user_datetime(stopped_at)
    return write_time_log(config, task, started=started, stopped=stopped, scope=scope)


def amend_time_log(
    config: AppConfig,
    key: str,
    *,
    started_at: str = "",
    stopped_at: str = "",
) -> TimelogEntryMutation:
    if not started_at and not stopped_at:
        raise RuntimeError("timelog amend requires --from or --to")
    location = _find_time_log_location(config, key)
    record = dict(location["record"])
    started = _parse_user_datetime(started_at) if started_at else _parse_datetime(str(record.get("started") or ""))
    stopped = _parse_user_datetime(stopped_at) if stopped_at else _parse_datetime(str(record.get("stopped") or ""))
    if stopped < started:
        raise RuntimeError("stop time is before start time")
    task = _resolved_task_from_record(record)
    note_kind = str(record.get("note_kind") or location["note_kind"])
    old_key = str(record.get("key") or "")
    new_key = _time_log_key(task.task_uuid, started, stopped)
    replacement = _format_time_entry(task, started, stopped, note_kind=note_kind, guard_key=new_key)
    note_path = Path(str(location["path"]))

    with exclusive_file_lock(note_path):
        metadata, body = read_document(note_path)
        line_index, original_line = _find_time_log_line(body, old_key)
        if new_key != old_key and new_key in body:
            raise RuntimeError(f"timelog entry {new_key} already exists")
        archive_path = _archive_time_log_record(
            config,
            action="amend",
            path=note_path,
            line=original_line,
            record=record,
        )
        lines = body.splitlines()
        lines[line_index] = _replace_time_log_line(original_line, replacement)
        metadata["updated"] = iso_now()
        write_document(note_path, metadata, "\n".join(lines))

    _update_time_log_index(config, task, note_kind, note_path)
    append_op(
        config,
        "timelog_amend",
        timelog_key=old_key,
        new_timelog_key=new_key,
        task_uuid=task.task_uuid,
        task_short_uuid=task.task_short_uuid,
        chain_id=chain_id_for_task(task.task) or None,
        path=str(note_path),
        archive_path=str(archive_path),
    )
    return TimelogEntryMutation.from_mapping({
        "amended": True,
        "timelog_key": old_key,
        "new_timelog_key": new_key,
        "task_short_uuid": task.task_short_uuid,
        "started": _iso_z(started),
        "stopped": _iso_z(stopped),
        "duration_minutes": round((stopped - started).total_seconds() / 60, 2),
        "path": str(note_path),
        "archive_path": str(archive_path),
    }, operation="amend")


def delete_time_log(config: AppConfig, key: str) -> TimelogEntryMutation:
    location = _find_time_log_location(config, key)
    record = dict(location["record"])
    note_path = Path(str(location["path"]))
    exact_key = str(record.get("key") or "")

    with exclusive_file_lock(note_path):
        metadata, body = read_document(note_path)
        line_index, original_line = _find_time_log_line(body, exact_key)
        archive_path = _archive_time_log_record(
            config,
            action="delete",
            path=note_path,
            line=original_line,
            record=record,
        )
        lines = body.splitlines()
        del lines[line_index]
        metadata["updated"] = iso_now()
        write_document(note_path, metadata, "\n".join(lines))

    task = _resolved_task_from_record(record)
    note_kind = str(record.get("note_kind") or location["note_kind"])
    _update_time_log_index(config, task, note_kind, note_path)
    append_op(
        config,
        "timelog_delete",
        timelog_key=exact_key,
        task_uuid=task.task_uuid,
        task_short_uuid=task.task_short_uuid,
        chain_id=chain_id_for_task(task.task) or None,
        path=str(note_path),
        archive_path=str(archive_path),
    )
    return TimelogEntryMutation.from_mapping({
        "deleted": True,
        "timelog_key": exact_key,
        "task_short_uuid": task.task_short_uuid,
        "path": str(note_path),
        "archive_path": str(archive_path),
    }, operation="delete")


def list_deleted_time_logs(config: AppConfig, *, include_internal: bool = False) -> list[dict[str, Any]]:
    restored = {
        str(item.get("archive_path") or "").strip()
        for item in read_ops(config)
        if str(item.get("op") or "") == "timelog_restore"
    }
    archive_root = config.trash_dir / "timelog"
    items: list[dict[str, Any]] = []
    if not archive_root.exists():
        return items
    for archive_path in sorted(archive_root.rglob("*.json")):
        if str(archive_path) in restored:
            continue
        try:
            payload = json.loads(archive_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or str(payload.get("action") or "") != "delete":
            continue
        record = payload.get("record")
        if not isinstance(record, dict):
            continue
        key = str(record.get("key") or "").strip()
        line = str(payload.get("line") or "")
        note_path = str(payload.get("path") or "").strip()
        if not key or not line or not note_path:
            continue
        item = {
            "key": key,
            "task_short_uuid": str(record.get("task_short_uuid") or ""),
            "chain_id": str(record.get("chain_id") or ""),
            "project": str(record.get("project") or ""),
            "started": str(record.get("started") or ""),
            "stopped": str(record.get("stopped") or ""),
            "minutes": float(record.get("minutes") or 0),
            "duration": _duration_text(float(record.get("minutes") or 0)),
            "archived_at": str(payload.get("archived_at") or ""),
            "path": note_path,
            "archive_path": str(archive_path),
        }
        if include_internal:
            item["line"] = line
            item["record"] = record
        items.append(item)
    items.sort(key=lambda item: str(item.get("archived_at") or ""), reverse=True)
    for item_id, item in enumerate(items, start=1):
        item["id"] = item_id
    return items


def restore_deleted_time_log(config: AppConfig, reference: str) -> TimelogEntryMutation:
    archive = _select_deleted_time_log(
        list_deleted_time_logs(config, include_internal=True),
        reference,
    )
    record = dict(archive["record"])
    note_kind = str(record.get("note_kind") or "task").strip().casefold()
    if note_kind not in {"task", "chain"}:
        raise RuntimeError(f"cannot restore timelog entry with note kind '{note_kind}'")
    note_path = Path(str(archive["path"])).expanduser()
    expected_root = config.chains_dir if note_kind == "chain" else config.tasks_dir
    try:
        note_path.resolve().relative_to(expected_root.resolve())
    except ValueError as exc:
        raise RuntimeError("timelog archive target is outside the configured note directory") from exc
    if not note_path.exists():
        raise RuntimeError(f"timelog restore target note does not exist: {note_path}")

    key = str(record.get("key") or "")
    with exclusive_file_lock(note_path):
        metadata, body = read_document(note_path)
        if key in body:
            raise RuntimeError(f"timelog entry {key} already exists in {note_path}")
        restored_body = _insert_restored_time_log_line(body, str(archive["line"]))
        metadata["updated"] = iso_now()
        write_document(note_path, metadata, restored_body)

    task = _resolved_task_from_record(record)
    _update_time_log_index(config, task, note_kind, note_path)
    append_op(
        config,
        "timelog_restore",
        timelog_key=key,
        task_uuid=task.task_uuid,
        task_short_uuid=task.task_short_uuid,
        chain_id=chain_id_for_task(task.task) or None,
        path=str(note_path),
        archive_path=str(archive["archive_path"]),
    )
    return TimelogEntryMutation.from_mapping({
        "restored": True,
        "timelog_key": key,
        "task_short_uuid": task.task_short_uuid,
        "path": str(note_path),
        "archive_path": str(archive["archive_path"]),
    }, operation="restore")


def report_time_logs(
    config: AppConfig,
    *,
    period: str = "all",
    project: str = "",
    task_ref: str = "",
    chain_id: str = "",
    details: bool = False,
    since: str = "",
    until: str = "",
    now: datetime | None = None,
) -> TimelogReport:
    return build_time_log_report(
        _read_time_log_records(config),
        period=period,
        project=project,
        task_ref=task_ref,
        chain_id=chain_id,
        details=details,
        since=since,
        until=until,
        now=now,
        parse_datetime=_parse_datetime,
        iso_z=_iso_z,
        duration_text=_duration_text,
        time_range=_time_range,
    )


def _resolved_task_from_json(task_json: dict[str, Any]) -> ResolvedTask:
    uuid = str(task_json.get("uuid") or "").strip()
    if not uuid:
        raise RuntimeError("task JSON does not include uuid")
    tags = task_json.get("tags")
    tag_list = [str(tag) for tag in tags] if isinstance(tags, list) else []
    return ResolvedTask(
        ref=TaskRef(raw=uuid),
        task_uuid=uuid,
        task_short_uuid=uuid.split("-")[0],
        description=str(task_json.get("description") or ""),
        project=str(task_json.get("project") or ""),
        tags=tag_list,
        task=task_json,
    )


def _resolved_task_from_record(record: dict[str, Any]) -> ResolvedTask:
    task_uuid = str(record.get("task_uuid") or "").strip()
    if not task_uuid:
        raise RuntimeError("timelog entry does not include task_uuid")
    short_uuid = str(record.get("task_short_uuid") or "").strip() or task_uuid.split("-")[0]
    chain_id = str(record.get("chain_id") or "").strip()
    tags = record.get("tags")
    tag_list = [str(tag) for tag in tags] if isinstance(tags, list) else []
    task_json: dict[str, Any] = {
        "uuid": task_uuid,
        "project": str(record.get("project") or ""),
        "tags": tag_list,
    }
    if chain_id:
        task_json["chainID"] = chain_id
    return ResolvedTask(
        ref=TaskRef(raw=task_uuid),
        task_uuid=task_uuid,
        task_short_uuid=short_uuid,
        description="",
        project=str(record.get("project") or ""),
        tags=tag_list,
        task=task_json,
    )


def _resolve_scope(scope: str, task_json: dict[str, Any], *, nautical_enabled: bool = True) -> str:
    normalized = str(scope or "auto").strip().casefold()
    if normalized not in {"auto", "task", "chain"}:
        raise RuntimeError("timelog scope must be auto, task, or chain")
    if normalized == "auto":
        return "chain" if nautical_enabled and chain_id_for_task(task_json) else "task"
    if normalized == "chain" and not chain_id_for_task(task_json):
        raise RuntimeError("cannot write chain time log for a task without chainID")
    return normalized


def _format_time_entry(
    task: ResolvedTask,
    started: datetime,
    stopped: datetime,
    *,
    note_kind: str,
    guard_key: str,
) -> str:
    minutes = round((stopped - started).total_seconds() / 60, 2)
    duration = _duration_text(minutes)
    parts = [f"{duration}, {_time_range(started, stopped)}"]
    if task.project:
        parts.append(task.project)
    if task.tags:
        parts.append(" ".join(f"#{tag}" for tag in task.tags))
    parts.append(f"<!-- timelog:{guard_key} -->")
    parts.append(_time_log_data_comment(task, started, stopped, note_kind=note_kind, guard_key=guard_key))
    return "; ".join(parts)


def _time_log_data_comment(
    task: ResolvedTask,
    started: datetime,
    stopped: datetime,
    *,
    note_kind: str,
    guard_key: str,
) -> str:
    payload = {
        "v": 1,
        "key": guard_key,
        "note_kind": note_kind,
        "task_uuid": task.task_uuid,
        "task_short_uuid": task.task_short_uuid,
        "chain_id": chain_id_for_task(task.task) or "",
        "project": task.project,
        "tags": list(task.tags),
        "started": _iso_z(started),
        "stopped": _iso_z(stopped),
        "minutes": round((stopped - started).total_seconds() / 60, 2),
    }
    return f"<!-- jot-time-log {json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(',', ':'))} -->"


def _read_time_log_records(config) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for note_kind, root in (("task", config.tasks_dir), ("chain", config.chains_dir)):
        if not root.exists():
            continue
        for note_path in sorted(root.rglob("*.md")):
            if ".jot_history" in note_path.parts:
                continue
            _metadata, body = read_document(note_path)
            for match in TIME_LOG_DATA_RE.finditer(body):
                try:
                    record = json.loads(match.group(1))
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                key = str(record.get("key") or "").strip()
                if key and key in seen_keys:
                    continue
                if key:
                    seen_keys.add(key)
                record.setdefault("note_kind", note_kind)
                record["path"] = str(note_path)
                records.append(record)
    return sorted(records, key=lambda item: str(item.get("stopped") or item.get("started") or ""))


def _find_time_log_location(config, key: str) -> dict[str, Any]:
    query = str(key or "").strip().casefold()
    if len(query) < 4:
        raise RuntimeError("timelog key prefix must contain at least 4 characters")
    matches: list[dict[str, Any]] = []
    for note_kind, root in (("task", config.tasks_dir), ("chain", config.chains_dir)):
        if not root.exists():
            continue
        for note_path in sorted(root.rglob("*.md")):
            if ".jot_history" in note_path.parts:
                continue
            _metadata, body = read_document(note_path)
            for line_index, line in enumerate(body.splitlines()):
                match = TIME_LOG_DATA_RE.search(line)
                if match is None:
                    continue
                try:
                    record = json.loads(match.group(1))
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                record_key = str(record.get("key") or "").strip()
                if record_key.casefold().startswith(query):
                    matches.append(
                        {
                            "note_kind": note_kind,
                            "path": str(note_path),
                            "line_index": line_index,
                            "line": line,
                            "record": record,
                        }
                    )
    if not matches:
        raise RuntimeError(f"timelog entry not found for key '{key}'")
    exact = [item for item in matches if str(item["record"].get("key") or "").casefold() == query]
    if len(exact) == 1:
        return exact[0]
    if len(matches) > 1:
        keys = ", ".join(sorted({str(item["record"].get("key") or "") for item in matches}))
        raise RuntimeError(f"timelog key prefix '{key}' is ambiguous: {keys}")
    return matches[0]


def _select_deleted_time_log(items: list[dict[str, Any]], reference: str) -> dict[str, Any]:
    query = str(reference or "").strip()
    if query.startswith("#"):
        try:
            item_id = int(query[1:])
        except ValueError as exc:
            raise RuntimeError(f"invalid timelog trash ID '{reference}'") from exc
        selected = next((item for item in items if int(item.get("id") or 0) == item_id), None)
        if selected is None:
            raise RuntimeError(f"timelog trash item {query} does not exist")
        return selected
    normalized = query.casefold()
    if len(normalized) < 4:
        raise RuntimeError("timelog key prefix must contain at least 4 characters")
    matches = [item for item in items if str(item.get("key") or "").casefold().startswith(normalized)]
    if not matches:
        raise RuntimeError(f"deleted timelog entry not found for key '{reference}'")
    exact = [item for item in matches if str(item.get("key") or "").casefold() == normalized]
    if len(exact) == 1:
        return exact[0]
    if len(matches) > 1:
        refs = ", ".join(f"#{item.get('id')} {item.get('key')}" for item in matches)
        raise RuntimeError(f"deleted timelog key prefix '{reference}' is ambiguous: {refs}")
    return matches[0]


def _find_time_log_line(body: str, key: str) -> tuple[int, str]:
    for line_index, line in enumerate(body.splitlines()):
        match = TIME_LOG_DATA_RE.search(line)
        if match is None:
            continue
        try:
            record = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and str(record.get("key") or "") == key:
            return line_index, line
    raise RuntimeError(f"timelog entry {key} changed while waiting for the note lock")


def _replace_time_log_line(original_line: str, replacement: str) -> str:
    prefix_match = re.match(r"^(\s*-\s+\[[^\]]+\]\s+)", original_line)
    prefix = prefix_match.group(1) if prefix_match else "- "
    return f"{prefix}{replacement}"


def _insert_restored_time_log_line(body: str, line: str) -> str:
    restored_line = str(line or "").rstrip("\n")
    if not restored_line:
        raise RuntimeError("timelog archive does not include the original note line")
    lines = body.splitlines()
    heading_index = next(
        (index for index, value in enumerate(lines) if TIME_LOG_HEADING_RE.match(value.strip())),
        None,
    )
    if heading_index is None:
        while lines and not lines[-1].strip():
            lines.pop()
        if lines:
            lines.append("")
        lines.extend(["## Time log", restored_line])
        return "\n".join(lines)

    section_end = len(lines)
    for index in range(heading_index + 1, len(lines)):
        if SECTION_END_RE.match(lines[index].strip()):
            section_end = index
            break
    insertion_index = section_end
    while insertion_index > heading_index + 1 and not lines[insertion_index - 1].strip():
        insertion_index -= 1
    lines.insert(insertion_index, restored_line)
    return "\n".join(lines)


def _archive_time_log_record(
    config,
    *,
    action: str,
    path: Path,
    line: str,
    record: dict[str, Any],
) -> Path:
    archived_at = iso_now()
    stamp = archived_at.replace("-", "").replace(":", "")
    key = str(record.get("key") or "unknown")
    directory = config.trash_dir / "timelog" / stamp
    archive_path = directory / f"{key}.json"
    counter = 1
    while archive_path.exists():
        archive_path = directory / f"{key}-{counter}.json"
        counter += 1
    payload = {
        "action": action,
        "archived_at": archived_at,
        "path": str(path),
        "line": line,
        "record": record,
    }
    atomic_write_text(archive_path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return archive_path


def _update_time_log_index(config, task: ResolvedTask, note_kind: str, note_path: Path) -> None:
    if note_kind == "chain":
        update_chain_note_index(config, task, note_path)
    else:
        update_task_note_index(config, task, note_path)


def _time_log_key(task_uuid: str, started: datetime, stopped: datetime) -> str:
    raw = "|".join([str(task_uuid), _iso_z(started), _iso_z(stopped)])
    return hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]


def _duration_text(minutes: float) -> str:
    if minutes < 60:
        return f"{minutes:g}m"
    hours = minutes / 60
    return f"{hours:.2f}h"


def _session_with_elapsed(session: TimelogSessionRecord, now: datetime) -> TimelogSessionRecord:
    item = dict(session)
    try:
        started = _parse_datetime(str(item.get("started") or ""))
    except RuntimeError:
        return item
    minutes = max(0.0, round((now - started).total_seconds() / 60, 2))
    item["elapsed_minutes"] = minutes
    item["elapsed"] = _duration_text(minutes)
    return cast(TimelogSessionRecord, item)


def _time_range(started: datetime, stopped: datetime) -> str:
    local_start = started.astimezone()
    local_stop = stopped.astimezone()
    start_zone = _zone_label(local_start)
    stop_zone = _zone_label(local_stop)
    if local_start.date() == local_stop.date():
        suffix = start_zone if start_zone == stop_zone else f"{start_zone}->{stop_zone}"
        return f"{local_start:%H:%M}-{local_stop:%H:%M} {suffix}".strip()
    return f"{local_start:%Y-%m-%d %H:%M} {start_zone} -> {local_stop:%Y-%m-%d %H:%M} {stop_zone}".strip()


def _zone_label(value: datetime) -> str:
    return value.tzname() or value.strftime("%z")


def _parse_user_datetime(value: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise RuntimeError("datetime value is empty")
    if raw.endswith("Z") and len(raw) == 16 and raw[8] == "T":
        return _parse_datetime(raw)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError(f"invalid datetime: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.astimezone(timezone.utc)


def _parse_datetime(value: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise RuntimeError("datetime value is empty")
    try:
        if raw.endswith("Z") and len(raw) == 16 and raw[8] == "T":
            return datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        normalized = raw.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise RuntimeError(f"invalid datetime: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _session_store_path(config: AppConfig) -> Path:
    return config.root_dir / "timelog-pending.json"


def _read_sessions_unlocked(path: Path) -> dict[str, TimelogSessionRecord]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid timelog session store: {path}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"invalid timelog session store: {path}")
    sessions = data.get("sessions", data)
    if not isinstance(sessions, dict):
        raise RuntimeError(f"invalid timelog session store: {path}")
    return {
        str(key): cast(TimelogSessionRecord, value)
        for key, value in sessions.items()
        if isinstance(value, dict)
    }


def _write_sessions_unlocked(path: Path, sessions: dict[str, TimelogSessionRecord]) -> None:
    payload = {
        "version": 1,
        "sessions": sessions,
        "updated": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
