"""Factories for note and resource Textual dialogs."""

from __future__ import annotations

from typing import Any


def build_note_modals():
    try:
        from textual.containers import Horizontal, Vertical, VerticalScroll
        from textual.screen import ModalScreen
        from textual.widgets import Button, Checkbox, Input, Label, Static
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

    class TrashNotePreviewModal(ModalScreen[dict[str, Any] | None]):
        BINDINGS = [("escape", "cancel", "Close")]
        CSS = """
        #trash-preview-dialog { width: 92; height: 90%; border: round $panel; padding: 1 2; background: $surface; }
        #trash-preview-details { height: auto; margin: 1 0; color: $text-muted; }
        #trash-preview-scroll { height: 1fr; border: round $panel; padding: 1; }
        #trash-preview-body { width: 1fr; }
        #buttons { height: auto; margin-top: 1; }
        """

        def __init__(self, item: dict[str, Any], body: str) -> None:
            super().__init__()
            self.item = item
            self.body = body

        def compose(self):
            kind = str(self.item.get("kind") or "deleted note").replace("-note", " note")
            title = (
                str(self.item.get("description") or "").strip()
                or str(self.item.get("project") or "").strip()
                or str(self.item.get("chain_id") or "").strip()
                or str(self.item.get("task_short_uuid") or "").strip()
                or kind
            )
            details = (
                f"Original: {self.item.get('original_path') or ''}\n"
                f"Deleted: {self.item.get('deleted_at') or 'unknown'}"
            )
            with Vertical(id="trash-preview-dialog"):
                yield Label(f"Deleted {kind}: {title}")
                yield Static(details, id="trash-preview-details")
                with VerticalScroll(id="trash-preview-scroll"):
                    yield Static(self.body, id="trash-preview-body", markup=False)
                with Horizontal(id="buttons"):
                    yield Button("Close", id="trash-preview-close-btn")
                    yield Button("Restore note", id="trash-preview-restore-btn", variant="primary")

        def action_cancel(self):
            self.dismiss(None)

        def on_button_pressed(self, event):
            if event.button.id == "trash-preview-restore-btn":
                self.dismiss(dict(self.item))
            else:
                self.dismiss(None)

    class NoteHistoryDiffModal(ModalScreen[bool]):
        BINDINGS = [("escape", "cancel", "Close")]
        CSS = """
        #history-diff-dialog { width: 96; height: 90%; border: round $panel; padding: 1 2; background: $surface; }
        #history-diff-scroll { height: 1fr; border: round $panel; padding: 1; }
        #history-diff-text { width: 1fr; }
        #history-diff-buttons { height: auto; margin-top: 1; }
        """

        def __init__(self, *, revision_id: str, diff: str) -> None:
            super().__init__()
            self.revision_id = revision_id
            self.diff = diff

        def compose(self):
            with Vertical(id="history-diff-dialog"):
                yield Label(f"Revision {self.revision_id} compared with current note")
                with VerticalScroll(id="history-diff-scroll"):
                    yield Static(self.diff or "No differences", id="history-diff-text", markup=False)
                yield Label("Restoring keeps the current note as another revision.")
                with Horizontal(id="history-diff-buttons"):
                    yield Button("Close", id="history-diff-close-btn")
                    yield Button("Restore revision", id="history-diff-restore-btn", variant="warning")

        def action_cancel(self):
            self.dismiss(False)

        def on_button_pressed(self, event):
            self.dismiss(event.button.id == "history-diff-restore-btn")

    return AddToHeadingModal, AttachResourceModal, TrashNotePreviewModal, NoteHistoryDiffModal
