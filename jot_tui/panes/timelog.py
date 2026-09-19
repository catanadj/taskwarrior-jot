"""Composition for the timelog pane."""

from __future__ import annotations


def compose_time_pane():
    from textual.containers import Horizontal, Vertical
    from textual.widgets import Button, DataTable, Select, Static

    with Vertical(id="time-pane"):
        with Vertical(id="time-controls"):
            with Horizontal(id="time-filter-controls"):
                yield Select(
                    [("Today", "today"), ("This week", "week"), ("This month", "month"), ("All time", "all")],
                    value="week",
                    allow_blank=False,
                    id="time-period",
                )
                yield Button("Refresh time", id="time-refresh", variant="primary")
            with Horizontal(id="time-action-controls"):
                yield Button("Add", id="time-add")
                yield Button("Amend", id="time-amend")
                yield Button("Delete", id="time-delete", variant="error")
                yield Button("Trash / Restore", id="time-trash")
        with Vertical(id="time-sessions-block"):
            yield Static("Active timers", id="time-sessions-title", classes="title")
            with Horizontal(id="time-session-controls"):
                yield Button("Start", id="time-session-start", variant="success")
                yield Button("Stop", id="time-session-stop", disabled=True)
                yield Button("Stop all", id="time-session-stop-all", disabled=True)
                yield Button("Cancel", id="time-session-cancel", variant="warning", disabled=True)
            sessions = DataTable(id="time-sessions-table", cursor_type="row")
            sessions.add_columns("elapsed", "task", "description", "project", "started", "chain")
            yield sessions
        yield Static("Loading time expenditure...", id="time-summary")
        with Horizontal(id="time-groups"):
            with Vertical():
                yield Static("By day", classes="title")
                days = DataTable(id="time-day-table", cursor_type="row")
                days.add_columns("day", "time", "entries")
                yield days
            with Vertical():
                yield Static("By project", classes="title")
                projects = DataTable(id="time-project-table", cursor_type="row")
                projects.add_columns("project", "time", "entries")
                yield projects
            with Vertical():
                yield Static("By task", classes="title")
                tasks = DataTable(id="time-task-table", cursor_type="row")
                tasks.add_columns("task", "time", "entries")
                yield tasks
        with Vertical(id="time-details-block"):
            yield Static("Intervals", classes="title")
            details = DataTable(id="time-details-table", cursor_type="row")
            details.add_columns("key", "day", "time", "task", "project", "interval")
            yield details
