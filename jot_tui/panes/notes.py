"""Composition for the note inventory pane."""

from __future__ import annotations


def compose_notes_pane():
    from textual.containers import Horizontal, Vertical
    from textual.widgets import Button, DataTable, Input, Static

    with Vertical(id="notes-pane"):
        yield Static("Notes", classes="title")
        with Horizontal(id="notes-filter-bar"):
            yield Input(placeholder="Kind filter: task, chain, project", id="notes-filter-kind")
            yield Input(placeholder="Project filter", id="notes-filter-project")
            yield Button("Clear", id="notes-filter-clear")
        notes = DataTable(id="notes-table", cursor_type="row")
        notes.add_columns("kind", "id", "title", "project", "progress", "resources", "updated")
        yield notes
