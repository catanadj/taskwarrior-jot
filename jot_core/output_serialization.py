from __future__ import annotations

from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any, Mapping


def serialize_payload(value: Any) -> Any:
    """Convert typed results and Python containers into JSON-compatible data."""
    if hasattr(value, "to_payload") and callable(value.to_payload):
        return serialize_payload(value.to_payload())
    if is_dataclass(value):
        return {
            item.name: serialize_payload(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): serialize_payload(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [serialize_payload(item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise TypeError(f"cannot serialize result value of type {type(value).__name__}")


def success_envelope(
    schema: str,
    data: Any,
    warnings: tuple[str, ...] | list[str] = (),
) -> dict[str, Any]:
    """Build the versioned machine-readable success response."""
    return {
        "schema": str(schema),
        "schema_version": 1,
        "ok": True,
        "data": serialize_payload(data),
        "warnings": [str(item) for item in warnings],
    }


def error_envelope(
    schema: str,
    code: str,
    message: str,
    details: Any = None,
) -> dict[str, Any]:
    """Build the versioned machine-readable error response."""
    error: dict[str, Any] = {"code": str(code), "message": str(message)}
    if details is not None:
        error["details"] = details
    return {
        "schema": str(schema),
        "schema_version": 1,
        "ok": False,
        "error": error,
    }
