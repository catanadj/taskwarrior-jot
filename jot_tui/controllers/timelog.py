"""Timelog workflow service-call adapters for the Textual UI."""

from __future__ import annotations

from typing import Any, Mapping


def start(service: Any, task_ref: str) -> Any:
    return service.timelog_start(task_ref)


def stop(service: Any, session: Mapping[str, Any]) -> Any:
    return service.timelog_stop(str(session.get("task_uuid") or session.get("task_short_uuid") or ""))


def stop_all(service: Any) -> Any:
    return service.timelog_stop_all()


def cancel(service: Any, session: Mapping[str, Any]) -> Any:
    return service.timelog_cancel(str(session.get("task_uuid") or session.get("task_short_uuid") or ""))


def add(service: Any, payload: Mapping[str, str]) -> Any:
    return service.timelog_add(
        payload["task_ref"],
        started_at=payload["started_at"],
        stopped_at=payload["stopped_at"],
        scope=payload["scope"],
    )


def amend(service: Any, key: str, payload: Mapping[str, str]) -> Any:
    return service.timelog_amend(key, started_at=payload["started_at"], stopped_at=payload["stopped_at"])


def delete(service: Any, key: str) -> Any:
    return service.timelog_delete(key)


def trash(service: Any) -> Any:
    return service.timelog_trash()


def restore(service: Any, item: Mapping[str, Any]) -> Any:
    return service.timelog_restore(f"#{item.get('id')}")
