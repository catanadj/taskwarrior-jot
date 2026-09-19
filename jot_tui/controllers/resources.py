"""Resource workflow orchestration independent of Textual widgets."""

from __future__ import annotations

from typing import Any, Mapping


def attach_resource(service: Any, target: Mapping[str, Any], payload: Mapping[str, Any]) -> Any:
    return service.attach_resource(
        str(target.get("kind") or ""),
        task_ref=str(target.get("task_ref") or ""),
        project_name=str(target.get("project") or ""),
        target=str(payload.get("target") or ""),
        label=str(payload.get("label") or "") or None,
    )


def open_resource(service: Any, target: str) -> Any:
    return service.open_resource(target)


def detach_resource(service: Any, target: Mapping[str, Any], resource: Mapping[str, Any]) -> Any:
    return service.detach_resource(
        str(target.get("kind") or ""),
        task_ref=str(target.get("task_ref") or ""),
        project_name=str(target.get("project") or ""),
        note_path=str(target.get("path") or ""),
        resource_id=int(resource.get("id") or 0),
    )
