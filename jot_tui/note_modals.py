"""Factories for note and resource Textual dialogs."""

from __future__ import annotations

from typing import Any


def build_note_modals():
    try:
        from textual.containers import Horizontal, Vertical
        from textual.screen import ModalScreen
        from textual.widgets import Button, Checkbox, Input, Label
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("textual is required for note dialogs") from exc

    class AddToHeadingModal(ModalScreen[dict[str, Any] | None]):
        CSS = """
        #dialog { width: 70; height: auto; border: round $panel; padding: 1 2; background: $surface; }
        #dialog Input { margin: 1 0; }
        #buttons { height: auto; }
        """
        BINDINGS = [("escape", "cancel", "Cancel")]

        def compose(self):
            with Vertical(id="dialog"):
                yield Label("Add entry under heading")
                yield Input(placeholder="Heading, e.g. Notes", id="heading-input")
                yield Input(placeholder="Entry text", id="entry-input")
                yield Checkbox("Create heading if missing", id="create-heading")
                with Horizontal(id="buttons"):
                    yield Button("Cancel", id="cancel-btn")
                    yield Button("Add", id="add-btn", variant="primary")

        def action_cancel(self):
            self.dismiss(None)

        def on_button_pressed(self, event):
            if event.button.id == "cancel-btn":
                self.dismiss(None)
            else:
                self._submit()

        def on_input_submitted(self, event):
            if event.input.id == "heading-input":
                self.query_one("#entry-input", Input).focus()
            else:
                self._submit()

        def _submit(self):
            heading = self.query_one("#heading-input", Input).value.strip()
            entry = self.query_one("#entry-input", Input).value.strip()
            if not heading:
                self.app.notify("Heading is required", severity="warning")
                return
            if not entry:
                self.app.notify("Entry text is required", severity="warning")
                return
            self.dismiss({"heading": heading, "entry": entry, "create_heading": bool(self.query_one("#create-heading", Checkbox).value)})

    class AttachResourceModal(ModalScreen[dict[str, str] | None]):
        CSS = """
        #dialog { width: 78; height: auto; border: round $panel; padding: 1 2; background: $surface; }
        #dialog Input { margin: 1 0; }
        #buttons { height: auto; }
        """
        BINDINGS = [("escape", "cancel", "Cancel")]

        def compose(self):
            with Vertical(id="dialog"):
                yield Label("Attach resource to active note")
                yield Input(placeholder="Path or URL", id="resource-target")
                yield Input(placeholder="Optional label", id="resource-label")
                with Horizontal(id="buttons"):
                    yield Button("Cancel", id="cancel-btn")
                    yield Button("Attach", id="attach-btn", variant="primary")

        def action_cancel(self):
            self.dismiss(None)

        def on_button_pressed(self, event):
            if event.button.id == "cancel-btn":
                self.dismiss(None)
            else:
                self._submit()

        def on_input_submitted(self, event):
            if event.input.id == "resource-target":
                self.query_one("#resource-label", Input).focus()
            else:
                self._submit()

        def _submit(self):
            target = self.query_one("#resource-target", Input).value.strip()
            if not target:
                self.app.notify("Resource path or URL is required", severity="warning")
                return
            self.dismiss({"target": target, "label": self.query_one("#resource-label", Input).value.strip()})

    return AddToHeadingModal, AttachResourceModal
