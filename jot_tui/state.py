"""Typed state owned by the Textual application shell."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class TuiState:
    recent_rows: list[dict[str, Any]] = field(default_factory=list)
    task_all_rows: list[dict[str, Any]] = field(default_factory=list)
    task_rows: list[dict[str, Any]] = field(default_factory=list)
    project_rows: list[dict[str, Any]] = field(default_factory=list)
    note_rows: list[dict[str, Any]] = field(default_factory=list)
    search_note_rows: list[dict[str, Any]] = field(default_factory=list)
    search_event_rows: list[dict[str, Any]] = field(default_factory=list)
    time_session_rows: list[dict[str, Any]] = field(default_factory=list)
    time_rows: list[dict[str, Any]] = field(default_factory=list)
    time_period: str = "week"
    current_search_query: str = ""
    note_filter_kind: str = ""
    note_filter_project: str = ""
    task_filter_project: str = ""
    task_filter_tag: str = ""
    task_filter_notes_only: bool = False
    current_latest_task_ref: str | None = None
    current_task_ref: str | None = None
    current_task_chain_path: str = ""
    current_task_has_chain: bool = False
    current_task_project: str = ""
    current_project_name: str | None = None
    current_context_has_resources: bool = False
    current_context_has_progress: bool = False
