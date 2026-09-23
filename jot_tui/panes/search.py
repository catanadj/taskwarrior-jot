"""Composition for the search pane."""

from __future__ import annotations


def compose_search_pane():
    from textual.containers import Horizontal, Vertical
    from textual.widgets import DataTable, Input, Static, TabbedContent, TabPane

    with Vertical():
        with Horizontal(id="search-bar"):
            yield Input(placeholder="Search notes/events and press Enter", id="search-input")
        with TabbedContent(initial="search-notes-pane", id="search-results-tabs"):
            with TabPane("Notes", id="search-notes-pane"):
                notes = DataTable(id="search-notes-table", cursor_type="row")
                notes.add_columns("kind", "title", "match")
                yield Static("Search Notes (0)", classes="title", id="search-notes-title")
                yield notes
                yield Static("Enter a search query to find notes.", id="search-notes-detail", markup=False)
            with TabPane("Trash", id="search-trash-pane"):
                trash = DataTable(id="search-trash-table", cursor_type="row")
                trash.add_columns("kind", "title", "match", "original location")
                yield Static("Deleted Notes (0)", classes="title", id="search-trash-title")
                yield trash
                yield Static("Enter a search query to find deleted notes.", id="search-trash-detail", markup=False)
            with TabPane("Events", id="search-events-pane"):
                events = DataTable(id="search-events-table", cursor_type="row")
                events.add_columns("task", "annotation", "ts")
                yield Static("Search Events (0)", classes="title", id="search-events-title")
                yield events
                yield Static("Enter a search query to find events.", id="search-events-detail", markup=False)
