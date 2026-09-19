"""Progress dialog factory for the Textual UI."""

from __future__ import annotations

from typing import Any, Callable


def build_progress_modal(
    new_track_marker: str,
    initial_track: Callable[[list[str]], str | None],
    resolve_track: Callable[[str | None, str, str], str],
):
    try:
        from textual.containers import Horizontal, Vertical
        from textual.screen import ModalScreen
        from textual.widgets import Button, Checkbox, Input, Label, Select, Static
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("textual is required for progress dialogs") from exc

    class ProgressModal(ModalScreen[dict[str, Any] | None]):
        BINDINGS = [("escape", "cancel", "Cancel")]
        CSS = "#dialog { width: 78; height: auto; border: round $accent; padding: 1 2; background: $surface; } #dialog Input { margin: 1 0; } #progress-help { color: $text-muted; } #buttons { height: auto; }"

        def __init__(self, *, scopes: list[str], initial_scope: str, tracks_by_scope: dict[str, list[str]]) -> None:
            super().__init__()
            self.scopes, self.initial_scope, self.tracks_by_scope = scopes, initial_scope, tracks_by_scope

        def compose(self):
            with Vertical(id="dialog"):
                yield Label("Update progress")
                yield Static("Operations: set, add, subtract, status, clear\nUse separate track names for independent measurements.\nAvailable scopes: " + ", ".join(self.scopes), id="progress-help")
                yield Select([(scope.capitalize(), scope) for scope in self.scopes], value=self.initial_scope, allow_blank=False, id="progress-scope")
                yield Select([], prompt="Select track", id="progress-track")
                yield Input(placeholder="New track name (used with set)", id="progress-new-track", disabled=True)
                yield Input(placeholder="Operation", id="progress-operation")
                yield Input(placeholder="Value: 120/350 for set, 20 for add/subtract, text for status", id="progress-value")
                yield Input(placeholder="Optional unit for set", id="progress-unit")
                yield Input(placeholder="Optional status for set", id="progress-status")
                yield Checkbox("Confirm clear", id="progress-confirm-clear")
                with Horizontal(id="buttons"):
                    yield Button("Cancel", id="cancel-btn")
                    yield Button("Apply", id="apply-btn", variant="primary")

        def on_mount(self):
            self._load_track_options(self.initial_scope)

        def action_cancel(self):
            self.dismiss(None)

        def on_button_pressed(self, event):
            if event.button.id == "cancel-btn":
                self.dismiss(None)
            else:
                self._submit()

        def on_input_submitted(self, event):
            next_id = {"progress-new-track": "#progress-operation", "progress-operation": "#progress-value", "progress-value": "#progress-unit", "progress-unit": "#progress-status"}.get(event.input.id or "")
            if next_id:
                self.query_one(next_id, Input).focus()
            else:
                self._submit()

        def on_select_changed(self, event):
            if event.select.id == "progress-scope":
                self._load_track_options(str(event.value))
            elif event.select.id == "progress-track":
                new_track = self.query_one("#progress-new-track", Input)
                is_new = event.value == new_track_marker
                new_track.disabled = not is_new
                if is_new:
                    new_track.focus()

        def _load_track_options(self, scope: str):
            tracks = self.tracks_by_scope.get(scope, [])
            selector = self.query_one("#progress-track", Select)
            new_track = self.query_one("#progress-new-track", Input)
            new_track.value = ""
            selector.set_options([(track, track) for track in tracks] + [("New track...", new_track_marker)])
            selected = initial_track(tracks)
            if selected is not None:
                selector.value, new_track.disabled = selected, True
            elif not tracks:
                selector.value, new_track.disabled = new_track_marker, False
            else:
                selector.value, new_track.disabled = Select.BLANK, True

        def _submit(self):
            scope = str(self.query_one("#progress-scope", Select).value).strip().lower()
            selected = self.query_one("#progress-track", Select).value
            selected_track = None if selected is Select.BLANK else str(selected)
            operation = self.query_one("#progress-operation", Input).value.strip().lower()
            value = self.query_one("#progress-value", Input).value.strip()
            unit = self.query_one("#progress-unit", Input).value.strip()
            status = self.query_one("#progress-status", Input).value.strip()
            confirm_clear = bool(self.query_one("#progress-confirm-clear", Checkbox).value)
            try:
                track = resolve_track(selected_track, self.query_one("#progress-new-track", Input).value, operation)
            except RuntimeError as exc:
                self.app.notify(str(exc), severity="warning")
                return
            if scope not in self.scopes or operation not in {"set", "add", "subtract", "status", "clear"}:
                self.app.notify("Choose a valid scope and operation", severity="warning")
                return
            if operation != "clear" and not value:
                self.app.notify("Value is required for this operation", severity="warning")
                return
            if operation == "clear" and not confirm_clear:
                self.app.notify("Confirm clear before applying", severity="warning")
                return
            self.dismiss({"scope": scope, "track": track, "operation": operation, "value": value, "unit": unit, "status": status, "confirm_clear": confirm_clear})

    return ProgressModal
