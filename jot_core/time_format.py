"""Shared formatting for local ISO date-time values."""

from __future__ import annotations

from datetime import datetime


def format_local_iso_datetime(value: datetime) -> str:
    """Format a local datetime as ISO 8601, shortening whole-hour offsets."""
    rendered = value.isoformat()
    if len(rendered) >= 6 and rendered[-6] in "+-" and rendered[-3:] == ":00":
        return rendered[:-3]
    return rendered
