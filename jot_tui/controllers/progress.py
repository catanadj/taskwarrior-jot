"""Progress workflow orchestration independent of Textual widgets."""

from __future__ import annotations

from typing import Any, Mapping


def apply_progress(service: Any, target: Mapping[str, Any], payload: Mapping[str, Any]) -> Any:
    """Apply one progress dialog result through the service boundary."""
    return service.update_progress(
        str(target.get("kind") or ""),
        task_ref=str(target.get("task_ref") or ""),
        project_name=str(target.get("project") or ""),
        operation=str(payload.get("operation") or ""),
        value=str(payload.get("value") or ""),
        unit=str(payload.get("unit") or "") or None,
        status=str(payload.get("status") or "") or None,
        track=str(payload.get("track") or "default"),
        confirm_clear=bool(payload.get("confirm_clear")),
    )
