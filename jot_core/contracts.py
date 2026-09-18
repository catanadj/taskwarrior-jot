from __future__ import annotations


NOTE_KINDS = frozenset({"task", "chain", "project"})
PROGRESS_OPERATIONS = frozenset({"set", "add", "subtract", "status", "clear"})


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
