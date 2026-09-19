"""Composition for the search pane."""

from __future__ import annotations


def compose_search_pane():
    from textual.containers import Horizontal, Vertical
    from textual.widgets import DataTable, Input, Static

    with Vertical():
        with Horizontal(id="search-bar"):
            yield Input(placeholder="Search notes/events and press Enter", id="search-input")
        with Horizontal():
            with Vertical():
                notes = DataTable(id="search-notes-table", cursor_type="row")
                notes.add_columns("kind", "path", "match")
                yield Static("Search Notes", classes="title")
                yield notes
            with Vertical():
                events = DataTable(id="search-events-table", cursor_type="row")
                events.add_columns("task", "annotation", "ts")
                yield Static("Search Events", classes="title")
                yield events
