from __future__ import annotations

import asyncio
from dataclasses import asdict
from pathlib import Path
from typing import Any

from jot_core.services import JotService
from jot_core.notes import preview_trash_path
from jot_tui.palette import PaletteEntry, filter_palette_entries


NEW_PROGRESS_TRACK = "__new_progress_track__"


def initial_progress_track(tracks: list[str]) -> str | None:
    normalized = [str(track or "").strip() for track in tracks if str(track or "").strip()]
    if "default" in normalized:
        return "default"
    if len(normalized) == 1:
        return normalized[0]
    return None


def resolve_progress_track(
    selected: str | None,
    new_track: str,
    operation: str,
) -> str:
    if selected == NEW_PROGRESS_TRACK:
        normalized = " ".join(str(new_track or "").strip().split())
        if operation != "set":
            raise RuntimeError("New track can only be used with the set operation")
        if not normalized:
            raise RuntimeError("New track name is required")
        return normalized
    normalized = str(selected or "").strip()
    if not normalized:
        raise RuntimeError("Select a progress track")
    return normalized


def run_tui(service: JotService) -> int:
    try:
        from textual.app import App, ComposeResult
        from textual.containers import Horizontal, Vertical
        from textual.screen import ModalScreen
        from textual.widgets import Button, Checkbox, DataTable, Footer, Header, Input, Label, Select, Static
        from textual.widgets import TabbedContent, TabPane
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "textual is required for `jot tui` (install with: pip install textual)"
        ) from exc

    class AddToHeadingModal(ModalScreen[dict[str, Any] | None]):
        CSS = """
        #dialog {
            width: 70;
            height: auto;
            border: round $panel;
            padding: 1 2;
            background: $surface;
        }
        #dialog Input, #dialog Select { margin: 1 0; }
        #buttons { height: auto; }
        """

        BINDINGS = [("escape", "cancel", "Cancel")]

        def compose(self) -> ComposeResult:
            with Vertical(id="dialog"):
                yield Label("Add entry under heading")
                yield Input(placeholder="Heading, e.g. Notes", id="heading-input")
                yield Input(placeholder="Entry text", id="entry-input")
                yield Checkbox("Create heading if missing", id="create-heading")
                with Horizontal(id="buttons"):
                    yield Button("Cancel", id="cancel-btn")
                    yield Button("Add", id="add-btn", variant="primary")

        def action_cancel(self) -> None:
            self.dismiss(None)

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "cancel-btn":
                self.dismiss(None)
                return
            self._submit()

        def on_input_submitted(self, event: Input.Submitted) -> None:
            if event.input.id == "heading-input":
                self.query_one("#entry-input", Input).focus()
                return
            self._submit()

        def _submit(self) -> None:
            heading = self.query_one("#heading-input", Input).value.strip()
            entry = self.query_one("#entry-input", Input).value.strip()
            create_heading = bool(self.query_one("#create-heading", Checkbox).value)
            if not heading:
                self.app.notify("Heading is required", severity="warning")
                return
            if not entry:
                self.app.notify("Entry text is required", severity="warning")
                return
            self.dismiss(
                {
                    "heading": heading,
                    "entry": entry,
                    "create_heading": create_heading,
                }
            )

    class ConfirmDeleteModal(ModalScreen[bool]):
        CSS = """
        #dialog {
            width: 76;
            height: auto;
            border: round $error;
            padding: 1 2;
            background: $surface;
        }
        #dialog Button { margin: 1 1 0 0; }
        #details { margin: 1 0; color: $text-muted; }
        """

        BINDINGS = [("escape", "cancel", "Cancel")]

        def __init__(self, *, label: str, path: str, trash_path: str) -> None:
            super().__init__()
            self.label = label
            self.path = path
            self.trash_path = trash_path

        def compose(self) -> ComposeResult:
            with Vertical(id="dialog"):
                yield Label(f"Delete {self.label}?")
                yield Static(
                    f"This will move the note to the trash folder.\n\nFrom: {self.path}\nTo:   {self.trash_path}",
                    id="details",
                )
                with Horizontal(id="buttons"):
                    yield Button("Cancel", id="cancel-btn")
                    yield Button("Delete", id="delete-btn", variant="error")

        def action_cancel(self) -> None:
            self.dismiss(False)

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "delete-btn":
                self.dismiss(True)
                return
            self.dismiss(False)

    class AttachResourceModal(ModalScreen[dict[str, str] | None]):
        CSS = """
        #dialog {
            width: 78;
            height: auto;
            border: round $panel;
            padding: 1 2;
            background: $surface;
        }
        #dialog Input { margin: 1 0; }
        #buttons { height: auto; }
        """

        BINDINGS = [("escape", "cancel", "Cancel")]

        def compose(self) -> ComposeResult:
            with Vertical(id="dialog"):
                yield Label("Attach resource to active note")
                yield Input(placeholder="Path or URL", id="resource-target")
                yield Input(placeholder="Optional label", id="resource-label")
                with Horizontal(id="buttons"):
                    yield Button("Cancel", id="cancel-btn")
                    yield Button("Attach", id="attach-btn", variant="primary")

        def action_cancel(self) -> None:
            self.dismiss(None)

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "cancel-btn":
                self.dismiss(None)
                return
            self._submit()

        def on_input_submitted(self, event: Input.Submitted) -> None:
            if event.input.id == "resource-target":
                self.query_one("#resource-label", Input).focus()
                return
            self._submit()

        def _submit(self) -> None:
            target = self.query_one("#resource-target", Input).value.strip()
            label = self.query_one("#resource-label", Input).value.strip()
            if not target:
                self.app.notify("Resource path or URL is required", severity="warning")
                return
            self.dismiss({"target": target, "label": label})

    class ProgressModal(ModalScreen[dict[str, Any] | None]):
        CSS = """
        #dialog {
            width: 78;
            height: auto;
            border: round $accent;
            padding: 1 2;
            background: $surface;
        }
        #dialog Input { margin: 1 0; }
        #progress-help { color: $text-muted; }
        #buttons { height: auto; }
        """

        BINDINGS = [("escape", "cancel", "Cancel")]

        def __init__(
            self,
            *,
            scopes: list[str],
            initial_scope: str,
            tracks_by_scope: dict[str, list[str]],
        ) -> None:
            super().__init__()
            self.scopes = scopes
            self.initial_scope = initial_scope
            self.tracks_by_scope = tracks_by_scope

        def compose(self) -> ComposeResult:
            with Vertical(id="dialog"):
                yield Label("Update progress")
                yield Static(
                    "Operations: set, add, subtract, status, clear\n"
                    "Use separate track names for independent measurements.\n"
                    f"Available scopes: {', '.join(self.scopes)}",
                    id="progress-help",
                )
                yield Select(
                    [(scope.capitalize(), scope) for scope in self.scopes],
                    value=self.initial_scope,
                    allow_blank=False,
                    id="progress-scope",
                )
                yield Select([], prompt="Select track", id="progress-track")
                yield Input(
                    placeholder="New track name (used with set)",
                    id="progress-new-track",
                    disabled=True,
                )
                yield Input(placeholder="Operation", id="progress-operation")
                yield Input(
                    placeholder="Value: 120/350 for set, 20 for add/subtract, text for status",
                    id="progress-value",
                )
                yield Input(placeholder="Optional unit for set", id="progress-unit")
                yield Input(placeholder="Optional status for set", id="progress-status")
                yield Checkbox("Confirm clear", id="progress-confirm-clear")
                with Horizontal(id="buttons"):
                    yield Button("Cancel", id="cancel-btn")
                    yield Button("Apply", id="apply-btn", variant="primary")

        def on_mount(self) -> None:
            self._load_track_options(self.initial_scope)

        def action_cancel(self) -> None:
            self.dismiss(None)

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "cancel-btn":
                self.dismiss(None)
                return
            self._submit()

        def on_input_submitted(self, event: Input.Submitted) -> None:
            order = {
                "progress-new-track": "#progress-operation",
                "progress-operation": "#progress-value",
                "progress-value": "#progress-unit",
                "progress-unit": "#progress-status",
            }
            next_id = order.get(event.input.id or "")
            if next_id:
                self.query_one(next_id, Input).focus()
                return
            self._submit()

        def on_select_changed(self, event: Select.Changed) -> None:
            if event.select.id == "progress-scope":
                self._load_track_options(str(event.value))
                return
            if event.select.id == "progress-track":
                new_track = self.query_one("#progress-new-track", Input)
                is_new = event.value == NEW_PROGRESS_TRACK
                new_track.disabled = not is_new
                if is_new:
                    new_track.focus()

        def _load_track_options(self, scope: str) -> None:
            tracks = self.tracks_by_scope.get(scope, [])
            selector = self.query_one("#progress-track", Select)
            new_track = self.query_one("#progress-new-track", Input)
            new_track.value = ""
            selector.set_options(
                [(track, track) for track in tracks]
                + [("New track...", NEW_PROGRESS_TRACK)]
            )
            initial = initial_progress_track(tracks)
            if initial is not None:
                selector.value = initial
                new_track.disabled = True
            elif not tracks:
                selector.value = NEW_PROGRESS_TRACK
                new_track.disabled = False
            else:
                selector.value = Select.BLANK
                new_track.disabled = True

        def _submit(self) -> None:
            scope_value = self.query_one("#progress-scope", Select).value
            scope = str(scope_value).strip().lower()
            track_value = self.query_one("#progress-track", Select).value
            selected_track = None if track_value is Select.BLANK else str(track_value)
            new_track = self.query_one("#progress-new-track", Input).value
            operation = self.query_one("#progress-operation", Input).value.strip().lower()
            value = self.query_one("#progress-value", Input).value.strip()
            unit = self.query_one("#progress-unit", Input).value.strip()
            status = self.query_one("#progress-status", Input).value.strip()
            confirm_clear = bool(self.query_one("#progress-confirm-clear", Checkbox).value)
            if scope not in self.scopes:
                self.app.notify(f"Scope must be one of: {', '.join(self.scopes)}", severity="warning")
                return
            if operation not in {"set", "add", "subtract", "status", "clear"}:
                self.app.notify("Operation must be set, add, subtract, status, or clear", severity="warning")
                return
            try:
                track = resolve_progress_track(selected_track, new_track, operation)
            except RuntimeError as exc:
                self.app.notify(str(exc), severity="warning")
                return
            if operation != "clear" and not value:
                self.app.notify("Value is required for this operation", severity="warning")
                return
            if operation == "clear" and not confirm_clear:
                self.app.notify("Confirm clear before applying", severity="warning")
                return
            self.dismiss(
                {
                    "scope": scope,
                    "track": track,
                    "operation": operation,
                    "value": value,
                    "unit": unit,
                    "status": status,
                    "confirm_clear": confirm_clear,
                }
            )

    class ResourcePickerModal(ModalScreen[dict[str, Any] | None]):
        CSS = """
        #dialog {
            width: 96;
            height: 28;
            border: round $panel;
            padding: 1 2;
            background: $surface;
        }
        #resource-table { height: 1fr; }
        #buttons { height: auto; }
        """

        BINDINGS = [("escape", "cancel", "Cancel")]

        def __init__(self, *, title: str, resources: list[dict[str, Any]], action_label: str) -> None:
            super().__init__()
            self.title_text = title
            self.resources = resources
            self.action_label = action_label

        def compose(self) -> ComposeResult:
            with Vertical(id="dialog"):
                yield Label(self.title_text)
                table = DataTable(id="resource-table", cursor_type="row")
                table.add_columns("id", "label", "kind", "target")
                yield table
                with Horizontal(id="buttons"):
                    yield Button("Cancel", id="cancel-btn")
                    yield Button(self.action_label, id="action-btn", variant="primary")

        def on_mount(self) -> None:
            table = self.query_one("#resource-table", DataTable)
            for item in self.resources:
                table.add_row(
                    str(item.get("id") or ""),
                    str(item.get("label") or ""),
                    str(item.get("kind") or ""),
                    str(item.get("target") or ""),
                )
            table.focus()

        def action_cancel(self) -> None:
            self.dismiss(None)

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "action-btn":
                self._submit_selected()
                return
            self.dismiss(None)

        def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
            if event.data_table.id != "resource-table":
                return
            self._submit_row(event.cursor_row)

        def _submit_selected(self) -> None:
            table = self.query_one("#resource-table", DataTable)
            self._submit_row(table.cursor_row)

        def _submit_row(self, row: int) -> None:
            if row < 0 or row >= len(self.resources):
                self.dismiss(None)
                return
            self.dismiss(dict(self.resources[row]))

    class CommandPaletteModal(ModalScreen[dict[str, Any] | None]):
        CSS = """
        #dialog {
            width: 88;
            height: 30;
            border: round $panel;
            padding: 1 2;
            background: $surface;
        }
        #palette-input { margin: 1 0; }
        #palette-table { height: 1fr; }
        #palette-buttons { height: auto; }
        """

        BINDINGS = [("escape", "cancel", "Cancel")]

        def __init__(self, entries: list[PaletteEntry]) -> None:
            super().__init__()
            self.entries = entries
            self.filtered_entries = list(entries)

        def compose(self) -> ComposeResult:
            with Vertical(id="dialog"):
                yield Label("Command palette")
                yield Input(placeholder="Type to filter commands", id="palette-input")
                table = DataTable(id="palette-table", cursor_type="row")
                table.add_columns("key", "command", "description")
                yield table
                with Horizontal(id="palette-buttons"):
                    yield Button("Cancel", id="cancel-btn")
                    yield Button("Open", id="open-btn", variant="primary")

        def on_mount(self) -> None:
            self._render()
            self.query_one("#palette-input", Input).focus()

        def action_cancel(self) -> None:
            self.dismiss(None)

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "open-btn":
                self._open_selected()
                return
            self.dismiss(None)

        def on_input_changed(self, event: Input.Changed) -> None:
            if event.input.id != "palette-input":
                return
            self.filtered_entries = filter_palette_entries(self.entries, event.value)
            self._render()

        def on_input_submitted(self, event: Input.Submitted) -> None:
            if event.input.id != "palette-input":
                return
            self._open_selected()

        def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
            if event.data_table.id != "palette-table":
                return
            self._open_row(event.cursor_row)

        def _render(self) -> None:
            table = self.query_one("#palette-table", DataTable)
            table.clear()
            for entry in self.filtered_entries[:20]:
                table.add_row(entry.id, entry.label, entry.detail)

        def _open_selected(self) -> None:
            table = self.query_one("#palette-table", DataTable)
            row = table.cursor_row
            if row < 0:
                row = 0
            self._open_row(row)

        def _open_row(self, row: int) -> None:
            if row < 0 or row >= len(self.filtered_entries):
                self.dismiss(None)
                return
            self.dismiss(asdict(self.filtered_entries[row]))

    class JotTUI(App[None]):
        CSS = """
        Screen { layout: vertical; }
        #browse-top { height: 1fr; }
        #task-browser-pane, #project-browser-pane, #search-tab { height: 1fr; }
        #browse-tasks, #browse-projects { width: 1fr; border: round $panel; }
        #task-workspace, #project-workspace { width: 1fr; border: round $panel; }
        #task-workspace-tabs, #project-workspace-tabs { height: 1fr; }
        #task-filter-bar {
            height: auto;
            padding: 0 1;
        }
        #task-filter-project, #task-filter-tag { width: 1fr; margin: 0 1 0 0; }
        #task-summary, #task-note-preview, #chain-note-preview, #project-note-preview, #task-events-preview, #task-resources-preview, #task-progress-preview, #project-summary, #project-note-body, #project-resources-preview, #project-progress-preview {
            padding: 1;
            height: 1fr;
            overflow: auto;
        }
        #latest-pane { border: round $panel; }
        #latest-workspace-tabs { height: 1fr; }
        #latest-summary, #latest-task-note-preview, #latest-chain-note-preview, #latest-project-note-preview, #latest-events-preview, #latest-resources-preview, #latest-progress-preview {
            padding: 1;
            height: 1fr;
            overflow: auto;
        }
        #search-bar { height: auto; }
        #search-input { margin: 0 1 0 0; width: 1fr; }
        #context-hints { padding: 0 1; color: $text-muted; }
        #recent-table, #tasks-table, #projects-table, #search-notes-table, #search-events-table { height: 1fr; }
        """

        BINDINGS = [
            ("q", "quit", "Quit"),
            ("r", "refresh", "Refresh"),
            ("u", "refresh_current", "Update"),
            ("ctrl+p", "command_palette", "Palette"),
            ("enter", "open_selected", "Open"),
            ("slash", "focus_search", "Search"),
            ("e", "edit_selected_task_note", "Edit note"),
            ("d", "delete_selected_note", "Delete note"),
            ("f", "attach_resource", "Attach resource"),
            ("o", "open_resource", "Open resource"),
            ("x", "detach_resource", "Detach resource"),
            ("g", "update_progress", "Progress"),
            ("a", "add_to_selected_task", "Add-to task"),
            ("c", "add_to_selected_chain", "Add-to chain"),
            ("p", "open_project_context", "Open project"),
        ]

        def __init__(self, svc: JotService) -> None:
            super().__init__()
            self.svc = svc
            self.recent_rows: list[dict[str, Any]] = []
            self.task_all_rows: list[dict[str, Any]] = []
            self.task_rows: list[dict[str, Any]] = []
            self.project_rows: list[dict[str, Any]] = []
            self.search_note_rows: list[dict[str, Any]] = []
            self.search_event_rows: list[dict[str, Any]] = []
            self.current_search_query: str = ""
            self.task_filter_project: str = ""
            self.task_filter_tag: str = ""
            self.task_filter_notes_only: bool = False
            self.current_latest_task_ref: str | None = None
            self.current_task_ref: str | None = None
            self.current_task_chain_path: str = ""
            self.current_task_has_chain: bool = False
            self.current_task_project: str = ""
            self.current_project_name: str | None = None

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            with TabbedContent(initial="browse-tab", id="main-tabs"):
                with TabPane("Browse", id="browse-tab"):
                    with Horizontal(id="browse-top"):
                        with TabbedContent(initial="task-browser-pane", id="browse-browser-tabs"):
                            with TabPane("Tasks", id="task-browser-pane"):
                                with Horizontal():
                                    with Vertical(id="browse-tasks"):
                                        yield Static("Tasks", classes="title")
                                        with Horizontal(id="task-filter-bar"):
                                            yield Input(placeholder="Project filter", id="task-filter-project")
                                            yield Input(placeholder="Tag filter", id="task-filter-tag")
                                            yield Checkbox("Notes only", id="task-filter-notes")
                                            yield Button("Clear", id="task-filter-clear")
                                        tasks = DataTable(id="tasks-table", cursor_type="row")
                                        tasks.add_columns("id", "description", "project", "progress", "tags", "notes")
                                        yield tasks
                                    with Vertical(id="task-workspace"):
                                        yield Static("Task Workspace", classes="title")
                                        with TabbedContent(initial="task-summary-pane", id="task-workspace-tabs"):
                                            with TabPane("Summary", id="task-summary-pane"):
                                                yield Static("Select a task row to load details.", id="task-summary")
                                            with TabPane("Task Note", id="task-note-pane"):
                                                yield Static("No task note loaded.", id="task-note-preview")
                                            with TabPane("Chain Note", id="chain-note-pane"):
                                                yield Static("No chain note loaded.", id="chain-note-preview")
                                            with TabPane("Project Note", id="project-note-pane"):
                                                yield Static("No project note loaded.", id="project-note-preview")
                                            with TabPane("Events", id="task-events-pane"):
                                                yield Static("No events loaded.", id="task-events-preview")
                                            with TabPane("Resources", id="task-resources-pane"):
                                                yield Static("No resources loaded.", id="task-resources-preview")
                                            with TabPane("Progress", id="task-progress-pane"):
                                                yield Static("No progress loaded.", id="task-progress-preview")
                            with TabPane("Projects", id="project-browser-pane"):
                                with Horizontal():
                                    with Vertical(id="browse-projects"):
                                        projects = DataTable(id="projects-table", cursor_type="row")
                                        projects.add_columns("project tree", "tasks", "progress", "note", "updated")
                                        yield Static("Projects", classes="title")
                                        yield projects
                                    with Vertical(id="project-workspace"):
                                        yield Static("Project Workspace", classes="title")
                                        with TabbedContent(initial="project-summary-pane", id="project-workspace-tabs"):
                                            with TabPane("Summary", id="project-summary-pane"):
                                                yield Static("Select a project row to load details.", id="project-summary")
                                            with TabPane("Project Note", id="project-note-body-pane"):
                                                yield Static("No project note loaded.", id="project-note-body")
                                            with TabPane("Resources", id="project-resources-pane"):
                                                yield Static("No resources loaded.", id="project-resources-preview")
                                            with TabPane("Progress", id="project-progress-pane"):
                                                yield Static("No progress loaded.", id="project-progress-preview")
                with TabPane("Search", id="search-tab"):
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
                with TabPane("Latest Edits", id="latest-tab"):
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
            yield Static("Actions: / search | r refresh | q quit", id="context-hints")
            yield Footer()

        async def on_mount(self) -> None:
            await self._refresh_recent_async()
            await self._refresh_tasks_async()
            await self._refresh_projects_async()
            self._update_action_hints()

        async def action_refresh(self) -> None:
            await self._refresh_recent_async()
            await self._refresh_tasks_async()
            await self._refresh_projects_async()
            self._update_action_hints()

        async def action_refresh_current(self) -> None:
            await self._refresh_current_context_async()
            self._update_action_hints()

        def action_command_palette(self) -> None:
            self.push_screen(
                CommandPaletteModal(self._palette_entries()),
                lambda payload: self._on_palette_selected(payload),
            )

        def action_focus_search(self) -> None:
            self.query_one("#main-tabs", TabbedContent).active = "search-tab"
            self.query_one("#search-input", Input).focus()

        def action_open_selected(self) -> None:
            focused = self.focused
            if not isinstance(focused, DataTable):
                return
            table_id = focused.id or ""
            row_index = focused.cursor_row
            if row_index < 0:
                return
            if table_id == "recent-table":
                if row_index >= len(self.recent_rows):
                    return
                short_uuid = str(self.recent_rows[row_index].get("task_short_uuid") or "").strip()
                if short_uuid:
                    self._open_latest_workspace(short_uuid)
                return
            if table_id == "tasks-table":
                if row_index >= len(self.task_rows):
                    return
                short_uuid = str(self.task_rows[row_index].get("short_uuid") or "").strip()
                if short_uuid:
                    self._open_task_workspace(short_uuid)
                return
            if table_id == "projects-table":
                if row_index >= len(self.project_rows):
                    return
                project_name = str(self.project_rows[row_index].get("project") or "").strip()
                if project_name:
                    self.current_project_name = project_name
                if project_name and bool(self.project_rows[row_index].get("selectable")):
                    self._open_project_workspace(project_name)
                return
            if table_id == "search-events-table":
                if row_index >= len(self.search_event_rows):
                    return
                short_uuid = str(self.search_event_rows[row_index].get("task_short_uuid") or "").strip()
                if short_uuid:
                    self._open_task_workspace(short_uuid)
                return
            if table_id == "search-notes-table":
                if row_index >= len(self.search_note_rows):
                    return
                item = self.search_note_rows[row_index]
                kind = str(item.get("kind") or "").strip()
                if kind == "project-note":
                    project_name = str(item.get("project") or "").strip()
                    if project_name:
                        self._open_project_workspace(project_name)
                        return
                if kind == "task-note":
                    short_uuid = str(item.get("task_short_uuid") or "").strip()
                    if short_uuid:
                        self._open_task_workspace(short_uuid)
                        return
                if kind == "chain-note":
                    chain_id = str(item.get("chain_id") or "").strip()
                    if chain_id:
                        try:
                            short_uuid = self.svc.task_ref_for_chain_id(chain_id)
                        except Exception as exc:
                            self.notify(f"Chain open failed: {exc}", severity="error")
                            return
                        self._open_task_workspace(short_uuid)
                        return
                self.notify("This search result has no direct workspace target yet", severity="warning")

        def action_edit_selected_task_note(self) -> None:
            try:
                path = self._open_active_note_in_editor()
            except Exception as exc:
                self.notify(f"Editor failed: {exc}", severity="error")
                return
            self.notify(f"Opened: {path}")
            main_tab = self.query_one("#main-tabs", TabbedContent).active
            if main_tab == "latest-tab" and self.current_latest_task_ref:
                asyncio.create_task(self._load_latest_task_async(self.current_latest_task_ref))
            elif self.current_task_ref:
                asyncio.create_task(self._load_task_async(self.current_task_ref))
            elif self.current_project_name:
                asyncio.create_task(self._load_project_async(self.current_project_name))

        def action_delete_selected_note(self) -> None:
            target = self._active_note_target()
            if target is None:
                self.notify("Select a note tab first", severity="warning")
                return
            self.push_screen(
                ConfirmDeleteModal(
                    label=target["label"],
                    path=target["path"],
                    trash_path=target["trash_path"],
                ),
                lambda confirmed: self._on_delete_confirmed(target, confirmed),
            )

        def action_attach_resource(self) -> None:
            target = self._active_note_target()
            if target is None:
                self.notify("Select a note context first", severity="warning")
                return
            self.push_screen(
                AttachResourceModal(),
                lambda payload: self._on_attach_resource_payload(target, payload),
            )

        def action_open_resource(self) -> None:
            target = self._active_note_target()
            if target is None:
                self.notify("Select a note context first", severity="warning")
                return
            asyncio.create_task(self._choose_resource_async(target, mode="open"))

        def action_detach_resource(self) -> None:
            target = self._active_note_target()
            if target is None:
                self.notify("Select a note context first", severity="warning")
                return
            asyncio.create_task(self._choose_resource_async(target, mode="detach"))

        def action_update_progress(self) -> None:
            targets = self._progress_targets()
            if not targets:
                self.notify("Select a task or project context first", severity="warning")
                return
            asyncio.create_task(self._open_progress_modal_async(targets))

        async def _open_progress_modal_async(self, targets: list[dict[str, Any]]) -> None:
            tracks_by_scope: dict[str, list[str]] = {}
            try:
                for target in targets:
                    kind = str(target.get("kind") or "")
                    tracks_by_scope[kind] = await asyncio.to_thread(
                        self.svc.progress_track_names,
                        kind,
                        task_ref=str(target.get("task_ref") or ""),
                        project_name=str(target.get("project") or ""),
                    )
            except Exception as exc:
                self.notify(f"Could not load progress tracks: {exc}", severity="error")
                return
            scopes = [str(item["kind"]) for item in targets]
            self.push_screen(
                ProgressModal(
                    scopes=scopes,
                    initial_scope=scopes[0],
                    tracks_by_scope=tracks_by_scope,
                ),
                lambda payload: self._on_progress_payload(targets, payload),
            )

        def action_add_to_selected_task(self) -> None:
            if not self.current_task_ref:
                self.notify("Select a task row in Recent first", severity="warning")
                return
            self.push_screen(
                AddToHeadingModal(),
                lambda payload: self._on_add_to_payload("task", payload),
            )

        def action_add_to_selected_chain(self) -> None:
            if not self.current_task_ref:
                self.notify("Select a task row in Recent first", severity="warning")
                return
            if not self.current_task_chain_path:
                self.notify("Selected task has no chain note context", severity="warning")
                return
            self.push_screen(
                AddToHeadingModal(),
                lambda payload: self._on_add_to_payload("chain", payload),
            )

        def action_open_project_context(self) -> None:
            project = self.current_project_name or self.current_task_project
            if not project:
                self.notify("Select a project row or a task with a project", severity="warning")
                return
            self._open_project_workspace(project)

        def _on_palette_selected(self, payload: dict[str, Any] | None) -> None:
            if not payload:
                return
            asyncio.create_task(self._execute_palette_command_async(str(payload.get("id") or "")))

        def _on_add_to_payload(self, kind: str, payload: dict[str, Any] | None) -> None:
            if not payload:
                return
            asyncio.create_task(self._apply_add_to_async(kind, payload))

        def _on_delete_confirmed(self, target: dict[str, Any], confirmed: bool) -> None:
            if not confirmed:
                return
            asyncio.create_task(self._apply_delete_async(target))

        def _on_attach_resource_payload(self, target: dict[str, Any], payload: dict[str, str] | None) -> None:
            if not payload:
                return
            asyncio.create_task(self._apply_attach_resource_async(target, payload))

        def _on_resource_selected(self, target: dict[str, Any], mode: str, resource: dict[str, Any] | None) -> None:
            if not resource:
                return
            if mode == "open":
                asyncio.create_task(self._apply_open_resource_async(resource))
                return
            asyncio.create_task(self._apply_detach_resource_async(target, resource))

        def _on_progress_payload(
            self,
            targets: list[dict[str, Any]],
            payload: dict[str, Any] | None,
        ) -> None:
            if not payload:
                return
            scope = str(payload.get("scope") or "")
            target = next((item for item in targets if item.get("kind") == scope), None)
            if target is None:
                self.notify("Progress scope is no longer available", severity="error")
                return
            asyncio.create_task(self._apply_progress_async(target, payload))


        def on_input_submitted(self, event: Input.Submitted) -> None:
            if event.input.id != "search-input":
                return
            query = event.value.strip()
            self.current_search_query = query
            if not query:
                self.query_one("#search-notes-table", DataTable).clear()
                self.query_one("#search-events-table", DataTable).clear()
                return
            self._run_search(query)

        def on_input_changed(self, event: Input.Changed) -> None:
            if event.input.id == "task-filter-project":
                self.task_filter_project = event.value.strip()
                self._render_tasks_table()
                return
            if event.input.id == "task-filter-tag":
                self.task_filter_tag = event.value.strip()
                self._render_tasks_table()

        def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
            if event.checkbox.id != "task-filter-notes":
                return
            self.task_filter_notes_only = bool(event.value)
            self._render_tasks_table()

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id != "task-filter-clear":
                return
            self.task_filter_project = ""
            self.task_filter_tag = ""
            self.task_filter_notes_only = False
            self.query_one("#task-filter-project", Input).value = ""
            self.query_one("#task-filter-tag", Input).value = ""
            self.query_one("#task-filter-notes", Checkbox).value = False
            self._render_tasks_table()

        def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
            if event.data_table.id == "recent-table":
                row_index = event.cursor_row
                if row_index < 0 or row_index >= len(self.recent_rows):
                    return
                item = self.recent_rows[row_index]
                short_uuid = str(item.get("task_short_uuid") or "").strip()
                if not short_uuid:
                    return
                self._open_latest_workspace(short_uuid)
                return
            if event.data_table.id == "tasks-table":
                row_index = event.cursor_row
                if row_index < 0 or row_index >= len(self.task_rows):
                    return
                short_uuid = str(self.task_rows[row_index].get("short_uuid") or "").strip()
                if not short_uuid:
                    return
                self._open_task_workspace(short_uuid)
                return
            if event.data_table.id == "projects-table":
                row_index = event.cursor_row
                if row_index < 0 or row_index >= len(self.project_rows):
                    return
                project_name = str(self.project_rows[row_index].get("project") or "").strip()
                if not project_name:
                    return
                self.current_project_name = project_name or None
                if self.current_project_name and bool(self.project_rows[row_index].get("selectable")):
                    self._open_project_workspace(self.current_project_name)

        async def _refresh_recent_async(self) -> None:
            table = self.query_one("#recent-table", DataTable)
            table.clear()
            self.recent_rows = await asyncio.to_thread(self.svc.recent, 80)
            for item in self.recent_rows:
                ident = (
                    str(item.get("task_short_uuid") or "").strip()
                    or str(item.get("chain_id") or "").strip()
                    or str(item.get("project") or "").strip()
                )
                summary = (
                    str(item.get("description") or "").strip()
                    or str(item.get("annotation") or "").strip()
                    or str(item.get("path") or "").strip()
                )
                table.add_row(
                    str(item.get("ts") or ""),
                    str(item.get("kind") or ""),
                    ident,
                    summary,
                )

        async def _refresh_tasks_async(self) -> None:
            self.task_all_rows = await asyncio.to_thread(self.svc.tasks, 250)
            self._render_tasks_table()

        async def _refresh_projects_async(self) -> None:
            table = self.query_one("#projects-table", DataTable)
            table.clear()
            self.project_rows = await asyncio.to_thread(self.svc.project_tree_rows)
            for item in self.project_rows:
                table.add_row(
                    str(item.get("label") or item.get("project") or ""),
                    str(item.get("count") or ""),
                    str(item.get("progress") or "-"),
                    str(item.get("note") or ""),
                    str(item.get("updated") or ""),
                )

        def _run_search(self, query: str) -> None:
            asyncio.create_task(self._run_search_async(query))

        def _render_tasks_table(self) -> None:
            table = self.query_one("#tasks-table", DataTable)
            table.clear()
            self.task_rows = [
                item for item in self.task_all_rows if self._task_matches_filters(item)
            ]
            for item in self.task_rows:
                notes = []
                if item.get("has_task_note"):
                    notes.append("task")
                if item.get("has_chain_note"):
                    notes.append("chain")
                if item.get("has_project_note"):
                    notes.append("project")
                table.add_row(
                    str(item.get("short_uuid") or ""),
                    str(item.get("description") or ""),
                    str(item.get("project") or ""),
                    str(item.get("progress") or "-"),
                    ",".join(str(tag) for tag in item.get("tags") or []),
                    ",".join(notes) or "-",
                )

        def _task_matches_filters(self, item: dict[str, Any]) -> bool:
            project_filter = self.task_filter_project.strip().lower()
            if project_filter:
                project = str(item.get("project") or "").strip().lower()
                if project_filter not in project:
                    return False
            tag_filter = self.task_filter_tag.strip().lower()
            if tag_filter:
                tags = [str(tag).strip().lower() for tag in item.get("tags") or []]
                if not any(tag_filter in tag for tag in tags):
                    return False
            if self.task_filter_notes_only and not bool(item.get("has_notes")):
                return False
            return True

        async def _run_search_async(self, query: str) -> None:
            notes_table = self.query_one("#search-notes-table", DataTable)
            events_table = self.query_one("#search-events-table", DataTable)
            notes_table.clear()
            events_table.clear()
            data = await asyncio.to_thread(self.svc.search, query)
            self.search_note_rows = list(data.get("notes", []))
            self.search_event_rows = list(data.get("events", []))
            for item in self.search_note_rows:
                notes_table.add_row(
                    str(item.get("kind") or ""),
                    str(item.get("path") or ""),
                    str(item.get("match") or ""),
                )
            for item in self.search_event_rows:
                events_table.add_row(
                    str(item.get("task_short_uuid") or ""),
                    str(item.get("annotation") or ""),
                    str(item.get("ts") or ""),
                )

        async def _refresh_current_context_async(self) -> None:
            main_tab = self.query_one("#main-tabs", TabbedContent).active
            if main_tab == "browse-tab":
                browse_tab = self.query_one("#browse-browser-tabs", TabbedContent).active
                if browse_tab == "task-browser-pane":
                    if self.current_task_ref:
                        await self._refresh_tasks_async()
                        await self._load_task_async(self.current_task_ref)
                    return
                if browse_tab == "project-browser-pane":
                    await self._refresh_projects_async()
                    if self.current_project_name:
                        await self._load_project_async(self.current_project_name)
                    return
            if main_tab == "latest-tab":
                if self.current_latest_task_ref:
                    await self._refresh_recent_async()
                    await self._load_latest_task_async(self.current_latest_task_ref)
                return
            if main_tab == "search-tab":
                if self.current_search_query:
                    await self._run_search_async(self.current_search_query)
                return
            await self._refresh_recent_async()
            await self._refresh_tasks_async()
            await self._refresh_projects_async()

        async def _execute_palette_command_async(self, command_id: str) -> None:
            if command_id == "browse-tasks":
                self.query_one("#main-tabs", TabbedContent).active = "browse-tab"
                self.query_one("#browse-browser-tabs", TabbedContent).active = "task-browser-pane"
                if self.current_task_ref:
                    await self._load_task_async(self.current_task_ref)
                self._update_action_hints()
                return
            if command_id == "browse-projects":
                self.query_one("#main-tabs", TabbedContent).active = "browse-tab"
                self.query_one("#browse-browser-tabs", TabbedContent).active = "project-browser-pane"
                if self.current_project_name:
                    await self._load_project_async(self.current_project_name)
                self._update_action_hints()
                return
            if command_id == "latest-edits":
                self.query_one("#main-tabs", TabbedContent).active = "latest-tab"
                if self.current_latest_task_ref:
                    await self._load_latest_task_async(self.current_latest_task_ref)
                self._update_action_hints()
                return
            if command_id == "search":
                self.action_focus_search()
                return
            if command_id == "refresh-current":
                await self.action_refresh_current()
                return
            if command_id == "refresh-all":
                await self.action_refresh()
                return
            if command_id == "open-selected":
                self.action_open_selected()
                return
            if command_id == "edit-note":
                self.action_edit_selected_task_note()
                return
            if command_id == "delete-note":
                self.action_delete_selected_note()
                return
            if command_id == "attach-resource":
                self.action_attach_resource()
                return
            if command_id == "open-resource":
                self.action_open_resource()
                return
            if command_id == "detach-resource":
                self.action_detach_resource()
                return
            if command_id == "update-progress":
                self.action_update_progress()
                return
            if command_id == "add-task":
                self.action_add_to_selected_task()
                return
            if command_id == "add-chain":
                self.action_add_to_selected_chain()
                return
            if command_id == "open-project":
                self.action_open_project_context()
                return
            self.notify(f"Unknown palette command: {command_id}", severity="warning")

        async def _load_task_async(self, task_ref: str) -> None:
            summary = self.query_one("#task-summary", Static)
            task_note = self.query_one("#task-note-preview", Static)
            chain_note = self.query_one("#chain-note-preview", Static)
            project_note = self.query_one("#project-note-preview", Static)
            events_view = self.query_one("#task-events-preview", Static)
            resources_view = self.query_one("#task-resources-preview", Static)
            progress_view = self.query_one("#task-progress-preview", Static)
            try:
                data = await asyncio.to_thread(self.svc.task_workspace, task_ref)
            except Exception as exc:
                summary.update(f"Task load failed for {task_ref}\n\n{exc}")
                return
            lines: list[str] = []
            task = data.get("task", {})
            lines.append(f"Task {task.get('short_uuid')}")
            lines.append(f"Description: {task.get('description')}")
            lines.append(f"Project: {task.get('project') or ''}")
            tags = task.get("tags") or []
            if tags:
                lines.append(f"Tags: {', '.join(tags)}")
            nautical = data.get("nautical") or {}
            if nautical:
                lines.append("")
                lines.append("Nautical:")
                for key in ("chain_id", "anchor", "anchor_mode", "link", "cp"):
                    value = nautical.get(key)
                    if value not in (None, "", []):
                        lines.append(f"  {self._pretty_label(key)}: {value}")
            notes = data.get("notes", {})
            task_note_data = notes.get("task") or {}
            chain_note_data = notes.get("chain") or {}
            project_note_data = notes.get("project") or {}
            self.current_task_chain_path = str(chain_note_data.get("path") or "").strip()
            self.current_task_has_chain = bool((data.get("nautical") or {}).get("chain_id"))
            self.current_task_project = str(task.get("project") or "").strip()
            lines.append("")
            events = data.get("events") or []
            lines.append(f"Events: {len(events)} total")
            lines.append(f"Task note: {'present' if task_note_data.get('body') else 'empty'}")
            if chain_note_data.get("path"):
                lines.append(f"Chain note: {'present' if chain_note_data.get('body') else 'empty'}")
            if project_note_data.get("path"):
                lines.append(f"Project note: {'present' if project_note_data.get('body') else 'empty'}")
            summary.update("\n".join(lines))
            task_note.update(self._render_note_panel("Task Note", task_note_data))
            chain_note.update(self._render_note_panel("Chain Note", chain_note_data))
            project_note.update(self._render_note_panel("Project Note", project_note_data))
            events_view.update(self._render_events_panel(events))
            resources_view.update(
                self._render_workspace_resources(
                    [
                        ("task", task_note_data),
                        ("chain", chain_note_data),
                        ("project", project_note_data),
                    ]
                )
            )
            progress_view.update(
                self._render_workspace_progress(
                    [
                        ("task", task_note_data),
                        ("chain", chain_note_data),
                        ("project", project_note_data),
                    ]
                )
            )
            self._focus_best_task_workspace_tab(task_note_data, chain_note_data, project_note_data, events)
            self._update_action_hints()

        async def _load_latest_task_async(self, task_ref: str) -> None:
            summary = self.query_one("#latest-summary", Static)
            task_note = self.query_one("#latest-task-note-preview", Static)
            chain_note = self.query_one("#latest-chain-note-preview", Static)
            project_note = self.query_one("#latest-project-note-preview", Static)
            events_view = self.query_one("#latest-events-preview", Static)
            resources_view = self.query_one("#latest-resources-preview", Static)
            progress_view = self.query_one("#latest-progress-preview", Static)
            try:
                data = await asyncio.to_thread(self.svc.task_workspace, task_ref)
            except Exception as exc:
                summary.update(f"Latest load failed for {task_ref}\n\n{exc}")
                return
            lines: list[str] = []
            task = data.get("task", {})
            lines.append(f"Task {task.get('short_uuid')}")
            lines.append(f"Description: {task.get('description')}")
            lines.append(f"Project: {task.get('project') or ''}")
            tags = task.get("tags") or []
            if tags:
                lines.append(f"Tags: {', '.join(tags)}")
            nautical = data.get("nautical") or {}
            if nautical:
                lines.append("")
                lines.append("Nautical:")
                for key in ("chain_id", "anchor", "anchor_mode", "link", "cp"):
                    value = nautical.get(key)
                    if value not in (None, "", []):
                        lines.append(f"  {self._pretty_label(key)}: {value}")
            notes = data.get("notes", {})
            task_note_data = notes.get("task") or {}
            chain_note_data = notes.get("chain") or {}
            project_note_data = notes.get("project") or {}
            self.current_latest_task_ref = task_ref
            self.current_task_chain_path = str(chain_note_data.get("path") or "").strip()
            self.current_task_has_chain = bool((data.get("nautical") or {}).get("chain_id"))
            self.current_task_project = str(task.get("project") or "").strip()
            lines.append("")
            events = data.get("events") or []
            lines.append(f"Events: {len(events)} total")
            lines.append(f"Task note: {'present' if task_note_data.get('body') else 'empty'}")
            if chain_note_data.get("path"):
                lines.append(f"Chain note: {'present' if chain_note_data.get('body') else 'empty'}")
            if project_note_data.get("path"):
                lines.append(f"Project note: {'present' if project_note_data.get('body') else 'empty'}")
            summary.update("\n".join(lines))
            task_note.update(self._render_note_panel("Task Note", task_note_data))
            chain_note.update(self._render_note_panel("Chain Note", chain_note_data))
            project_note.update(self._render_note_panel("Project Note", project_note_data))
            events_view.update(self._render_events_panel(events))
            resources_view.update(
                self._render_workspace_resources(
                    [
                        ("task", task_note_data),
                        ("chain", chain_note_data),
                        ("project", project_note_data),
                    ]
                )
            )
            progress_view.update(
                self._render_workspace_progress(
                    [
                        ("task", task_note_data),
                        ("chain", chain_note_data),
                        ("project", project_note_data),
                    ]
                )
            )
            self._focus_best_latest_workspace_tab(task_note_data, chain_note_data, project_note_data, events)
            self._update_action_hints()

        async def _load_project_async(self, project_name: str) -> None:
            summary = self.query_one("#project-summary", Static)
            note_body = self.query_one("#project-note-body", Static)
            resources_view = self.query_one("#project-resources-preview", Static)
            progress_view = self.query_one("#project-progress-preview", Static)
            data = await asyncio.to_thread(self.svc.project_workspace, project_name)
            note = data.get("note") or {}
            body = str(note.get("body") or "").strip()
            summary.update(
                "\n".join(
                    [
                        f"Project {project_name}",
                        "",
                        f"Note: {note.get('path') or ''}",
                        "",
                        f"Status: {'present' if body else 'empty'}",
                    ]
                )
            )
            note_body.update(self._render_note_panel("Project Note", note))
            resources_view.update(self._render_workspace_resources([("project", note)]))
            progress_view.update(self._render_workspace_progress([("project", note)]))
            self._focus_best_project_workspace_tab(note)
            self._update_action_hints()

        async def _apply_add_to_async(self, kind: str, payload: dict[str, Any]) -> None:
            try:
                if kind == "task":
                    if not self.current_task_ref:
                        self.notify("Select a task row in Recent first", severity="warning")
                        return
                    result = await asyncio.to_thread(
                        self.svc.add_to_task_heading,
                        self.current_task_ref,
                        heading=str(payload.get("heading") or ""),
                        text=str(payload.get("entry") or ""),
                        create_heading=bool(payload.get("create_heading")),
                        exact=False,
                    )
                elif kind == "chain":
                    if not self.current_task_ref:
                        self.notify("Select a task row in Recent first", severity="warning")
                        return
                    result = await asyncio.to_thread(
                        self.svc.add_to_chain_heading,
                        self.current_task_ref,
                        heading=str(payload.get("heading") or ""),
                        text=str(payload.get("entry") or ""),
                        create_heading=bool(payload.get("create_heading")),
                        exact=False,
                    )
                else:
                    project = self.current_project_name or self.current_task_project
                    if not project:
                        self.notify("Select a project row or a task with a project", severity="warning")
                        return
                    result = await asyncio.to_thread(
                        self.svc.add_to_project_heading,
                        project,
                        heading=str(payload.get("heading") or ""),
                        text=str(payload.get("entry") or ""),
                        create_heading=bool(payload.get("create_heading")),
                        exact=False,
                    )
            except Exception as exc:
                self.notify(f"Add-to failed: {exc}", severity="error")
                return
            self.notify(
                f"Added under {result.get('heading')} ({result.get('heading_match')})",
                severity="information",
            )
            await self._refresh_recent_async()
            await self._refresh_tasks_async()
            await self._refresh_projects_async()
            main_tab = self.query_one("#main-tabs", TabbedContent).active
            if main_tab == "latest-tab" and self.current_latest_task_ref:
                await self._load_latest_task_async(self.current_latest_task_ref)
            elif self.current_task_ref:
                await self._load_task_async(self.current_task_ref)

        async def _choose_resource_async(self, target: dict[str, Any], *, mode: str) -> None:
            resources = await asyncio.to_thread(self.svc.note_resources, str(target.get("path") or ""))
            if not resources:
                self.notify("Active note has no resources", severity="warning")
                return
            title = "Open resource" if mode == "open" else "Detach resource"
            action_label = "Open" if mode == "open" else "Detach"
            self.push_screen(
                ResourcePickerModal(title=title, resources=resources, action_label=action_label),
                lambda resource: self._on_resource_selected(target, mode, resource),
            )

        async def _apply_attach_resource_async(self, target: dict[str, Any], payload: dict[str, str]) -> None:
            try:
                result = await asyncio.to_thread(
                    self.svc.attach_resource,
                    str(target.get("kind") or ""),
                    task_ref=str(target.get("task_ref") or ""),
                    project_name=str(target.get("project") or ""),
                    target=str(payload.get("target") or ""),
                    label=str(payload.get("label") or "") or None,
                )
            except Exception as exc:
                self.notify(f"Attach failed: {exc}", severity="error")
                return
            resource = result.get("resource") or {}
            self.notify(f"Attached: {resource.get('label') or resource.get('target')}", severity="information")
            await self._refresh_after_resource_change_async()

        async def _apply_open_resource_async(self, resource: dict[str, Any]) -> None:
            target = str(resource.get("target") or "").strip()
            if not target:
                self.notify("Resource has no target", severity="warning")
                return
            try:
                with self.suspend():
                    await asyncio.to_thread(self.svc.open_resource, target)
            except Exception as exc:
                self.notify(f"Open resource failed: {exc}", severity="error")
                return
            self.notify(f"Opened resource: {target}", severity="information")

        async def _apply_detach_resource_async(self, target: dict[str, Any], resource: dict[str, Any]) -> None:
            try:
                result = await asyncio.to_thread(
                    self.svc.detach_resource,
                    str(target.get("kind") or ""),
                    task_ref=str(target.get("task_ref") or ""),
                    project_name=str(target.get("project") or ""),
                    note_path=str(target.get("path") or ""),
                    resource_id=int(resource.get("id") or 0),
                )
            except Exception as exc:
                self.notify(f"Detach failed: {exc}", severity="error")
                return
            removed = result.get("resource") or {}
            self.notify(f"Detached: {removed.get('label') or removed.get('target')}", severity="information")
            await self._refresh_after_resource_change_async()

        async def _refresh_after_resource_change_async(self) -> None:
            await self._refresh_recent_async()
            await self._refresh_tasks_async()
            await self._refresh_projects_async()
            main_tab = self.query_one("#main-tabs", TabbedContent).active
            if main_tab == "latest-tab" and self.current_latest_task_ref:
                await self._load_latest_task_async(self.current_latest_task_ref)
            elif self.current_project_name and self.query_one("#browse-browser-tabs", TabbedContent).active == "project-browser-pane":
                await self._load_project_async(self.current_project_name)
            elif self.current_task_ref:
                await self._load_task_async(self.current_task_ref)

        async def _apply_progress_async(self, target: dict[str, Any], payload: dict[str, Any]) -> None:
            try:
                result = await asyncio.to_thread(
                    self.svc.update_progress,
                    str(target.get("kind") or ""),
                    task_ref=str(target.get("task_ref") or ""),
                    project_name=str(target.get("project") or ""),
                    operation=str(payload.get("operation") or ""),
                    value=str(payload.get("value") or ""),
                    unit=str(payload.get("unit") or "") or None,
                    status=str(payload.get("status") or "") or None,
                    track=str(payload.get("track") or "default"),
                    confirm_clear=bool(payload.get("confirm_clear")),
                )
            except Exception as exc:
                self.notify(f"Progress update failed: {exc}", severity="error")
                return
            progress = result.get("progress")
            if isinstance(progress, dict):
                measurement = f"{progress.get('current')}/{progress.get('target')}"
                unit = str(progress.get("unit") or "").strip()
                if unit:
                    measurement += f" {unit}"
                track = str(result.get("track") or "default")
                self.notify(f"Progress updated [{track}]: {measurement}", severity="information")
            else:
                track = str(result.get("track") or "default")
                self.notify(f"Progress track cleared: {track}", severity="information")
            await self._refresh_after_resource_change_async()

        def _update_action_hints(self) -> None:
            hints = ["Actions: ctrl+p palette", "/ search", "r refresh", "u update", "q quit"]
            if self.current_task_ref or self.current_latest_task_ref or self.current_project_name:
                hints.append("d delete-note")
                hints.extend(["f attach-resource", "o open-resource", "x detach-resource"])
            if self._progress_targets():
                hints.append("g progress")
            if self.current_task_ref:
                hints.extend(["e edit-task", "a add-task"])
            if self.current_task_ref and self.current_task_chain_path:
                hints.append("c add-chain")
            if self.current_project_name or self.current_task_project:
                hints.append("p open-project")
            self.query_one("#context-hints", Static).update(" | ".join(hints))

        def _palette_entries(self) -> list[PaletteEntry]:
            entries = [
                PaletteEntry("browse-tasks", "Browse tasks", "Open the task browser workspace"),
                PaletteEntry("browse-projects", "Browse projects", "Open the project browser workspace"),
                PaletteEntry("latest-edits", "Latest edits", "Open the recent activity workspace"),
                PaletteEntry("search", "Search", "Focus the search tab and input"),
                PaletteEntry("refresh-current", "Refresh current", "Reload the active workspace"),
                PaletteEntry("refresh-all", "Refresh all", "Reload tasks, projects, and recent activity"),
                PaletteEntry("open-selected", "Open selected row", "Jump into the selected task, project, or recent item"),
                PaletteEntry("edit-note", "Edit active note", "Open the active note in your editor", bool(self._active_note_target())),
                PaletteEntry("delete-note", "Delete active note", "Move the active note to trash", bool(self._active_note_target())),
                PaletteEntry("attach-resource", "Attach resource", "Attach a file path or URL to the active note", bool(self._active_note_target())),
                PaletteEntry("open-resource", "Open note resource", "Open a resource from the active note", bool(self._active_note_target())),
                PaletteEntry("detach-resource", "Detach note resource", "Remove a resource from the active note", bool(self._active_note_target())),
                PaletteEntry("update-progress", "Update progress", "Set or adjust progress for the current task, chain, or project", bool(self._progress_targets())),
                PaletteEntry("add-task", "Add to task heading", "Add a timestamped entry under the selected task note", bool(self.current_task_ref)),
                PaletteEntry("add-chain", "Add to chain heading", "Add a timestamped entry under the selected chain note", bool(self.current_task_ref and self.current_task_chain_path)),
                PaletteEntry("open-project", "Open project workspace", "Open the selected or current project note", bool(self.current_project_name or self.current_task_project)),
            ]
            return entries

        def _progress_targets(self) -> list[dict[str, Any]]:
            main_tab = self.query_one("#main-tabs", TabbedContent).active
            if main_tab not in {"browse-tab", "latest-tab"}:
                return []
            if main_tab == "browse-tab":
                browse_tab = self.query_one("#browse-browser-tabs", TabbedContent).active
                if browse_tab == "project-browser-pane":
                    project = self.current_project_name
                    return [{"kind": "project", "project": project}] if project else []
            task_ref = self.current_latest_task_ref if main_tab == "latest-tab" else self.current_task_ref
            if not task_ref:
                return []
            targets: list[dict[str, Any]] = [{"kind": "task", "task_ref": task_ref}]
            if self.current_task_has_chain:
                targets.append({"kind": "chain", "task_ref": task_ref})
            if self.current_task_project:
                targets.append({"kind": "project", "project": self.current_task_project})
            return targets

        def _active_note_target(self) -> dict[str, Any] | None:
            main_tab = self.query_one("#main-tabs", TabbedContent).active
            if main_tab == "browse-tab":
                browse_tab = self.query_one("#browse-browser-tabs", TabbedContent).active
                if browse_tab == "task-browser-pane":
                    if not self.current_task_ref:
                        return None
                    active = self.query_one("#task-workspace-tabs", TabbedContent).active
                    if active == "chain-note-pane":
                        note_path = self.svc.chain_note_path_for_task_ref(self.current_task_ref)
                        return {
                            "kind": "chain",
                            "label": "chain note",
                            "task_ref": self.current_task_ref,
                            "path": note_path,
                            "trash_path": str(preview_trash_path(self.svc.config, Path(note_path))),
                        }
                    if active == "project-note-pane":
                        project = self.current_task_project or self.current_project_name
                        if not project:
                            return None
                        note_path = self.svc.project_note_path_for_name(project)
                        return {
                            "kind": "project",
                            "label": "project note",
                            "project": project,
                            "path": note_path,
                            "trash_path": str(preview_trash_path(self.svc.config, Path(note_path))),
                        }
                    note_path = self.svc.task_note_path_for_task_ref(self.current_task_ref)
                    return {
                        "kind": "task",
                        "label": "task note",
                        "task_ref": self.current_task_ref,
                        "path": note_path,
                        "trash_path": str(preview_trash_path(self.svc.config, Path(note_path))),
                    }
                if browse_tab == "project-browser-pane":
                    project = self.current_project_name or self.current_task_project
                    if not project:
                        return None
                    note_path = self.svc.project_note_path_for_name(project)
                    return {
                        "kind": "project",
                        "label": "project note",
                        "project": project,
                        "path": note_path,
                        "trash_path": str(preview_trash_path(self.svc.config, Path(note_path))),
                    }
            if main_tab == "latest-tab":
                if not self.current_latest_task_ref:
                    return None
                active = self.query_one("#latest-workspace-tabs", TabbedContent).active
                if active == "latest-chain-note-pane":
                    note_path = self.svc.chain_note_path_for_task_ref(self.current_latest_task_ref)
                    return {
                        "kind": "chain",
                        "label": "chain note",
                        "task_ref": self.current_latest_task_ref,
                        "path": note_path,
                        "trash_path": str(preview_trash_path(self.svc.config, Path(note_path))),
                    }
                if active == "latest-project-note-pane":
                    project = self.current_task_project
                    if not project:
                        return None
                    note_path = self.svc.project_note_path_for_name(project)
                    return {
                        "kind": "project",
                        "label": "project note",
                        "project": project,
                        "path": note_path,
                        "trash_path": str(preview_trash_path(self.svc.config, Path(note_path))),
                    }
                note_path = self.svc.task_note_path_for_task_ref(self.current_latest_task_ref)
                return {
                    "kind": "task",
                    "label": "task note",
                    "task_ref": self.current_latest_task_ref,
                    "path": note_path,
                    "trash_path": str(preview_trash_path(self.svc.config, Path(note_path))),
                }
            return None

        async def _apply_delete_async(self, target: dict[str, Any]) -> None:
            try:
                kind = str(target.get("kind") or "")
                if kind == "task":
                    result = await asyncio.to_thread(self.svc.delete_task_note, str(target.get("task_ref") or ""))
                elif kind == "chain":
                    result = await asyncio.to_thread(self.svc.delete_chain_note, str(target.get("task_ref") or ""))
                elif kind == "project":
                    result = await asyncio.to_thread(self.svc.delete_project_note, str(target.get("project") or ""))
                else:
                    raise RuntimeError("unknown delete target")
            except Exception as exc:
                self.notify(f"Delete failed: {exc}", severity="error")
                return
            self.notify(
                f"Moved to trash: {result.get('trash_path')}",
                severity="information",
            )
            await self._refresh_recent_async()
            await self._refresh_tasks_async()
            await self._refresh_projects_async()
            main_tab = self.query_one("#main-tabs", TabbedContent).active
            if main_tab == "latest-tab" and self.current_latest_task_ref:
                await self._load_latest_task_async(self.current_latest_task_ref)
            elif self.current_task_ref:
                await self._load_task_async(self.current_task_ref)
            elif self.current_project_name:
                await self._load_project_async(self.current_project_name)

        def _open_task_workspace(self, task_ref: str) -> None:
            self.current_task_ref = task_ref
            self.current_project_name = None
            self.query_one("#main-tabs", TabbedContent).active = "browse-tab"
            self.query_one("#browse-browser-tabs", TabbedContent).active = "task-browser-pane"
            asyncio.create_task(self._load_task_async(task_ref))
            self._update_action_hints()

        def _open_latest_workspace(self, task_ref: str) -> None:
            self.current_latest_task_ref = task_ref
            self.current_task_ref = task_ref
            self.current_project_name = None
            self.query_one("#main-tabs", TabbedContent).active = "latest-tab"
            asyncio.create_task(self._load_latest_task_async(task_ref))
            self._update_action_hints()

        def _open_project_workspace(self, project_name: str) -> None:
            self.current_project_name = project_name
            self.query_one("#main-tabs", TabbedContent).active = "browse-tab"
            self.query_one("#browse-browser-tabs", TabbedContent).active = "project-browser-pane"
            asyncio.create_task(self._load_project_async(project_name))
            self._update_action_hints()

        def _open_active_note_in_editor(self) -> str:
            main_tab = self.query_one("#main-tabs", TabbedContent).active
            if main_tab == "browse-tab":
                browse_tab = self.query_one("#browse-browser-tabs", TabbedContent).active
                if browse_tab == "task-browser-pane":
                    if not self.current_task_ref:
                        raise RuntimeError("select a task first")
                    active = self.query_one("#task-workspace-tabs", TabbedContent).active
                    with self.suspend():
                        if active == "chain-note-pane":
                            return self.svc.open_chain_note_in_editor(self.current_task_ref)
                        if active == "project-note-pane":
                            project = self.current_task_project or self.current_project_name
                            if not project:
                                raise RuntimeError("selected task has no project note context")
                            return self.svc.open_project_note_in_editor(project)
                        return self.svc.open_task_note_in_editor(self.current_task_ref)
                if browse_tab == "project-browser-pane":
                    project = self.current_project_name
                    if not project:
                        raise RuntimeError("select a project first")
                    with self.suspend():
                        return self.svc.open_project_note_in_editor(project)
            if main_tab == "latest-tab":
                if not self.current_latest_task_ref:
                    raise RuntimeError("select a recent task first")
                active = self.query_one("#latest-workspace-tabs", TabbedContent).active
                with self.suspend():
                    if active == "latest-chain-note-pane":
                        return self.svc.open_chain_note_in_editor(self.current_latest_task_ref)
                    if active == "latest-project-note-pane":
                        project = self.current_task_project
                        if not project:
                            raise RuntimeError("selected recent task has no project note context")
                        return self.svc.open_project_note_in_editor(project)
                    return self.svc.open_task_note_in_editor(self.current_latest_task_ref)
            raise RuntimeError("no openable workspace is active")

        def _focus_best_task_workspace_tab(
            self,
            task_note: dict[str, Any],
            chain_note: dict[str, Any],
            project_note: dict[str, Any],
            events: list[dict[str, Any]],
        ) -> None:
            tabs = self.query_one("#task-workspace-tabs", TabbedContent)
            if str(task_note.get("body") or "").strip():
                tabs.active = "task-note-pane"
            elif str(chain_note.get("body") or "").strip():
                tabs.active = "chain-note-pane"
            elif str(project_note.get("body") or "").strip():
                tabs.active = "project-note-pane"
            elif events:
                tabs.active = "task-events-pane"
            else:
                tabs.active = "task-summary-pane"

        def _focus_best_project_workspace_tab(self, note: dict[str, Any]) -> None:
            tabs = self.query_one("#project-workspace-tabs", TabbedContent)
            if str(note.get("body") or "").strip():
                tabs.active = "project-note-body-pane"
            else:
                tabs.active = "project-summary-pane"

        def _focus_best_latest_workspace_tab(
            self,
            task_note: dict[str, Any],
            chain_note: dict[str, Any],
            project_note: dict[str, Any],
            events: list[dict[str, Any]],
        ) -> None:
            tabs = self.query_one("#latest-workspace-tabs", TabbedContent)
            if str(task_note.get("body") or "").strip():
                tabs.active = "latest-task-note-pane"
            elif str(chain_note.get("body") or "").strip():
                tabs.active = "latest-chain-note-pane"
            elif str(project_note.get("body") or "").strip():
                tabs.active = "latest-project-note-pane"
            elif events:
                tabs.active = "latest-events-pane"
            else:
                tabs.active = "latest-summary-pane"

        def _render_note_panel(self, title: str, note: dict[str, Any]) -> str:
            path = str(note.get("path") or "").strip()
            body = str(note.get("body") or "").strip()
            lines = [title, ""]
            lines.append(f"Path: {path or '(none)'}")
            lines.append("")
            lines.append(self._note_excerpt(body) or "(empty)")
            return "\n".join(lines)

        def _render_events_panel(self, events: list[dict[str, Any]]) -> str:
            if not events:
                return "Events\n\n(none)"
            lines = ["Events", ""]
            for item in events[:12]:
                entry = str(item.get("entry") or "").strip()
                desc = str(item.get("description") or "").strip()
                lines.append(f"{entry}  {desc}".strip())
            return "\n".join(lines)

        def _render_workspace_resources(self, note_items: list[tuple[str, dict[str, Any]]]) -> str:
            lines = ["Resources", ""]
            found = False
            for label, note in note_items:
                path = str(note.get("path") or "").strip()
                resources = note.get("resources") or []
                if not path and not resources:
                    continue
                lines.append(f"{label.capitalize()} note")
                if path:
                    lines.append(f"Path: {path}")
                if not resources:
                    lines.append("  (none)")
                    lines.append("")
                    continue
                found = True
                for item in resources:
                    name = str(item.get("label") or item.get("target") or "").strip()
                    kind = str(item.get("kind") or "resource").strip()
                    status = str(item.get("status") or "").strip()
                    target = str(item.get("target") or "").strip()
                    suffix = f"[{kind}]"
                    if status and status != "unchecked":
                        suffix += f" {status}"
                    lines.append(f"  {item.get('id')}. {name} {suffix}")
                    if target and target != name:
                        lines.append(f"     {target}")
                lines.append("")
            if not found and len(lines) == 2:
                lines.append("(none)")
            lines.append("Actions: f attach | o open | x detach")
            return "\n".join(lines).strip()

        def _render_workspace_progress(self, note_items: list[tuple[str, dict[str, Any]]]) -> str:
            lines = ["Progress", ""]
            found = False
            for label, note in note_items:
                tracks = note.get("progress_tracks")
                if not isinstance(tracks, list):
                    progress = note.get("progress")
                    tracks = [progress] if isinstance(progress, dict) else []
                if not tracks:
                    continue
                lines.append(f"{label.capitalize()} note")
                for progress in tracks:
                    if not isinstance(progress, dict):
                        continue
                    found = True
                    track = str(progress.get("track") or "default")
                    current = str(progress.get("current") or "0")
                    target = str(progress.get("target") or "0")
                    unit = str(progress.get("unit") or "").strip()
                    status = str(progress.get("status") or "").strip()
                    percentage = progress.get("percentage")
                    measurement = f"{current}/{target}"
                    if unit:
                        measurement += f" {unit}"
                    lines.append(f"  [{track}] {measurement}")
                    if percentage is not None:
                        lines.append(f"    {self._progress_bar(str(percentage))} {percentage}%")
                    if status:
                        lines.append(f"    Status: {status}")
                    if progress.get("updated"):
                        lines.append(f"    Updated: {progress.get('updated')}")
                lines.append("")
            if not found:
                lines.append("(not set)")
                lines.append("")
            lines.append("Action: g set, adjust, change status, or clear")
            return "\n".join(lines).strip()

        def _progress_bar(self, percentage: str, width: int = 24) -> str:
            try:
                value = float(percentage)
            except (TypeError, ValueError):
                value = 0.0
            clamped = max(0.0, min(100.0, value))
            filled = round((clamped / 100.0) * width)
            return "[" + "#" * filled + "-" * (width - filled) + "]"

        def _note_excerpt(self, body: str, *, max_lines: int = 16, max_width: int = 92) -> str:
            cleaned: list[str] = []
            for raw in str(body or "").splitlines():
                line = raw.rstrip()
                if not line.strip():
                    if cleaned and cleaned[-1] != "":
                        cleaned.append("")
                    continue
                cleaned.append(line)
                if len(cleaned) >= max_lines:
                    break
            if not cleaned:
                return ""
            out: list[str] = []
            for line in cleaned[:max_lines]:
                out.append(line if len(line) <= max_width else line[: max_width - 3] + "...")
            return "\n".join(out).strip()

        def _pretty_label(self, key: str) -> str:
            return str(key).replace("_", " ").capitalize()

    app = JotTUI(service)
    app.run()
    return 0
