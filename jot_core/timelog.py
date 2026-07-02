from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .frontmatter import atomic_write_text, exclusive_file_lock
from .index import update_chain_note_index, update_task_note_index
from .models import ResolvedTask, TaskRef
from .nautical import chain_id_for_task
from .notes import append_under_heading_once, ensure_chain_note, ensure_task_note
from .ops import append_op


TIME_LOG_HEADING = "Time log"


def ingest_time_log(config, old: dict[str, Any], new: dict[str, Any], *, scope: str = "auto", stopped_at: str = "") -> dict[str, Any]:
    if not isinstance(old, dict) or not isinstance(new, dict):
        raise RuntimeError("timelog ingest expects old and new task JSON objects")
    if "start" not in old or "start" in new:
        return {"written": False, "reason": "not a task stop"}

    task = _resolved_task_from_json(new)
    started = _parse_datetime(str(old.get("start") or ""))
    stopped = _parse_datetime(stopped_at) if stopped_at else datetime.now(timezone.utc)
    if stopped < started:
        raise RuntimeError("stop time is before start time")

    return write_time_log(config, task, started=started, stopped=stopped, scope=scope)


def start_time_session(config, task: ResolvedTask, *, started_at: str = "") -> dict[str, Any]:
    started = _parse_datetime(started_at) if started_at else datetime.now(timezone.utc)
    path = _session_store_path(config)
    with exclusive_file_lock(path):
        sessions = _read_sessions_unlocked(path)
        existing = sessions.get(task.task_uuid)
        if isinstance(existing, dict):
            return {
                "task_uuid": task.task_uuid,
                "task_short_uuid": task.task_short_uuid,
                "chain_id": existing.get("chain_id") or chain_id_for_task(task.task) or None,
                "started": existing.get("started"),
                "path": str(path),
                "already_started": True,
            }
        sessions[task.task_uuid] = {
            "task_uuid": task.task_uuid,
            "task_short_uuid": task.task_short_uuid,
            "description": task.description,
            "project": task.project,
            "chain_id": chain_id_for_task(task.task) or None,
            "started": _iso_z(started),
        }
        _write_sessions_unlocked(path, sessions)
    append_op(
        config,
        "timelog_session_start",
        task_short_uuid=task.task_short_uuid,
        task_uuid=task.task_uuid,
        chain_id=chain_id_for_task(task.task) or None,
        started=_iso_z(started),
    )
    return {
        "task_uuid": task.task_uuid,
        "task_short_uuid": task.task_short_uuid,
        "chain_id": chain_id_for_task(task.task) or None,
        "started": _iso_z(started),
        "path": str(path),
    }


def stop_time_session(config, task: ResolvedTask, *, stopped_at: str = "", scope: str = "auto") -> dict[str, Any]:
    stopped = _parse_datetime(stopped_at) if stopped_at else datetime.now(timezone.utc)
    path = _session_store_path(config)
    with exclusive_file_lock(path):
        sessions = _read_sessions_unlocked(path)
        session = sessions.get(task.task_uuid)
        if not isinstance(session, dict):
            raise RuntimeError(f"no pending timelog session for {task.task_short_uuid}")
        started = _parse_datetime(str(session.get("started") or ""))
        if stopped < started:
            raise RuntimeError("stop time is before start time")
        result = write_time_log(config, task, started=started, stopped=stopped, scope=scope)
        sessions.pop(task.task_uuid, None)
        _write_sessions_unlocked(path, sessions)
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
    return {
        **result,
        "session_cleared": True,
        "session_path": str(path),
    }


def list_time_sessions(config) -> list[dict[str, Any]]:
    path = _session_store_path(config)
    with exclusive_file_lock(path):
        sessions = _read_sessions_unlocked(path)
    return sorted(
        [item for item in sessions.values() if isinstance(item, dict)],
        key=lambda item: str(item.get("started") or ""),
    )


def cancel_time_session(config, task: ResolvedTask) -> dict[str, Any]:
    path = _session_store_path(config)
    with exclusive_file_lock(path):
        sessions = _read_sessions_unlocked(path)
        session = sessions.pop(task.task_uuid, None)
        if not isinstance(session, dict):
            raise RuntimeError(f"no pending timelog session for {task.task_short_uuid}")
        _write_sessions_unlocked(path, sessions)
    append_op(
        config,
        "timelog_session_cancel",
        task_short_uuid=task.task_short_uuid,
        task_uuid=task.task_uuid,
        chain_id=chain_id_for_task(task.task) or None,
        started=session.get("started"),
    )
    return {
        "task_uuid": task.task_uuid,
        "task_short_uuid": task.task_short_uuid,
        "chain_id": chain_id_for_task(task.task) or None,
        "started": session.get("started"),
        "path": str(path),
    }


def write_time_log(
    config,
    task: ResolvedTask,
    *,
    started: datetime,
    stopped: datetime,
    scope: str = "auto",
) -> dict[str, Any]:
    if stopped < started:
        raise RuntimeError("stop time is before start time")
    note_kind = _resolve_scope(scope, task.task)
    guard_key = _time_log_key(task.task_uuid, started, stopped)
    text = _format_time_entry(task, started, stopped, task.task, guard_key=guard_key)
    if note_kind == "chain":
        note = ensure_chain_note(config, task)
        result = append_under_heading_once(
            note.note_path,
            heading=TIME_LOG_HEADING,
            text=text,
            guard_key=guard_key,
            create_heading=True,
            exact=True,
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
        return {
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
        }

    return {
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
    }


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


def _resolve_scope(scope: str, task_json: dict[str, Any]) -> str:
    normalized = str(scope or "auto").strip().casefold()
    if normalized not in {"auto", "task", "chain"}:
        raise RuntimeError("timelog scope must be auto, task, or chain")
    if normalized == "auto":
        return "chain" if chain_id_for_task(task_json) else "task"
    if normalized == "chain" and not chain_id_for_task(task_json):
        raise RuntimeError("cannot write chain time log for a task without chainID")
    return normalized


def _format_time_entry(
    task: ResolvedTask,
    started: datetime,
    stopped: datetime,
    task_json: dict[str, Any],
    *,
    guard_key: str,
) -> str:
    minutes = round((stopped - started).total_seconds() / 60, 2)
    duration = _duration_text(minutes)
    parts = [
        f"{duration} spent",
        f"from {_display_time(started)} to {_display_time(stopped)}",
        f"task {task.task_short_uuid}",
    ]
    if task.description:
        parts.append(task.description)
    if task.project:
        parts.append(f"project {task.project}")
    chain_id = chain_id_for_task(task_json)
    if chain_id:
        parts.append(f"chain {chain_id}")
    if task.tags:
        parts.append("tags " + ", ".join(task.tags))
    parts.append(f"uuid {task.task_uuid}")
    parts.append(f"timelog:{guard_key}")
    return "; ".join(parts)


def _time_log_key(task_uuid: str, started: datetime, stopped: datetime) -> str:
    raw = "|".join([str(task_uuid), _iso_z(started), _iso_z(stopped)])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _duration_text(minutes: float) -> str:
    if minutes < 60:
        return f"{minutes:g}m"
    hours = minutes / 60
    return f"{hours:.2f}h"


def _display_time(value: datetime) -> str:
    return value.astimezone().strftime("%Y-%m-%d %H:%M")


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


def _session_store_path(config) -> Path:
    return config.root_dir / "timelog-pending.json"


def _read_sessions_unlocked(path: Path) -> dict[str, dict[str, Any]]:
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
    return {str(key): value for key, value in sessions.items() if isinstance(value, dict)}


def _write_sessions_unlocked(path: Path, sessions: dict[str, dict[str, Any]]) -> None:
    payload = {
        "version": 1,
        "sessions": sessions,
        "updated": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
