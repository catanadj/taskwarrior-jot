from __future__ import annotations

from dataclasses import dataclass

NOTE_KINDS = frozenset({"task", "chain", "project"})
PROGRESS_OPERATIONS = frozenset({"set", "add", "subtract", "status", "clear"})


@dataclass(frozen=True, slots=True)
class ProgressRequest:
    """Validated CLI request for one progress mutation."""

    kind: str
    reference: str
    operation: str
    value: str = ""
    unit: str | None = None
    status: str | None = None
    track: str = "default"
    confirm_clear: bool = False

    def __post_init__(self) -> None:
        kind = normalize_note_kind(self.kind, context="progress target")
        reference = str(self.reference or "").strip()
        if not reference:
            raise RuntimeError("progress target reference is empty")
        operation = normalize_progress_operation(self.operation)
        value = str(self.value or "").strip()
        track = str(self.track or "default").strip() or "default"
        status = str(self.status or "").strip() or None
        if operation in {"set", "add", "subtract"} and not value:
            raise RuntimeError(f"progress operation '{operation}' requires a value")
        if operation == "status" and not (status or value):
            raise RuntimeError("progress operation 'status' requires a value")
        if operation == "clear":
            if not self.confirm_clear:
                raise RuntimeError("progress clear requires confirmation")
            if value or self.unit or status:
                raise RuntimeError("progress operation 'clear' does not accept a value")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "reference", reference)
        object.__setattr__(self, "operation", operation)
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "track", track)


@dataclass(frozen=True, slots=True)
class ResourceRequest:
    """Validated CLI request for attaching or detaching one resource."""

    kind: str
    reference: str
    target: str = ""
    label: str | None = None
    resource_id: int | None = None
    note_path: str = ""

    def __post_init__(self) -> None:
        kind = normalize_note_kind(self.kind, context="resource target")
        reference = str(self.reference or "").strip()
        if not reference:
            raise RuntimeError("resource target reference is empty")
        target = str(self.target or "").strip()
        note_path = str(self.note_path or "").strip()
        if self.resource_id is None:
            if not target:
                raise RuntimeError("resource attach requires a target")
            if note_path:
                raise RuntimeError("resource attach cannot include a note path")
        else:
            if self.resource_id <= 0:
                raise RuntimeError("resource detach requires a positive resource id")
            if not note_path:
                raise RuntimeError("resource detach requires a note path")
            if target:
                raise RuntimeError("resource detach cannot include a target")
            if self.label:
                raise RuntimeError("resource detach cannot include a label")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "reference", reference)
        object.__setattr__(self, "target", target)
        object.__setattr__(self, "note_path", note_path)


def normalize_note_kind(value: str, *, context: str = "note") -> str:
    normalized = str(value or "").strip().casefold()
    if normalized not in NOTE_KINDS:
        raise RuntimeError(f"unknown {context} kind: {value}")
    return normalized


def normalize_task_note_kind(value: str) -> str:
    normalized = normalize_note_kind(value, context="task progress target")
    if normalized == "project":
        raise RuntimeError("task progress target kind must be task or chain")
    return normalized


def normalize_progress_operation(value: str) -> str:
    normalized = str(value or "").strip().casefold()
    if normalized not in PROGRESS_OPERATIONS:
        raise RuntimeError(f"unknown progress operation: {value}")
    return normalized
