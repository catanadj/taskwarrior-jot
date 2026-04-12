from __future__ import annotations

from typing import Any

from jot_core.services import JotService


def run_tui(service: JotService) -> int:
    try:
        from textual.app import App, ComposeResult
        from textual.containers import Horizontal, Vertical
        from textual.screen import ModalScreen
        from textual.widgets import Button, Checkbox, DataTable, Footer, Header, Input, Label, Static
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
        #top { height: 1fr; }
        #left { width: 2fr; border: round $panel; }
        #right { width: 3fr; border: round $panel; }
        #search-input { margin: 0 1; }
        #task-detail { padding: 1; }
        #recent-table, #projects-table, #search-notes-table, #search-events-table { height: 1fr; }
        """

        BINDINGS = [
            ("q", "quit", "Quit"),
            ("r", "refresh", "Refresh"),
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
            self.current_task_ref: str | None = None
            self.current_task_chain_path: str = ""
            self.current_task_project: str = ""
            self.current_project_name: str | None = None

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            yield Input(placeholder="Search notes/events and press Enter", id="search-input")
            with Horizontal(id="top"):
                with Vertical(id="left"):
                    recent = DataTable(id="recent-table", cursor_type="row")
                    recent.add_columns("ts", "kind", "id", "summary")
                    yield Static("Recent", classes="title")
                    yield recent
                    projects = DataTable(id="projects-table", cursor_type="row")
                    projects.add_columns("project", "updated")
                    yield Static("Projects", classes="title")
                    yield projects
                with Vertical(id="right"):
                    yield Static("Task Detail", classes="title")
                    yield Static("Select a recent task row to load details.", id="task-detail")
                    notes = DataTable(id="search-notes-table", cursor_type="row")
                    notes.add_columns("kind", "path", "match")
                    yield Static("Search Notes", classes="title")
                    yield notes
                    events = DataTable(id="search-events-table", cursor_type="row")
                    events.add_columns("task", "annotation", "ts")
                    yield Static("Search Events", classes="title")
                    yield events
            yield Footer()

        def on_mount(self) -> None:
            self._refresh_recent()
            self._refresh_projects()

        def action_refresh(self) -> None:
            self._refresh_recent()
            self._refresh_projects()

        def action_focus_search(self) -> None:
            self.query_one("#search-input", Input).focus()

        def action_edit_selected_task_note(self) -> None:
            if not self.current_task_ref:
                self.notify("Select a task row in Recent first", severity="warning")
                return
            try:
                # Hand terminal control back to the editor process; otherwise
                # the editor runs under Textual's terminal mode and feels broken.
                with self.suspend():
                    path = self.svc.open_task_note_in_editor(self.current_task_ref)
            except Exception as exc:
                self.notify(f"Editor failed: {exc}", severity="error")
                return
            self.notify(f"Opened: {path}")
            self._load_task(self.current_task_ref)

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
            try:
                if kind == "task":
                    if not self.current_task_ref:
                        self.notify("Select a task row in Recent first", severity="warning")
                        return
                    result = self.svc.add_to_task_heading(
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
                    result = self.svc.add_to_chain_heading(
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
                    result = self.svc.add_to_project_heading(
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
            self._refresh_recent()
            self._refresh_projects()
            if self.current_task_ref:
                self._load_task(self.current_task_ref)

        def on_input_submitted(self, event: Input.Submitted) -> None:
            if event.input.id != "search-input":
                return
            query = event.value.strip()
            if not query:
                return
            self._run_search(query)

        def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
            if event.data_table.id == "recent-table":
                row_index = event.cursor_row
                if row_index < 0 or row_index >= len(self.recent_rows):
                    return
                item = self.recent_rows[row_index]
                short_uuid = str(item.get("task_short_uuid") or "").strip()
                if not short_uuid:
                    return
                self.current_task_ref = short_uuid
                self.current_project_name = None
                self._load_task(short_uuid)
                return
            if event.data_table.id == "projects-table":
                row_index = event.cursor_row
                projects = self.svc.projects()
                if row_index < 0 or row_index >= len(projects):
                    return
                self.current_project_name = str(projects[row_index].get("project") or "").strip() or None
                if self.current_project_name:
                    self.notify(f"Project selected: {self.current_project_name}")

        def _refresh_recent(self) -> None:
            table = self.query_one("#recent-table", DataTable)
            table.clear()
            self.recent_rows = self.svc.recent(limit=80)
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

        def _refresh_projects(self) -> None:
            table = self.query_one("#projects-table", DataTable)
            table.clear()
            for item in self.svc.projects():
                table.add_row(str(item.get("project") or ""), str(item.get("updated") or ""))

        def _run_search(self, query: str) -> None:
            notes_table = self.query_one("#search-notes-table", DataTable)
            events_table = self.query_one("#search-events-table", DataTable)
            notes_table.clear()
            events_table.clear()
            data = self.svc.search(query)
            for item in data.get("notes", []):
                notes_table.add_row(
                    str(item.get("kind") or ""),
                    str(item.get("path") or ""),
                    str(item.get("match") or ""),
                )
            for item in data.get("events", []):
                events_table.add_row(
                    str(item.get("task_short_uuid") or ""),
                    str(item.get("annotation") or ""),
                    str(item.get("ts") or ""),
                )

        def _load_task(self, task_ref: str) -> None:
            detail = self.query_one("#task-detail", Static)
            try:
                data = self.svc.task_summary(task_ref)
            except Exception as exc:
                detail.update(f"Task load failed for {task_ref}\n\n{exc}")
                return
            lines: list[str] = []
            task = data.get("task", {})
            lines.append(f"Task {task.get('short_uuid')}")
            lines.append(f"Description: {task.get('description')}")
            lines.append(f"Project: {task.get('project') or ''}")
            tags = task.get("tags") or []
            if tags:
                lines.append(f"Tags: {', '.join(tags)}")
            notes = data.get("notes", {})
            self.current_task_chain_path = str(notes.get("chain") or "").strip()
            self.current_task_project = str(task.get("project") or "").strip()
            lines.append("")
            lines.append("Notes:")
            lines.append(f"  task: {notes.get('task')}")
            if notes.get("chain"):
                lines.append(f"  chain: {notes.get('chain')}")
            if notes.get("project"):
                lines.append(f"  project: {notes.get('project')}")
            lines.append("")
            lines.append("Recent events:")
            events = data.get("events") or []
            if not events:
                lines.append("  (none)")
            else:
                for item in events[:8]:
                    lines.append(f"  {item.get('entry') or ''} {item.get('description') or ''}".strip())
            detail.update("\n".join(lines))

    app = JotTUI(service)
    app.run()
    return 0
