from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

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

    note_kind = _resolve_scope(scope, new)
    guard_key = _time_log_key(task.task_uuid, started, stopped)
    text = _format_time_entry(task, started, stopped, new, guard_key=guard_key)
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
                chain_id=chain_id_for_task(new) or None,
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
            "chain_id": chain_id_for_task(new) or None,
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
        "chain_id": chain_id_for_task(new) or None,
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
