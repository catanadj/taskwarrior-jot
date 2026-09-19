"""Composition for the latest-edits pane."""

from __future__ import annotations


def compose_latest_pane():
    from textual.containers import Vertical
    from textual.widgets import DataTable, Static, TabbedContent, TabPane

    with Vertical(id="latest-pane"):
        recent = DataTable(id="recent-table", cursor_type="row")
        recent.add_columns("ts", "kind", "id", "summary")
        yield Static("Recent Activity", classes="title")
        yield recent
        with TabbedContent(initial="latest-summary-pane", id="latest-workspace-tabs"):
            with TabPane("Summary", id="latest-summary-pane"):
                yield Static("Select a recent row to load details.", id="latest-summary")
            with TabPane("Task Note", id="latest-task-note-pane"):
                yield Static("No task note loaded.", id="latest-task-note-preview")
            with TabPane("Chain Note", id="latest-chain-note-pane"):
                yield Static("No chain note loaded.", id="latest-chain-note-preview")
            with TabPane("Project Note", id="latest-project-note-pane"):
                yield Static("No project note loaded.", id="latest-project-note-preview")
            with TabPane("Events", id="latest-events-pane"):
                yield Static("No events loaded.", id="latest-events-preview")
            with TabPane("Resources", id="latest-resources-pane"):
                yield Static("No resources loaded.", id="latest-resources-preview")
            with TabPane("Progress", id="latest-progress-pane"):
                yield Static("No progress loaded.", id="latest-progress-preview")
