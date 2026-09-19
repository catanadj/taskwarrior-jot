"""Factories for shared confirmation and resource-picker dialogs."""

from __future__ import annotations

from typing import Any


def build_common_modals():
    from textual.containers import Horizontal, Vertical
    from textual.screen import ModalScreen
    from textual.widgets import Button, DataTable, Label, Static

    class ConfirmDeleteModal(ModalScreen[bool]):
        BINDINGS = [("escape", "cancel", "Cancel")]

        def __init__(self, *, label: str, path: str, trash_path: str) -> None:
            super().__init__()
            self.label, self.path, self.trash_path = label, path, trash_path

        def compose(self):
            with Vertical(id="dialog"):
                yield Label(f"Delete {self.label}?")
                yield Static(f"This will move the note to the trash folder.\n\nFrom: {self.path}\nTo:   {self.trash_path}", id="details")
                with Horizontal(id="buttons"):
                    yield Button("Cancel", id="cancel-btn")
                    yield Button("Delete", id="delete-btn", variant="error")

        def action_cancel(self):
            self.dismiss(False)

        def on_button_pressed(self, event):
            self.dismiss(event.button.id == "delete-btn")

    class ResourcePickerModal(ModalScreen[dict[str, Any] | None]):
        BINDINGS = [("escape", "cancel", "Cancel")]

        def __init__(self, *, title: str, resources: list[dict[str, Any]], action_label: str) -> None:
            super().__init__()
            self.title_text, self.resources, self.action_label = title, resources, action_label

        def compose(self):
            with Vertical(id="dialog"):
                yield Label(self.title_text)
                table = DataTable(id="resource-table", cursor_type="row")
                table.add_columns("id", "label", "kind", "target")
                yield table
                with Horizontal(id="buttons"):
                    yield Button("Cancel", id="cancel-btn")
                    yield Button(self.action_label, id="action-btn", variant="primary")

        def on_mount(self):
            table = self.query_one("#resource-table", DataTable)
            for item in self.resources:
                table.add_row(str(item.get("id") or ""), str(item.get("label") or ""), str(item.get("kind") or ""), str(item.get("target") or ""))
            table.focus()

        def action_cancel(self):
            self.dismiss(None)

        def on_button_pressed(self, event):
            if event.button.id == "action-btn":
                self._submit_row(self.query_one("#resource-table", DataTable).cursor_row)
            else:
                self.dismiss(None)

        def on_data_table_row_selected(self, event):
            if event.data_table.id == "resource-table":
                self._submit_row(event.cursor_row)

        def _submit_row(self, row: int):
            if 0 <= row < len(self.resources):
                self.dismiss(dict(self.resources[row]))
            else:
                self.dismiss(None)

    return ConfirmDeleteModal, ResourcePickerModal
