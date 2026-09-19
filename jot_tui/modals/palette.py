"""Reusable Textual modal factories used by the Jot application."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from jot_tui.palette import PaletteEntry, filter_palette_entries


def build_command_palette_modal():
    """Return the command-palette modal without importing Textual at module load."""
    try:
        from textual.containers import Horizontal, Vertical
        from textual.screen import ModalScreen
        from textual.widgets import Button, DataTable, Input, Label
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("textual is required for the command palette") from exc

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

        def __init__(
            self,
            entries: list[PaletteEntry],
            *,
            title: str = "Command palette",
            placeholder: str = "Type to filter commands",
        ) -> None:
            super().__init__()
            self.entries = entries
            self.filtered_entries = list(entries)
            self.title_text = title
            self.placeholder = placeholder

        def compose(self):
            with Vertical(id="dialog"):
                yield Label(self.title_text)
                yield Input(placeholder=self.placeholder, id="palette-input")
                table = DataTable(id="palette-table", cursor_type="row")
                table.add_columns("key", "command", "description")
                yield table
                with Horizontal(id="palette-buttons"):
                    yield Button("Cancel", id="cancel-btn")
                    yield Button("Open", id="open-btn", variant="primary")

        def on_mount(self) -> None:
            self.query_one("#palette-input", Input).focus()
            self.call_after_refresh(self._render_table)

        def action_cancel(self) -> None:
            self.dismiss(None)

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "open-btn":
                self._open_selected()
                return
            self.dismiss(None)

        def on_input_changed(self, event: Input.Changed) -> None:
            if event.input.id == "palette-input":
                self.filtered_entries = filter_palette_entries(self.entries, event.value)
                self._render_table()

        def on_input_submitted(self, event: Input.Submitted) -> None:
            if event.input.id == "palette-input":
                self._open_selected()

        def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
            if event.data_table.id == "palette-table":
                self._open_row(event.cursor_row)

        def _render_table(self) -> None:
            tables = self.query("#palette-table")
            if not tables:
                return
            table = tables.first(DataTable)
            table.clear()
            for entry in self.filtered_entries[:20]:
                table.add_row(entry.id, entry.label, entry.detail)

        def _open_selected(self) -> None:
            row = self.query_one("#palette-table", DataTable).cursor_row
            self._open_row(max(0, row))

        def _open_row(self, row: int) -> None:
            if row < 0 or row >= len(self.filtered_entries):
                self.dismiss(None)
                return
            self.dismiss(asdict(self.filtered_entries[row]))

    return CommandPaletteModal
