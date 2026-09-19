"""Factories for timelog-related Textual dialogs."""

from __future__ import annotations

from typing import Any, Callable


def build_time_modals(
    time_input_value: Callable[[str], str],
    default_time_range: Callable[[], tuple[str, str]],
):
    try:
        from textual.containers import Horizontal, Vertical
        from textual.screen import ModalScreen
        from textual.widgets import Button, DataTable, Input, Label, Select, Static
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("textual is required for timelog dialogs") from exc

    class TimeSessionStartModal(ModalScreen[str | None]):
        BINDINGS = [("escape", "cancel", "Cancel")]
        CSS = "#dialog { width: 70; height: auto; border: round $accent; padding: 1 2; background: $surface; } #dialog Input { margin: 1 0; } #buttons { height: auto; }"

        def __init__(self, initial_task_ref: str = "") -> None:
            super().__init__()
            self.initial_task_ref = initial_task_ref

        def compose(self):
            with Vertical(id="dialog"):
                yield Label("Start timer")
                yield Static("Jot will keep this session pending until you stop or cancel it.", id="time-session-help")
                yield Input(value=self.initial_task_ref, placeholder="Task ID or UUID", id="time-session-task")
                with Horizontal(id="buttons"):
                    yield Button("Cancel", id="cancel-btn")
                    yield Button("Start", id="start-btn", variant="primary")

        def action_cancel(self):
            self.dismiss(None)

        def on_button_pressed(self, event):
            if event.button.id == "start-btn":
                self._submit()
            else:
                self.dismiss(None)

        def on_input_submitted(self, _event):
            self._submit()

        def _submit(self):
            task_ref = self.query_one("#time-session-task", Input).value.strip()
            if not task_ref:
                self.app.notify("Task reference is required", severity="warning")
                return
            self.dismiss(task_ref)

    class ConfirmTimeSessionModal(ModalScreen[bool]):
        BINDINGS = [("escape", "cancel", "Cancel")]
        CSS = "#dialog { width: 76; height: auto; border: round $warning; padding: 1 2; background: $surface; } #details { margin: 1 0; color: $text-muted; } #buttons { height: auto; }"

        def __init__(self, *, title: str, details: str, action_label: str) -> None:
            super().__init__()
            self.title_text, self.details, self.action_label = title, details, action_label

        def compose(self):
            with Vertical(id="dialog"):
                yield Label(self.title_text)
                yield Static(self.details, id="details")
                with Horizontal(id="buttons"):
                    yield Button("Back", id="cancel-btn")
                    yield Button(self.action_label, id="confirm-btn", variant="warning")

        def action_cancel(self):
            self.dismiss(False)

        def on_button_pressed(self, event):
            self.dismiss(event.button.id == "confirm-btn")

    class TimeEntryModal(ModalScreen[dict[str, str] | None]):
        BINDINGS = [("escape", "cancel", "Cancel")]
        CSS = "#dialog { width: 82; height: auto; border: round $accent; padding: 1 2; background: $surface; } #dialog Input, #dialog Select { margin: 1 0; } #buttons { height: auto; }"

        def __init__(self, *, mode: str, item: dict[str, Any] | None = None, initial_task_ref: str = "") -> None:
            super().__init__()
            self.mode, self.item, self.initial_task_ref = mode, dict(item or {}), initial_task_ref

        def compose(self):
            if self.mode == "amend":
                title = f"Amend interval {self.item.get('key') or ''}"
                task_ref = str(self.item.get("task_short_uuid") or "")
                started = time_input_value(str(self.item.get("started") or ""))
                stopped = time_input_value(str(self.item.get("stopped") or ""))
            else:
                title = "Add completed time interval"
                task_ref = self.initial_task_ref
                started, stopped = default_time_range()
            with Vertical(id="dialog"):
                yield Label(title)
                yield Static("Timezone-less values use the local timezone. Explicit offsets are preserved.", id="time-entry-help")
                yield Input(value=task_ref, placeholder="Task ID or UUID", id="time-entry-task", disabled=self.mode == "amend")
                yield Input(value=started, placeholder="Start datetime", id="time-entry-from")
                yield Input(value=stopped, placeholder="Stop datetime", id="time-entry-to")
                if self.mode == "add":
                    yield Select([("Automatic scope", "auto"), ("Task note", "task"), ("Chain note", "chain")], value="auto", allow_blank=False, id="time-entry-scope")
                with Horizontal(id="buttons"):
                    yield Button("Cancel", id="cancel-btn")
                    yield Button("Amend" if self.mode == "amend" else "Add", id="save-btn", variant="primary")

        def action_cancel(self):
            self.dismiss(None)

        def on_button_pressed(self, event):
            if event.button.id == "save-btn":
                self._submit()
            else:
                self.dismiss(None)

        def on_input_submitted(self, event):
            next_id = {"time-entry-task": "#time-entry-from", "time-entry-from": "#time-entry-to"}.get(event.input.id or "")
            if next_id:
                self.query_one(next_id, Input).focus()
            else:
                self._submit()

        def _submit(self):
            task_ref = self.query_one("#time-entry-task", Input).value.strip()
            started = self.query_one("#time-entry-from", Input).value.strip()
            stopped = self.query_one("#time-entry-to", Input).value.strip()
            if not task_ref or not started or not stopped:
                self.app.notify("Task reference, start, and stop times are required", severity="warning")
                return
            scope = "auto" if self.mode == "amend" else str(self.query_one("#time-entry-scope", Select).value or "auto")
            self.dismiss({"task_ref": task_ref, "started_at": started, "stopped_at": stopped, "scope": scope})

    class ConfirmTimeDeleteModal(ModalScreen[bool]):
        BINDINGS = [("escape", "cancel", "Cancel")]

        def __init__(self, item: dict[str, Any]) -> None:
            super().__init__()
            self.item = item

        def compose(self):
            with Vertical(id="dialog"):
                yield Label(f"Delete interval {self.item.get('key') or ''}?")
                yield Static(f"{self.item.get('duration') or ''} for task {self.item.get('task_short_uuid') or ''}\n{self.item.get('display_range') or ''}\n\nThe original entry will remain available in timelog trash.", id="details")
                with Horizontal(id="buttons"):
                    yield Button("Cancel", id="cancel-btn")
                    yield Button("Delete", id="delete-btn", variant="error")

        def action_cancel(self):
            self.dismiss(False)

        def on_button_pressed(self, event):
            self.dismiss(event.button.id == "delete-btn")

    class TimeTrashModal(ModalScreen[dict[str, Any] | None]):
        BINDINGS = [("escape", "cancel", "Cancel")]

        def __init__(self, items: list[dict[str, Any]]) -> None:
            super().__init__()
            self.items = items

        def compose(self):
            with Vertical(id="dialog"):
                yield Label("Restore deleted time interval")
                table = DataTable(id="time-trash-table", cursor_type="row")
                table.add_columns("id", "key", "time", "task/chain", "project", "archived")
                yield table
                with Horizontal(id="buttons"):
                    yield Button("Cancel", id="cancel-btn")
                    yield Button("Restore", id="restore-btn", variant="primary")

        def on_mount(self):
            table = self.query_one("#time-trash-table", DataTable)
            for item in self.items:
                table.add_row(f"#{item.get('id')}", str(item.get("key") or ""), str(item.get("duration") or ""), str(item.get("chain_id") or item.get("task_short_uuid") or ""), str(item.get("project") or ""), str(item.get("archived_at") or ""))
            table.focus()

        def action_cancel(self):
            self.dismiss(None)

        def on_button_pressed(self, event):
            if event.button.id == "restore-btn":
                self._submit(self.query_one("#time-trash-table", DataTable).cursor_row)
            else:
                self.dismiss(None)

        def on_data_table_row_selected(self, event):
            if event.data_table.id == "time-trash-table":
                self._submit(event.cursor_row)

        def _submit(self, row: int):
            if 0 <= row < len(self.items):
                self.dismiss(dict(self.items[row]))

    return TimeSessionStartModal, ConfirmTimeSessionModal, TimeEntryModal, ConfirmTimeDeleteModal, TimeTrashModal
