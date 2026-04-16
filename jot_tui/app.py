from __future__ import annotations

import asyncio
from typing import Any

from jot_core.services import JotService


def run_tui(service: JotService) -> int:
    try:
        from textual.app import App, ComposeResult
        from textual.containers import Horizontal, Vertical
        from textual.screen import ModalScreen
        from textual.widgets import Button, Checkbox, DataTable, Footer, Header, Input, Label, Static
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
        #dialog Input { margin: 1 0; }
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
        #task-summary, #task-note-preview, #chain-note-preview, #project-note-preview, #task-events-preview, #project-summary, #project-note-body {
            padding: 1;
            height: 1fr;
            overflow: auto;
        }
        #latest-pane { border: round $panel; }
        #search-bar { height: auto; }
        #search-input { margin: 0 1 0 0; width: 1fr; }
        #context-hints { padding: 0 1; color: $text-muted; }
        #recent-table, #tasks-table, #projects-table, #search-notes-table, #search-events-table { height: 1fr; }
        """

        BINDINGS = [
            ("q", "quit", "Quit"),
            ("r", "refresh", "Refresh"),
            ("enter", "open_selected", "Open"),
            ("slash", "focus_search", "Search"),
            ("e", "edit_selected_task_note", "Edit note"),
            ("a", "add_to_selected_task", "Add-to task"),
            ("c", "add_to_selected_chain", "Add-to chain"),
            ("p", "add_to_project_context", "Add-to project"),
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
            self.task_filter_project: str = ""
            self.task_filter_tag: str = ""
            self.task_filter_notes_only: bool = False
            self.current_task_ref: str | None = None
            self.current_task_chain_path: str = ""
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
                                        tasks.add_columns("id", "description", "project", "tags", "notes")
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
                            with TabPane("Projects", id="project-browser-pane"):
                                with Horizontal():
                                    with Vertical(id="browse-projects"):
                                        projects = DataTable(id="projects-table", cursor_type="row")
                                        projects.add_columns("project", "updated")
                                        yield Static("Projects", classes="title")
                                        yield projects
                                    with Vertical(id="project-workspace"):
                                        yield Static("Project Workspace", classes="title")
                                        with TabbedContent(initial="project-summary-pane", id="project-workspace-tabs"):
                                            with TabPane("Summary", id="project-summary-pane"):
                                                yield Static("Select a project row to load details.", id="project-summary")
                                            with TabPane("Project Note", id="project-note-body-pane"):
                                                yield Static("No project note loaded.", id="project-note-body")
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
                    self._open_task_workspace(short_uuid)
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
            if self.current_task_ref:
                asyncio.create_task(self._load_task_async(self.current_task_ref))
            elif self.current_project_name:
                asyncio.create_task(self._load_project_async(self.current_project_name))

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

        def action_add_to_project_context(self) -> None:
            project = self.current_project_name or self.current_task_project
            if not project:
                self.notify("Select a project row or a task with a project", severity="warning")
                return
            self.push_screen(
                AddToHeadingModal(),
                lambda payload: self._on_add_to_payload("project", payload),
            )

        def _on_add_to_payload(self, kind: str, payload: dict[str, Any] | None) -> None:
            if not payload:
                return
            asyncio.create_task(self._apply_add_to_async(kind, payload))

        def on_input_submitted(self, event: Input.Submitted) -> None:
            if event.input.id != "search-input":
                return
            query = event.value.strip()
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
                self._open_task_workspace(short_uuid)
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
                self.current_project_name = str(self.project_rows[row_index].get("project") or "").strip() or None
                if self.current_project_name:
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
            self.project_rows = await asyncio.to_thread(self.svc.projects)
            for item in self.project_rows:
                table.add_row(str(item.get("project") or ""), str(item.get("updated") or ""))

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

        async def _load_task_async(self, task_ref: str) -> None:
            summary = self.query_one("#task-summary", Static)
            task_note = self.query_one("#task-note-preview", Static)
            chain_note = self.query_one("#chain-note-preview", Static)
            project_note = self.query_one("#project-note-preview", Static)
            events_view = self.query_one("#task-events-preview", Static)
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
            self._focus_best_task_workspace_tab(task_note_data, chain_note_data, project_note_data, events)
            self._update_action_hints()

        async def _load_project_async(self, project_name: str) -> None:
            summary = self.query_one("#project-summary", Static)
            note_body = self.query_one("#project-note-body", Static)
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
            if self.current_task_ref:
                await self._load_task_async(self.current_task_ref)

        def _update_action_hints(self) -> None:
            hints = ["Actions: / search", "r refresh", "q quit"]
            if self.current_task_ref:
                hints.extend(["e edit-task", "a add-task"])
            if self.current_task_ref and self.current_task_chain_path:
                hints.append("c add-chain")
            if self.current_project_name or self.current_task_project:
                hints.append("p add-project")
            self.query_one("#context-hints", Static).update(" | ".join(hints))

        def _open_task_workspace(self, task_ref: str) -> None:
            self.current_task_ref = task_ref
            self.current_project_name = None
            self.query_one("#main-tabs", TabbedContent).active = "browse-tab"
            self.query_one("#browse-browser-tabs", TabbedContent).active = "task-browser-pane"
            asyncio.create_task(self._load_task_async(task_ref))
            self._update_action_hints()

        def _open_project_workspace(self, project_name: str) -> None:
            self.current_project_name = project_name
            self.query_one("#main-tabs", TabbedContent).active = "browse-tab"
            self.query_one("#browse-browser-tabs", TabbedContent).active = "project-browser-pane"
            asyncio.create_task(self._load_project_async(project_name))
            self._update_action_hints()

        def _open_active_note_in_editor(self) -> str:
            main_tab = self.query_one("#main-tabs", TabbedContent).active
            if main_tab != "browse-tab":
                raise RuntimeError("open a task or project workspace first")
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
                project = self.current_project_name or self.current_task_project
                if not project:
                    raise RuntimeError("select a project first")
                with self.suspend():
                    return self.svc.open_project_note_in_editor(project)
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
