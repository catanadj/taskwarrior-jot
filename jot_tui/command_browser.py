from __future__ import annotations

from jot_core.command_help import CommandHelp


def run_command_browser(commands: list[CommandHelp]) -> int:
    try:
        from textual.app import App, ComposeResult
        from textual.containers import Horizontal, Vertical
        from textual.widgets import DataTable, Footer, Header, Input, Static
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("textual is not installed") from exc

    class CommandBrowser(App[None]):
        CSS = """
        Screen {
            layout: vertical;
        }
        #intro {
            height: auto;
            padding: 0 1;
            color: $text-muted;
        }
        #command-search {
            margin: 1;
        }
        #workspace {
            height: 1fr;
        }
        #command-list {
            width: 46%;
            border: round $panel;
        }
        #command-details {
            width: 54%;
            border: round $accent;
            padding: 1 2;
            overflow: auto;
        }
        """

        BINDINGS = [
            ("q", "quit", "Quit"),
            ("escape", "quit", "Quit"),
            ("slash", "focus_search", "Search"),
        ]

        def __init__(self, items: list[CommandHelp]) -> None:
            super().__init__()
            self.items = items
            self.filtered = list(items)

        def compose(self) -> ComposeResult:
            yield Header(show_clock=False)
            yield Static(
                "Browse commands without running them. Move through the list to see syntax and purpose.",
                id="intro",
            )
            yield Input(placeholder="Filter commands", id="command-search")
            with Horizontal(id="workspace"):
                with Vertical(id="command-list"):
                    table = DataTable(id="command-table", cursor_type="row")
                    table.add_columns("category", "command", "summary")
                    yield table
                yield Static("", id="command-details", markup=False)
            yield Footer()

        def on_mount(self) -> None:
            self._render_table()
            self.query_one("#command-table", DataTable).focus()
            self._show_details(0)

        def action_focus_search(self) -> None:
            self.query_one("#command-search", Input).focus()

        def on_input_changed(self, event: Input.Changed) -> None:
            if event.input.id != "command-search":
                return
            query = event.value.strip().lower()
            self.filtered = [
                item
                for item in self.items
                if query in " ".join(
                    (item.name, item.category, item.summary, item.description, item.example)
                ).lower()
            ]
            self._render_table()
            self._show_details(0)

        def on_input_submitted(self, event: Input.Submitted) -> None:
            if event.input.id == "command-search":
                self.query_one("#command-table", DataTable).focus()

        def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
            if event.data_table.id == "command-table":
                self._show_details(event.cursor_row)

        def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
            if event.data_table.id == "command-table":
                self._show_details(event.cursor_row)

        def _render_table(self) -> None:
            table = self.query_one("#command-table", DataTable)
            table.clear()
            for item in self.filtered:
                table.add_row(item.category, item.name, item.summary)

        def _show_details(self, row: int) -> None:
            panel = self.query_one("#command-details", Static)
            if row < 0 or row >= len(self.filtered):
                panel.update("No matching commands.")
                return
            item = self.filtered[row]
            lines = [
                item.name,
                "",
                item.description,
                "",
                "Usage",
                f"  {item.usage}",
                "",
                "Example",
                f"  {item.example}",
            ]
            if item.arguments:
                lines.extend(["", "Arguments and options"])
                lines.extend(f"  {argument}" for argument in item.arguments)
            lines.extend(["", "This browser explains commands; it does not execute them."])
            panel.update("\n".join(lines))

    CommandBrowser(commands).run()
    return 0
