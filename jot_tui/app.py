from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

from jot_core.frontmatter import read_document
from jot_core.services import JotService
from jot_core.notes import preview_trash_path
from jot_tui.palette import PaletteEntry, filter_palette_entries
from jot_tui.modals import (
    build_command_palette_modal,
    build_common_modals,
    build_note_modals,
    build_progress_modal,
    build_time_modals,
)
from jot_tui.state import TuiState
from jot_tui.controllers.progress import apply_progress
from jot_tui.controllers.resources import attach_resource, detach_resource, open_resource
from jot_tui.controllers.timelog import add as add_time, amend as amend_time, cancel as cancel_time, delete as delete_time, restore as restore_time, start as start_time, stop as stop_time, stop_all as stop_all_time, trash as trash_time
from jot_tui.panes.timelog import compose_time_pane
from jot_tui.panes.browse import compose_browse_pane
from jot_tui.panes.latest import compose_latest_pane
from jot_tui.panes.notes import compose_notes_pane
from jot_tui.panes.search import compose_search_pane
from jot_tui.rendering import (
    note_excerpt,
    pretty_label,
    progress_bar,
    render_events_panel,
    render_note_panel,
    render_workspace_progress,
    render_workspace_resources,
    workspace_has_progress,
    workspace_has_resources,
)


NEW_PROGRESS_TRACK = "__new_progress_track__"


def _read_row_field(item: object, name: str, default: Any = None) -> Any:
    """Read typed browse rows while accepting mapping-based integrations."""
    if hasattr(item, name):
        return getattr(item, name)
    if isinstance(item, Mapping):
        return item.get(name, default)
    return default


def tui_time_input_value(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.astimezone().isoformat(timespec="minutes")


def tui_default_time_range(now: datetime | None = None) -> tuple[str, str]:
    stopped = (now or datetime.now().astimezone()).astimezone()
    started = stopped - timedelta(hours=1)
    return started.isoformat(timespec="minutes"), stopped.isoformat(timespec="minutes")


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


def tui_note_empty_guidance(title: str, path: str) -> str:
    lines = [title, ""]
    lines.append(f"Path: {path or '(will be created when opened)'}")
    lines.append("")
    lines.append("No note text yet.")
    lines.append("Press e to open this note in your editor.")
    lines.append("Press a/c to add a timestamped heading entry when available.")
    lines.append("Press f to attach a file or URL.")
    return "\n".join(lines)


def tui_context_action_entries(
    *,
    scope: str,
    has_note: bool,
    has_resources: bool,
    has_progress: bool,
    has_chain: bool = False,
    has_project: bool = False,
) -> list[PaletteEntry]:
    entries = [
        PaletteEntry("edit-note", "Edit/open note", "Open the active note in your editor."),
    ]
    if has_note:
        entries.append(PaletteEntry("note-history", "Note history", "Review past revisions and restore one."))
    if scope == "task":
        entries.append(
            PaletteEntry("add-task", "Add to task heading", "Prompt for heading and text, then append a timestamped task entry.")
        )
        if has_chain:
            entries.append(
                PaletteEntry("add-chain", "Add to chain heading", "Prompt for heading and text, then append a timestamped chain entry.")
            )
        if has_project:
            entries.append(
                PaletteEntry("open-project", "Open project workspace", "Open the related project workspace.")
            )
    if scope == "project":
        entries.append(
            PaletteEntry("attach-resource", "Attach project resource", "Prompt for a file path or URL and store it on the project note.")
        )
    elif has_note:
        entries.append(
            PaletteEntry("attach-resource", "Attach resource", "Prompt for a file path or URL and store it on the active note.")
        )
    if has_resources:
        entries.extend(
            [
                PaletteEntry("open-resource", "Open resource", "Choose a resource from the active note and open it."),
                PaletteEntry("detach-resource", "Detach resource", "Choose a resource from the active note and remove it."),
            ]
        )
    if has_progress:
        entries.append(
            PaletteEntry("update-progress", "Update progress", "Open the progress dialog for this context.")
        )
    else:
        entries.append(
            PaletteEntry("update-progress", "Start progress tracking", "Set a current/target measurement for this context.")
        )
    entries.append(
        PaletteEntry("delete-note", "Delete note", "Show a confirmation, then move the active note to trash.")
    )
    return entries


def tui_next_actions(
    *,
    scope: str,
    has_note: bool,
    has_resources: bool,
    has_progress: bool,
    has_chain: bool = False,
    has_project: bool = False,
) -> list[str]:
    labels = {
        "edit-note": "e edit/open note",
        "add-task": "a add to task heading",
        "add-chain": "c add to chain heading",
        "open-project": "p open project workspace",
        "attach-resource": "f attach resource",
        "open-resource": "o open resource",
        "detach-resource": "x detach resource",
        "update-progress": "g update progress" if has_progress else "g start progress tracking",
        "delete-note": "d delete note",
    }
    return [
        labels[entry.id]
        for entry in tui_context_action_entries(
            scope=scope,
            has_note=has_note,
            has_resources=has_resources,
            has_progress=has_progress,
            has_chain=has_chain,
            has_project=has_project,
        )
        if entry.id in labels
    ]


def tui_actions_block(actions: list[str]) -> str:
    if not actions:
        return ""
    return "Next actions:\n" + "\n".join(f"  - {action}" for action in actions)


def build_tui(
    service: JotService,
    *,
    session_refresh_seconds: float | None = 60,
) -> Any:
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

    # Keep the palette workflow independent from the main application state.
    CommandPaletteModal = build_command_palette_modal()
    AddToHeadingModal, AttachResourceModal, TrashNotePreviewModal, NoteHistoryDiffModal = build_note_modals()
    TimeSessionStartModal, ConfirmTimeSessionModal, TimeEntryModal, ConfirmTimeDeleteModal, TimeTrashModal = build_time_modals(tui_time_input_value, tui_default_time_range)
    ProgressModal = build_progress_modal(NEW_PROGRESS_TRACK, initial_progress_track, resolve_progress_track)
    ConfirmDeleteModal, ResourcePickerModal = build_common_modals()

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
        #search-notes-detail, #search-trash-detail, #search-events-detail {
            height: 6;
            border: round $panel;
            padding: 0 1;
            overflow: auto;
        }
        #time-pane { padding: 0 1; }
        #time-controls { height: auto; margin: 0 0 1 0; }
        #time-filter-controls, #time-action-controls { height: auto; }
        #time-period { width: 24; margin: 0 1 0 0; }
        #time-controls Button { margin: 0 1 0 0; }
        #time-sessions-block { height: 8; border: round $panel; }
        #time-sessions-title { height: auto; padding: 0 1; }
        #time-session-controls { height: auto; padding: 0 1; }
        #time-session-controls Button { margin: 0 1 0 0; }
        #time-sessions-table { height: 1fr; }
        #time-summary { height: auto; padding: 0 1 1 1; }
        #time-groups { height: 2fr; }
        #time-groups > Vertical { width: 1fr; border: round $panel; }
        #time-details-block { height: 3fr; border: round $panel; }
        #time-day-table, #time-project-table, #time-task-table, #time-details-table { height: 1fr; }
        #context-hints { padding: 0 1; color: $text-muted; }
        #recent-table, #tasks-table, #projects-table, #notes-table, #search-notes-table, #search-trash-table, #search-events-table { height: 1fr; }
        #search-results-tabs { height: 1fr; }
        """

        BINDINGS = [
            ("q", "quit", "Quit"),
            ("r", "refresh", "Refresh"),
            ("u", "refresh_current", "Update"),
            ("ctrl+p", "command_palette", "Palette"),
            ("enter", "open_selected", "Open"),
            ("m", "context_actions", "Actions"),
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
            self.state = TuiState()
            self.svc = svc
            self.session_refresh_seconds = session_refresh_seconds

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            with TabbedContent(initial="browse-tab", id="main-tabs"):
                with TabPane("Browse", id="browse-tab"):
                    yield from compose_browse_pane()
                with TabPane("Time", id="time-tab"):
                    yield from compose_time_pane()
                with TabPane("Notes", id="notes-tab"):
                    yield from compose_notes_pane()
                with TabPane("Search", id="search-tab"):
                    yield from compose_search_pane()
                with TabPane("Latest Edits", id="latest-tab"):
                    yield from compose_latest_pane()
            yield Static("Actions: / search | r refresh | q quit", id="context-hints")
            yield Footer()

        async def on_mount(self) -> None:
            await self._refresh_recent_async()
            await self._refresh_tasks_async()
            await self._refresh_projects_async()
            await self._refresh_notes_async()
            await self._refresh_time_async()
            if self.session_refresh_seconds is not None:
                self.set_interval(
                    self.session_refresh_seconds,
                    self._refresh_time_sessions_async,
                )
            self._update_action_hints()

        async def action_refresh(self) -> None:
            await self._refresh_recent_async()
            await self._refresh_tasks_async()
            await self._refresh_projects_async()
            await self._refresh_notes_async()
            await self._refresh_time_async()
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
                self.action_context_actions()
                return
            table_id = focused.id or ""
            row_index = focused.cursor_row
            if row_index < 0:
                return
            if table_id == "time-sessions-table":
                if row_index >= len(self.state.time_session_rows):
                    return
                task_ref = str(self.state.time_session_rows[row_index].get("task_short_uuid") or "").strip()
                if task_ref:
                    self._open_task_workspace(task_ref)
                return
            if table_id == "time-details-table":
                if row_index >= len(self.state.time_rows):
                    return
                task_ref = str(self.state.time_rows[row_index].get("task_short_uuid") or "").strip()
                if task_ref:
                    self._open_task_workspace(task_ref)
                return
            if table_id == "recent-table":
                if row_index >= len(self.state.recent_rows):
                    return
                short_uuid = str(self.state.recent_rows[row_index].get("task_short_uuid") or "").strip()
                if short_uuid:
                    self._open_latest_workspace(short_uuid)
                return
            if table_id == "tasks-table":
                if row_index >= len(self.state.task_rows):
                    return
                short_uuid = str(_read_row_field(self.state.task_rows[row_index], "short_uuid") or "").strip()
                if short_uuid:
                    self._open_task_workspace(short_uuid)
                return
            if table_id == "projects-table":
                if row_index >= len(self.state.project_rows):
                    return
                project_name = str(_read_row_field(self.state.project_rows[row_index], "project") or "").strip()
                if project_name:
                    self.state.current_project_name = project_name
                if project_name and bool(_read_row_field(self.state.project_rows[row_index], "selectable")):
                    self._open_project_workspace(project_name)
                return
            if table_id == "notes-table":
                if row_index >= len(self.state.note_rows):
                    return
                self._open_note_inventory_row(self.state.note_rows[row_index])
                return
            if table_id == "search-events-table":
                if row_index >= len(self.state.search_event_rows):
                    return
                short_uuid = str(self.state.search_event_rows[row_index].get("task_short_uuid") or "").strip()
                if short_uuid:
                    self._open_task_workspace(short_uuid)
                return
            if table_id == "search-trash-table":
                if row_index >= len(self.state.search_trash_rows):
                    return
                self._open_search_trash_preview(self.state.search_trash_rows[row_index])
                return
            if table_id == "search-notes-table":
                if row_index >= len(self.state.search_note_rows):
                    return
                item = self.state.search_note_rows[row_index]
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

        def action_context_actions(self) -> None:
            entries = self._context_action_entries()
            if not entries:
                self.notify("Select a task, project, recent item, or note tab first", severity="warning")
                return
            self.push_screen(
                CommandPaletteModal(
                    entries,
                    title="Context actions",
                    placeholder="Type to filter actions",
                ),
                lambda payload: self._on_context_action_selected(payload),
            )

        def action_edit_selected_task_note(self) -> None:
            if self.query_one("#main-tabs", TabbedContent).active == "time-tab":
                self.action_time_amend()
                return
            target = self._active_note_target()
            try:
                path = self._open_active_note_in_editor()
            except Exception as exc:
                self.notify(f"Editor failed: {exc}", severity="error")
                return
            self.notify(f"Opened: {path}")
            self._offer_post_save_actions(target)
            main_tab = self.query_one("#main-tabs", TabbedContent).active
            if main_tab == "notes-tab":
                asyncio.create_task(self._refresh_notes_async())
            elif main_tab == "latest-tab" and self.state.current_latest_task_ref:
                asyncio.create_task(self._load_latest_task_async(self.state.current_latest_task_ref))
            elif self.state.current_task_ref:
                asyncio.create_task(self._load_task_async(self.state.current_task_ref))
            elif self.state.current_project_name:
                asyncio.create_task(self._load_project_async(self.state.current_project_name))

        def _offer_post_save_actions(self, target: dict[str, Any] | None) -> None:
            if not self.svc.config.editor_post_save_actions or target is None:
                return
            kind = str(target.get("kind") or "")
            task_ref = str(target.get("task_ref") or "").strip()
            if kind not in {"task", "chain"} or not task_ref:
                return
            self.push_screen(
                CommandPaletteModal(
                    [
                        PaletteEntry(
                            "complete-task",
                            "Complete task",
                            "Mark the related Taskwarrior task done",
                        ),
                    ],
                    title="Post-save actions",
                    placeholder="Type to filter actions",
                ),
                lambda payload: self._on_post_save_action_selected(payload, task_ref),
            )

        def _on_post_save_action_selected(self, payload: dict[str, Any] | None, task_ref: str) -> None:
            if not payload or payload.get("id") != "complete-task":
                return
            asyncio.create_task(self._complete_task_async(task_ref))

        async def _complete_task_async(self, task_ref: str) -> None:
            try:
                result = await asyncio.to_thread(self.svc.complete_task, task_ref)
            except Exception as exc:
                self.notify(f"Complete failed: {exc}", severity="error")
                return
            self.notify(f"Completed task: {result.get('task_short_uuid')}")
            await self._refresh_current_context_async()

        def action_delete_selected_note(self) -> None:
            if self.query_one("#main-tabs", TabbedContent).active == "time-tab":
                self.action_time_delete()
                return
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
            if self.query_one("#main-tabs", TabbedContent).active == "time-tab":
                self.action_time_add()
                return
            if not self.state.current_task_ref:
                self.notify("Select a task row in Recent first", severity="warning")
                return
            self.push_screen(
                AddToHeadingModal(),
                lambda payload: self._on_add_to_payload("task", payload),
            )

        def action_add_to_selected_chain(self) -> None:
            if not self.state.current_task_ref:
                self.notify("Select a task row in Recent first", severity="warning")
                return
            if not self.state.current_task_chain_path:
                self.notify("Selected task has no chain note context", severity="warning")
                return
            self.push_screen(
                AddToHeadingModal(),
                lambda payload: self._on_add_to_payload("chain", payload),
            )

        def action_open_project_context(self) -> None:
            project = self.state.current_project_name or self.state.current_task_project
            if not project:
                self.notify("Select a project row or a task with a project", severity="warning")
                return
            self._open_project_workspace(project)

        def action_time_add(self) -> None:
            selected = self._selected_time_row()
            initial_task = str((selected or {}).get("task_short_uuid") or self.state.current_task_ref or "")
            self.push_screen(
                TimeEntryModal(mode="add", initial_task_ref=initial_task),
                lambda payload: self._on_time_entry_payload("add", None, payload),
            )

        def action_time_amend(self) -> None:
            selected = self._selected_time_row()
            if selected is None:
                self.notify("Select an interval row to amend", severity="warning")
                return
            self.push_screen(
                TimeEntryModal(mode="amend", item=selected),
                lambda payload: self._on_time_entry_payload("amend", selected, payload),
            )

        def action_time_delete(self) -> None:
            selected = self._selected_time_row()
            if selected is None:
                self.notify("Select an interval row to delete", severity="warning")
                return
            self.push_screen(
                ConfirmTimeDeleteModal(selected),
                lambda confirmed: self._on_time_delete_confirmed(selected, confirmed),
            )

        def action_time_trash(self) -> None:
            asyncio.create_task(self._open_time_trash_async())

        def action_time_session_start(self) -> None:
            selected = self._selected_time_row()
            initial_task = str((selected or {}).get("task_short_uuid") or self.state.current_task_ref or "")
            self.push_screen(
                TimeSessionStartModal(initial_task),
                self._on_time_session_start_selected,
            )

        def action_time_session_stop(self) -> None:
            session = self._selected_time_session()
            if session is None:
                self.notify("Select an active timer to stop", severity="warning")
                return
            asyncio.create_task(self._apply_time_session_stop_async(session))

        def action_time_session_stop_all(self) -> None:
            count = len(self.state.time_session_rows)
            if not count:
                self.notify("No active timers to stop", severity="information")
                return
            self.push_screen(
                ConfirmTimeSessionModal(
                    title=f"Stop all {count} active timers?",
                    details="Each elapsed interval will be written to its task or chain note.",
                    action_label="Stop all",
                ),
                self._on_time_session_stop_all_confirmed,
            )

        def action_time_session_cancel(self) -> None:
            session = self._selected_time_session()
            if session is None:
                self.notify("Select an active timer to cancel", severity="warning")
                return
            task_ref = str(session.get("task_short_uuid") or "")
            self.push_screen(
                ConfirmTimeSessionModal(
                    title=f"Cancel timer for {task_ref}?",
                    details="The pending start will be discarded without writing a time interval.",
                    action_label="Discard timer",
                ),
                lambda confirmed: self._on_time_session_cancel_confirmed(session, confirmed),
            )

        def _on_palette_selected(self, payload: dict[str, Any] | None) -> None:
            if not payload:
                return
            asyncio.create_task(self._execute_palette_command_async(str(payload.get("id") or "")))

        def _on_context_action_selected(self, payload: dict[str, Any] | None) -> None:
            if not payload:
                return
            asyncio.create_task(self._execute_palette_command_async(str(payload.get("id") or "")))

        async def _open_note_history_async(self, target: dict[str, Any]) -> None:
            kind, ref = self._note_history_target(target)
            try:
                history = await asyncio.to_thread(self.svc.note_history, kind, ref)
            except Exception as exc:
                self.notify(f"Could not load note history: {exc}", severity="error")
                return
            revisions = list(history.get("revisions") or [])
            if not revisions:
                self.notify("No earlier revisions for this note", severity="information")
                return
            entries = [
                PaletteEntry(
                    str(item.get("revision_id") or ""),
                    str(item.get("created_at") or "Unknown time"),
                    f"Revision {str(item.get('revision_id') or '')[-12:]}",
                )
                for item in revisions
            ]
            self.push_screen(
                CommandPaletteModal(entries, title="Note history", placeholder="Filter revisions"),
                lambda selected: self._on_note_revision_selected(target, selected),
            )

        def _note_history_target(self, target: dict[str, Any]) -> tuple[str, str]:
            kind = str(target.get("kind") or "")
            ref = str(target.get("project") or "") if kind == "project" else str(target.get("task_ref") or "")
            if not kind or not ref:
                raise RuntimeError("selected note has no history target")
            return kind, ref

        def _on_note_revision_selected(
            self,
            target: dict[str, Any],
            selected: dict[str, Any] | None,
        ) -> None:
            if selected:
                asyncio.create_task(
                    self._open_note_history_diff_async(target, str(selected.get("id") or ""))
                )

        async def _open_note_history_diff_async(self, target: dict[str, Any], revision_id: str) -> None:
            try:
                kind, ref = self._note_history_target(target)
                result = await asyncio.to_thread(self.svc.note_history_diff, kind, ref, revision_id)
            except Exception as exc:
                self.notify(f"Could not load revision diff: {exc}", severity="error")
                return
            self.push_screen(
                NoteHistoryDiffModal(revision_id=revision_id, diff=str(result.get("diff") or "")),
                lambda restore: self._on_note_history_restore_selected(
                    target,
                    revision_id,
                    str(result.get("current_digest") or ""),
                    restore,
                ),
            )

        def _on_note_history_restore_selected(
            self,
            target: dict[str, Any],
            revision_id: str,
            current_digest: str,
            restore: bool,
        ) -> None:
            if restore:
                asyncio.create_task(
                    self._restore_note_history_async(target, revision_id, current_digest)
                )

        async def _restore_note_history_async(
            self,
            target: dict[str, Any],
            revision_id: str,
            current_digest: str,
        ) -> None:
            try:
                kind, ref = self._note_history_target(target)
                result = await asyncio.to_thread(
                    self.svc.restore_note_history,
                    kind,
                    ref,
                    revision_id,
                    expected_current_digest=current_digest,
                )
            except Exception as exc:
                self.notify(f"Could not restore note revision: {exc}", severity="error")
                return
            self.notify(
                f"Restored revision {revision_id}; current version saved as {result.get('preserved_revision_id')}",
                severity="information",
            )
            await self._refresh_after_resource_change_async()

        def _on_add_to_payload(self, kind: str, payload: dict[str, Any] | None) -> None:
            if not payload:
                return
            asyncio.create_task(self._apply_add_to_async(kind, payload))

        def _on_time_entry_payload(
            self,
            mode: str,
            item: dict[str, Any] | None,
            payload: dict[str, str] | None,
        ) -> None:
            if not payload:
                return
            asyncio.create_task(self._apply_time_entry_async(mode, item, payload))

        def _on_time_delete_confirmed(self, item: dict[str, Any], confirmed: bool) -> None:
            if confirmed:
                asyncio.create_task(self._apply_time_delete_async(item))

        def _on_time_restore_selected(self, item: dict[str, Any] | None) -> None:
            if item:
                asyncio.create_task(self._apply_time_restore_async(item))

        def _on_time_session_start_selected(self, task_ref: str | None) -> None:
            if task_ref:
                asyncio.create_task(self._apply_time_session_start_async(task_ref))

        def _on_time_session_stop_all_confirmed(self, confirmed: bool) -> None:
            if confirmed:
                asyncio.create_task(self._apply_time_session_stop_all_async())

        def _on_time_session_cancel_confirmed(
            self,
            session: dict[str, Any],
            confirmed: bool,
        ) -> None:
            if confirmed:
                asyncio.create_task(self._apply_time_session_cancel_async(session))

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
            self.state.current_search_query = query
            if not query:
                self.query_one("#search-notes-table", DataTable).clear()
                self.query_one("#search-trash-table", DataTable).clear()
                self.query_one("#search-events-table", DataTable).clear()
                self.state.search_note_rows = []
                self.state.search_trash_rows = []
                self.state.search_event_rows = []
                self._update_search_results_summary()
                return
            self._run_search(query)

        def on_input_changed(self, event: Input.Changed) -> None:
            if event.input.id == "notes-filter-kind":
                self.state.note_filter_kind = event.value.strip()
                asyncio.create_task(self._refresh_notes_async())
                return
            if event.input.id == "notes-filter-project":
                self.state.note_filter_project = event.value.strip()
                asyncio.create_task(self._refresh_notes_async())
                return
            if event.input.id == "task-filter-project":
                self.state.task_filter_project = event.value.strip()
                self._render_tasks_table()
                return
            if event.input.id == "task-filter-tag":
                self.state.task_filter_tag = event.value.strip()
                self._render_tasks_table()

        def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
            if event.checkbox.id != "task-filter-notes":
                return
            self.state.task_filter_notes_only = bool(event.value)
            self._render_tasks_table()

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "time-refresh":
                asyncio.create_task(self._refresh_time_async())
                return
            if event.button.id == "time-add":
                self.action_time_add()
                return
            if event.button.id == "time-amend":
                self.action_time_amend()
                return
            if event.button.id == "time-delete":
                self.action_time_delete()
                return
            if event.button.id == "time-trash":
                self.action_time_trash()
                return
            if event.button.id == "time-session-start":
                self.action_time_session_start()
                return
            if event.button.id == "time-session-stop":
                self.action_time_session_stop()
                return
            if event.button.id == "time-session-stop-all":
                self.action_time_session_stop_all()
                return
            if event.button.id == "time-session-cancel":
                self.action_time_session_cancel()
                return
            if event.button.id == "notes-filter-clear":
                self.state.note_filter_kind = ""
                self.state.note_filter_project = ""
                self.query_one("#notes-filter-kind", Input).value = ""
                self.query_one("#notes-filter-project", Input).value = ""
                asyncio.create_task(self._refresh_notes_async())
                return
            if event.button.id != "task-filter-clear":
                return
            self.state.task_filter_project = ""
            self.state.task_filter_tag = ""
            self.state.task_filter_notes_only = False
            self.query_one("#task-filter-project", Input).value = ""
            self.query_one("#task-filter-tag", Input).value = ""
            self.query_one("#task-filter-notes", Checkbox).value = False
            self._render_tasks_table()

        def on_select_changed(self, event: Select.Changed) -> None:
            if event.select.id != "time-period":
                return
            period = str(event.value or "").strip()
            if period not in {"all", "today", "week", "month"}:
                return
            self.state.time_period = period
            asyncio.create_task(self._refresh_time_async())

        def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
            if event.data_table.id == "search-trash-table":
                row_index = event.cursor_row
                if 0 <= row_index < len(self.state.search_trash_rows):
                    self._open_search_trash_preview(self.state.search_trash_rows[row_index])
                return
            if event.data_table.id == "time-sessions-table":
                row_index = event.cursor_row
                if row_index < 0 or row_index >= len(self.state.time_session_rows):
                    return
                task_ref = str(self.state.time_session_rows[row_index].get("task_short_uuid") or "").strip()
                if task_ref:
                    self._open_task_workspace(task_ref)
                return
            if event.data_table.id == "time-details-table":
                row_index = event.cursor_row
                if row_index < 0 or row_index >= len(self.state.time_rows):
                    return
                task_ref = str(self.state.time_rows[row_index].get("task_short_uuid") or "").strip()
                if task_ref:
                    self._open_task_workspace(task_ref)
                return
            if event.data_table.id == "recent-table":
                row_index = event.cursor_row
                if row_index < 0 or row_index >= len(self.state.recent_rows):
                    return
                item = self.state.recent_rows[row_index]
                short_uuid = str(item.get("task_short_uuid") or "").strip()
                if not short_uuid:
                    return
                self._open_latest_workspace(short_uuid)
                return
            if event.data_table.id == "tasks-table":
                row_index = event.cursor_row
                if row_index < 0 or row_index >= len(self.state.task_rows):
                    return
                short_uuid = str(_read_row_field(self.state.task_rows[row_index], "short_uuid") or "").strip()
                if not short_uuid:
                    return
                self._open_task_workspace(short_uuid)
                return
            if event.data_table.id == "projects-table":
                row_index = event.cursor_row
                if row_index < 0 or row_index >= len(self.state.project_rows):
                    return
                project_name = str(_read_row_field(self.state.project_rows[row_index], "project") or "").strip()
                if not project_name:
                    return
                self.state.current_project_name = project_name or None
                if self.state.current_project_name and bool(_read_row_field(self.state.project_rows[row_index], "selectable")):
                    self._open_project_workspace(self.state.current_project_name)
            if event.data_table.id == "notes-table":
                row_index = event.cursor_row
                if row_index < 0 or row_index >= len(self.state.note_rows):
                    return
                self._open_note_inventory_row(self.state.note_rows[row_index])

        def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
            table_kind = {
                "search-notes-table": "notes",
                "search-trash-table": "trash",
                "search-events-table": "events",
            }.get(str(event.data_table.id or ""))
            if table_kind:
                self._update_search_result_detail(table_kind, event.cursor_row)

        async def _refresh_recent_async(self) -> None:
            table = self.query_one("#recent-table", DataTable)
            table.clear()
            try:
                self.state.recent_rows = await asyncio.to_thread(self.svc.recent, 80)
            except Exception as exc:
                self.state.recent_rows = []
                self.notify(f"Recent activity refresh failed: {exc}", severity="error")
                return
            for item in self.state.recent_rows:
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

        async def _refresh_notes_async(self) -> None:
            table = self.query_one("#notes-table", DataTable)
            table.clear()
            try:
                self.state.note_rows = await asyncio.to_thread(
                    self.svc.notes,
                    kind=self.state.note_filter_kind,
                    project=self.state.note_filter_project,
                )
            except Exception as exc:
                self.state.note_rows = []
                self.notify(f"Notes refresh failed: {exc}", severity="error")
                return
            for item in self.state.note_rows:
                table.add_row(
                    str(_read_row_field(item, "kind") or ""),
                    str(_read_row_field(item, "identifier", _read_row_field(item, "id")) or ""),
                    str(_read_row_field(item, "title") or ""),
                    str(_read_row_field(item, "project") or ""),
                    str(_read_row_field(item, "progress") or "-") or "-",
                    str(_read_row_field(item, "resources") or "0"),
                    str(_read_row_field(item, "updated") or ""),
                )

        async def _refresh_tasks_async(self) -> None:
            try:
                self.state.task_all_rows = await asyncio.to_thread(self.svc.tasks, 250)
            except Exception as exc:
                self.state.task_all_rows = []
                self.state.task_rows = []
                self._render_tasks_table()
                self.notify(f"Tasks refresh failed: {exc}", severity="error")
                return
            self._render_tasks_table()

        async def _refresh_projects_async(self) -> None:
            table = self.query_one("#projects-table", DataTable)
            table.clear()
            try:
                self.state.project_rows = await asyncio.to_thread(self.svc.project_tree_rows)
            except Exception as exc:
                self.state.project_rows = []
                self.notify(f"Projects refresh failed: {exc}", severity="error")
                return
            for item in self.state.project_rows:
                table.add_row(
                    str(_read_row_field(item, "label") or _read_row_field(item, "project") or ""),
                    str(_read_row_field(item, "count") or ""),
                    str(_read_row_field(item, "progress") or "-"),
                    str(_read_row_field(item, "note") or ""),
                    str(_read_row_field(item, "updated") or ""),
                )

        def _selected_time_row(self) -> dict[str, Any] | None:
            table = self.query_one("#time-details-table", DataTable)
            row = table.cursor_row
            if row < 0 or row >= len(self.state.time_rows):
                return None
            return self.state.time_rows[row]

        def _selected_time_session(self) -> dict[str, Any] | None:
            table = self.query_one("#time-sessions-table", DataTable)
            row = table.cursor_row
            if row < 0 or row >= len(self.state.time_session_rows):
                return None
            return self.state.time_session_rows[row]

        async def _apply_time_session_start_async(self, task_ref: str) -> None:
            try:
                result = await asyncio.to_thread(start_time, self.svc, task_ref)
            except Exception as exc:
                self.notify(f"Timer start failed: {exc}", severity="error")
                return
            timewarrior = result.get("timewarrior")
            if isinstance(timewarrior, dict) and timewarrior.get("error"):
                self.notify(
                    f"Jot timer is pending, but Timewarrior failed: {timewarrior['error']}",
                    severity="error",
                )
            elif result.get("timewarrior_retry") and isinstance(timewarrior, dict) and timewarrior.get("started"):
                self.notify(
                    f"Retried and started Timewarrior for {result.get('task_short_uuid')}",
                    severity="information",
                )
            elif result.get("already_started"):
                self.notify(
                    f"Timer for {result.get('task_short_uuid')} is already running",
                    severity="warning",
                )
            else:
                self.notify(
                    f"Started timer for {result.get('task_short_uuid')}",
                    severity="information",
                )
            await self._refresh_time_sessions_async()

        async def _apply_time_session_stop_async(self, session: dict[str, Any]) -> None:
            task_ref = str(session.get("task_uuid") or session.get("task_short_uuid") or "")
            try:
                result = await asyncio.to_thread(stop_time, self.svc, session)
            except Exception as exc:
                self.notify(f"Timer stop failed: {exc}", severity="error")
                await self._refresh_time_sessions_async()
                return
            if result.get("written"):
                self.notify(
                    f"Stopped timer for {result.get('task_short_uuid')}: "
                    f"{float(result.get('duration_minutes') or 0):g}m recorded",
                    severity="information",
                )
            else:
                self.notify("Stopped timer; that interval was already recorded", severity="warning")
            await self._refresh_after_time_change_async()

        async def _apply_time_session_stop_all_async(self) -> None:
            try:
                result = await asyncio.to_thread(stop_all_time, self.svc)
            except Exception as exc:
                self.notify(f"Stop all timers failed: {exc}", severity="error")
                await self._refresh_time_sessions_async()
                return
            count = int(result.get("count") or 0)
            errors = int(result.get("error_count") or 0)
            if errors:
                self.notify(
                    f"Stopped {count} timers; {errors} could not be stopped",
                    severity="warning",
                )
            else:
                self.notify(f"Stopped {count} timers", severity="information")
            await self._refresh_after_time_change_async()

        async def _apply_time_session_cancel_async(self, session: dict[str, Any]) -> None:
            task_ref = str(session.get("task_uuid") or session.get("task_short_uuid") or "")
            try:
                result = await asyncio.to_thread(cancel_time, self.svc, session)
            except Exception as exc:
                self.notify(f"Timer cancel failed: {exc}", severity="error")
                await self._refresh_time_sessions_async()
                return
            self.notify(
                f"Cancelled timer for {result.get('task_short_uuid')}",
                severity="information",
            )
            await self._refresh_time_sessions_async()

        async def _apply_time_entry_async(
            self,
            mode: str,
            item: dict[str, Any] | None,
            payload: dict[str, str],
        ) -> None:
            try:
                if mode == "add":
                    result = await asyncio.to_thread(add_time, self.svc, payload)
                    if not result.get("written", True):
                        self.notify("That interval already exists", severity="warning")
                        return
                    message = f"Added interval {result.get('timelog_key')}"
                else:
                    if item is None:
                        raise RuntimeError("selected interval is no longer available")
                    result = await asyncio.to_thread(amend_time, self.svc, str(item.get("key") or ""), payload)
                    message = f"Amended interval {result.get('new_timelog_key')}"
            except Exception as exc:
                self.notify(f"Time {mode} failed: {exc}", severity="error")
                return
            self.notify(message, severity="information")
            await self._refresh_after_time_change_async()

        async def _apply_time_delete_async(self, item: dict[str, Any]) -> None:
            try:
                result = await asyncio.to_thread(delete_time, self.svc, str(item.get("key") or ""))
            except Exception as exc:
                self.notify(f"Time delete failed: {exc}", severity="error")
                return
            self.notify(f"Archived interval {result.get('timelog_key')}", severity="information")
            await self._refresh_after_time_change_async()

        async def _open_time_trash_async(self) -> None:
            try:
                items = await asyncio.to_thread(trash_time, self.svc)
            except Exception as exc:
                self.notify(f"Time trash failed: {exc}", severity="error")
                return
            if not items:
                self.notify("No deleted time intervals are available", severity="information")
                return
            self.push_screen(
                TimeTrashModal(items),
                lambda item: self._on_time_restore_selected(item),
            )

        async def _apply_time_restore_async(self, item: dict[str, Any]) -> None:
            try:
                result = await asyncio.to_thread(restore_time, self.svc, item)
            except Exception as exc:
                self.notify(f"Time restore failed: {exc}", severity="error")
                return
            self.notify(f"Restored interval {result.get('timelog_key')}", severity="information")
            await self._refresh_after_time_change_async()

        async def _refresh_after_time_change_async(self) -> None:
            await self._refresh_time_async()
            await self._refresh_recent_async()
            await self._refresh_tasks_async()
            await self._refresh_projects_async()
            await self._refresh_notes_async()

        async def _refresh_time_sessions_async(self) -> None:
            table = self.query_one("#time-sessions-table", DataTable)
            title = self.query_one("#time-sessions-title", Static)
            table.clear()
            try:
                sessions = await asyncio.to_thread(self.svc.timelog_pending)
            except Exception as exc:
                self.state.time_session_rows = []
                title.update("Active timers (unavailable)")
                self.query_one("#time-session-stop", Button).disabled = True
                self.query_one("#time-session-stop-all", Button).disabled = True
                self.query_one("#time-session-cancel", Button).disabled = True
                self.notify(f"Timer refresh failed: {exc}", severity="error")
                return
            self.state.time_session_rows = list(sessions)
            has_sessions = bool(self.state.time_session_rows)
            title.update(f"Active timers ({len(self.state.time_session_rows)})")
            self.query_one("#time-session-stop", Button).disabled = not has_sessions
            self.query_one("#time-session-stop-all", Button).disabled = not has_sessions
            self.query_one("#time-session-cancel", Button).disabled = not has_sessions
            for item in self.state.time_session_rows:
                table.add_row(
                    str(item.get("elapsed") or ""),
                    str(item.get("task_short_uuid") or ""),
                    str(item.get("description") or ""),
                    str(item.get("project") or ""),
                    tui_time_input_value(str(item.get("started") or "")),
                    str(item.get("chain_id") or ""),
                )

        async def _refresh_time_async(self) -> None:
            await self._refresh_time_sessions_async()
            summary = self.query_one("#time-summary", Static)
            tables = {
                "day": self.query_one("#time-day-table", DataTable),
                "project": self.query_one("#time-project-table", DataTable),
                "task": self.query_one("#time-task-table", DataTable),
                "details": self.query_one("#time-details-table", DataTable),
            }
            for table in tables.values():
                table.clear()
            try:
                report = await asyncio.to_thread(
                    self.svc.timelog_report,
                    self.state.time_period,
                    details=True,
                )
            except Exception as exc:
                self.state.time_rows = []
                summary.update(f"Time report failed: {exc}")
                self.notify(f"Time refresh failed: {exc}", severity="error")
                return
            self.state.time_rows = list(report.get("entries") or [])
            summary.update(
                f"{str(report.get('period') or self.state.time_period).capitalize()}: "
                f"{report.get('total') or '0m'} across {report.get('entry_count', 0)} intervals"
            )
            for item in report.get("by_day") or []:
                tables["day"].add_row(
                    str(item.get("name") or ""),
                    str(item.get("duration") or ""),
                    str(item.get("entry_count") or 0),
                )
            for item in report.get("by_project") or []:
                tables["project"].add_row(
                    str(item.get("name") or ""),
                    str(item.get("duration") or ""),
                    str(item.get("entry_count") or 0),
                )
            for item in report.get("by_task") or []:
                tables["task"].add_row(
                    str(item.get("name") or ""),
                    str(item.get("duration") or ""),
                    str(item.get("entry_count") or 0),
                )
            for item in self.state.time_rows:
                tables["details"].add_row(
                    str(item.get("key") or ""),
                    str(item.get("day") or ""),
                    str(item.get("duration") or ""),
                    str(item.get("task_short_uuid") or ""),
                    str(item.get("project") or ""),
                    str(item.get("display_range") or ""),
                )

        def _run_search(self, query: str) -> None:
            asyncio.create_task(self._run_search_async(query))

        def _render_tasks_table(self) -> None:
            table = self.query_one("#tasks-table", DataTable)
            table.clear()
            self.state.task_rows = [
                item for item in self.state.task_all_rows if self._task_matches_filters(item)
            ]
            for item in self.state.task_rows:
                notes = []
                if _read_row_field(item, "has_task_note"):
                    notes.append("task")
                if _read_row_field(item, "has_chain_note"):
                    notes.append("chain")
                if _read_row_field(item, "has_project_note"):
                    notes.append("project")
                table.add_row(
                    str(_read_row_field(item, "short_uuid") or ""),
                    str(_read_row_field(item, "description") or ""),
                    str(_read_row_field(item, "project") or ""),
                    str(_read_row_field(item, "progress") or "-"),
                    ",".join(str(tag) for tag in _read_row_field(item, "tags") or []),
                    ",".join(notes) or "-",
                )

        def _task_matches_filters(self, item: dict[str, Any]) -> bool:
            project_filter = self.state.task_filter_project.strip().lower()
            if project_filter:
                project = str(_read_row_field(item, "project") or "").strip().lower()
                if project_filter not in project:
                    return False
            tag_filter = self.state.task_filter_tag.strip().lower()
            if tag_filter:
                tags = [str(tag).strip().lower() for tag in _read_row_field(item, "tags") or []]
                if not any(tag_filter in tag for tag in tags):
                    return False
            if self.state.task_filter_notes_only and not bool(_read_row_field(item, "has_notes")):
                return False
            return True

        async def _run_search_async(self, query: str) -> None:
            notes_table = self.query_one("#search-notes-table", DataTable)
            trash_table = self.query_one("#search-trash-table", DataTable)
            events_table = self.query_one("#search-events-table", DataTable)
            notes_table.clear()
            trash_table.clear()
            events_table.clear()
            try:
                data = await asyncio.to_thread(self.svc.search, query)
            except Exception as exc:
                self.state.search_note_rows = []
                self.state.search_trash_rows = []
                self.state.search_event_rows = []
                self._update_search_results_summary()
                self.notify(f"Search failed: {exc}", severity="error")
                return
            self.state.search_note_rows = list(data.get("notes", []))
            self.state.search_trash_rows = list(data.get("trash", []))
            self.state.search_event_rows = list(data.get("events", []))
            for item in self.state.search_note_rows:
                title = (
                    str(item.get("description") or "").strip()
                    or str(item.get("project") or "").strip()
                    or str(item.get("chain_id") or "").strip()
                    or str(item.get("task_short_uuid") or "").strip()
                )
                notes_table.add_row(
                    str(item.get("kind") or ""),
                    title,
                    str(item.get("match") or ""),
                )
            for item in self.state.search_trash_rows:
                title = (
                    str(item.get("description") or "").strip()
                    or str(item.get("project") or "").strip()
                    or str(item.get("chain_id") or "").strip()
                    or str(item.get("task_short_uuid") or "").strip()
                )
                trash_table.add_row(
                    str(item.get("kind") or ""),
                    title,
                    str(item.get("match") or ""),
                    str(item.get("original_path") or ""),
                )
            for item in self.state.search_event_rows:
                events_table.add_row(
                    str(item.get("task_short_uuid") or ""),
                    str(item.get("annotation") or ""),
                    str(item.get("ts") or ""),
                )
            self._update_search_results_summary()

        def _update_search_results_summary(self) -> None:
            counts = {
                "notes": len(self.state.search_note_rows),
                "trash": len(self.state.search_trash_rows),
                "events": len(self.state.search_event_rows),
            }
            for kind, count in counts.items():
                label = {"notes": "Search Notes", "trash": "Deleted Notes", "events": "Search Events"}[kind]
                self.query_one(f"#search-{kind}-title", Static).update(f"{label} ({count})")
                self._update_search_result_detail(kind, 0 if count else -1)

        def _update_search_result_detail(self, kind: str, row_index: int) -> None:
            rows = {
                "notes": self.state.search_note_rows,
                "trash": self.state.search_trash_rows,
                "events": self.state.search_event_rows,
            }[kind]
            detail = self.query_one(f"#search-{kind}-detail", Static)
            if not self.state.current_search_query:
                detail.update(f"Enter a search query to find {('deleted ' if kind == 'trash' else '')}{kind}.")
                return
            if not rows:
                detail.update(f"No matching {'deleted notes' if kind == 'trash' else kind}.")
                return
            if row_index < 0 or row_index >= len(rows):
                detail.update("Select a result to see its details.")
                return
            item = rows[row_index]
            if kind == "notes":
                detail.update(
                    f"{item.get('description') or item.get('project') or item.get('chain_id') or item.get('task_short_uuid') or 'Note'}\n"
                    f"Match type: {item.get('match_type') or 'content'}\n"
                    f"Path: {item.get('path') or '(unknown)'}\n"
                    f"Match: {item.get('match') or ''}"
                )
            elif kind == "trash":
                detail.update(
                    f"{item.get('description') or item.get('project') or item.get('chain_id') or item.get('task_short_uuid') or 'Deleted note'}\n"
                    f"Match type: {item.get('match_type') or 'content'}\n"
                    f"Original: {item.get('original_path') or '(unknown)'}\n"
                    f"Deleted: {item.get('deleted_at') or 'unknown'}\n"
                    f"Match: {item.get('match') or ''}"
                )
            else:
                detail.update(
                    f"Task: {item.get('task_short_uuid') or '(unknown)'}\n"
                    "Match type: event\n"
                    f"When: {item.get('ts') or 'unknown'}\n"
                    f"{item.get('annotation') or ''}"
                )

        def _open_search_trash_preview(self, item: dict[str, Any]) -> None:
            try:
                _metadata, body = read_document(Path(str(item.get("path") or "")))
            except Exception as exc:
                self.notify(f"Could not preview trashed note: {exc}", severity="error")
                return
            self.push_screen(
                TrashNotePreviewModal(item, body),
                lambda selected: self._on_search_trash_preview_result(selected),
            )

        def _on_search_trash_preview_result(self, item: dict[str, Any] | None) -> None:
            if item is not None:
                asyncio.create_task(self._restore_search_trash_async(item))

        async def _restore_search_trash_async(self, item: dict[str, Any]) -> None:
            try:
                result = await asyncio.to_thread(
                    self.svc.restore_note_trash,
                    str(item.get("path") or ""),
                )
            except Exception as exc:
                self.notify(f"Restore failed: {exc}", severity="error")
                return
            self.notify(f"Restored note to {result.path}", severity="information")
            if self.state.current_search_query:
                await self._run_search_async(self.state.current_search_query)

        async def _refresh_current_context_async(self) -> None:
            main_tab = self.query_one("#main-tabs", TabbedContent).active
            if main_tab == "browse-tab":
                browse_tab = self.query_one("#browse-browser-tabs", TabbedContent).active
                if browse_tab == "task-browser-pane":
                    if self.state.current_task_ref:
                        await self._refresh_tasks_async()
                        await self._load_task_async(self.state.current_task_ref)
                    return
                if browse_tab == "project-browser-pane":
                    await self._refresh_projects_async()
                    if self.state.current_project_name:
                        await self._load_project_async(self.state.current_project_name)
                    return
            if main_tab == "latest-tab":
                if self.state.current_latest_task_ref:
                    await self._refresh_recent_async()
                    await self._load_latest_task_async(self.state.current_latest_task_ref)
                return
            if main_tab == "notes-tab":
                await self._refresh_notes_async()
                return
            if main_tab == "search-tab":
                if self.state.current_search_query:
                    await self._run_search_async(self.state.current_search_query)
                return
            if main_tab == "time-tab":
                await self._refresh_time_async()
                return
            await self._refresh_recent_async()
            await self._refresh_tasks_async()
            await self._refresh_projects_async()

        async def _execute_palette_command_async(self, command_id: str) -> None:
            if command_id == "browse-tasks":
                self.query_one("#main-tabs", TabbedContent).active = "browse-tab"
                self.query_one("#browse-browser-tabs", TabbedContent).active = "task-browser-pane"
                if self.state.current_task_ref:
                    await self._load_task_async(self.state.current_task_ref)
                self._update_action_hints()
                return
            if command_id == "browse-projects":
                self.query_one("#main-tabs", TabbedContent).active = "browse-tab"
                self.query_one("#browse-browser-tabs", TabbedContent).active = "project-browser-pane"
                if self.state.current_project_name:
                    await self._load_project_async(self.state.current_project_name)
                self._update_action_hints()
                return
            if command_id == "browse-notes":
                self.query_one("#main-tabs", TabbedContent).active = "notes-tab"
                await self._refresh_notes_async()
                self._update_action_hints()
                return
            if command_id == "time-report":
                self.query_one("#main-tabs", TabbedContent).active = "time-tab"
                await self._refresh_time_async()
                self._update_action_hints()
                return
            if command_id == "time-session-start":
                self.action_time_session_start()
                return
            if command_id == "time-session-stop":
                self.action_time_session_stop()
                return
            if command_id == "time-session-stop-all":
                self.action_time_session_stop_all()
                return
            if command_id == "time-session-cancel":
                self.action_time_session_cancel()
                return
            if command_id == "time-add":
                self.action_time_add()
                return
            if command_id == "time-amend":
                self.action_time_amend()
                return
            if command_id == "time-delete":
                self.action_time_delete()
                return
            if command_id == "time-restore":
                self.action_time_trash()
                return
            if command_id == "latest-edits":
                self.query_one("#main-tabs", TabbedContent).active = "latest-tab"
                if self.state.current_latest_task_ref:
                    await self._load_latest_task_async(self.state.current_latest_task_ref)
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
            if command_id == "note-history":
                target = self._active_note_target()
                if target:
                    await self._open_note_history_async(target)
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
            self.state.current_task_chain_path = str(chain_note_data.get("path") or "").strip()
            self.state.current_task_has_chain = bool((data.get("nautical") or {}).get("chain_id"))
            self.state.current_task_project = str(task.get("project") or "").strip()
            workspace_notes = [task_note_data, chain_note_data, project_note_data]
            self.state.current_context_has_resources = self._workspace_has_resources(workspace_notes)
            self.state.current_context_has_progress = self._workspace_has_progress(workspace_notes)
            lines.append("")
            events = data.get("events") or []
            lines.append(f"Events: {len(events)} total")
            lines.append(f"Task note: {'present' if task_note_data.get('body') else 'empty'}")
            if chain_note_data.get("path"):
                lines.append(f"Chain note: {'present' if chain_note_data.get('body') else 'empty'}")
            if project_note_data.get("path"):
                lines.append(f"Project note: {'present' if project_note_data.get('body') else 'empty'}")
            lines.append("")
            lines.append(
                tui_actions_block(
                    tui_next_actions(
                        scope="task",
                        has_note=bool(task_note_data.get("path")),
                        has_resources=self.state.current_context_has_resources,
                        has_progress=self.state.current_context_has_progress,
                        has_chain=self.state.current_task_has_chain,
                        has_project=bool(self.state.current_task_project),
                    )
                )
            )
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
            self.state.current_latest_task_ref = task_ref
            self.state.current_task_chain_path = str(chain_note_data.get("path") or "").strip()
            self.state.current_task_has_chain = bool((data.get("nautical") or {}).get("chain_id"))
            self.state.current_task_project = str(task.get("project") or "").strip()
            workspace_notes = [task_note_data, chain_note_data, project_note_data]
            self.state.current_context_has_resources = self._workspace_has_resources(workspace_notes)
            self.state.current_context_has_progress = self._workspace_has_progress(workspace_notes)
            lines.append("")
            events = data.get("events") or []
            lines.append(f"Events: {len(events)} total")
            lines.append(f"Task note: {'present' if task_note_data.get('body') else 'empty'}")
            if chain_note_data.get("path"):
                lines.append(f"Chain note: {'present' if chain_note_data.get('body') else 'empty'}")
            if project_note_data.get("path"):
                lines.append(f"Project note: {'present' if project_note_data.get('body') else 'empty'}")
            lines.append("")
            lines.append(
                tui_actions_block(
                    tui_next_actions(
                        scope="task",
                        has_note=bool(task_note_data.get("path")),
                        has_resources=self.state.current_context_has_resources,
                        has_progress=self.state.current_context_has_progress,
                        has_chain=self.state.current_task_has_chain,
                        has_project=bool(self.state.current_task_project),
                    )
                )
            )
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
            self.state.current_context_has_resources = self._workspace_has_resources([note])
            self.state.current_context_has_progress = self._workspace_has_progress([note])
            summary.update(
                "\n".join(
                    [
                        f"Project {project_name}",
                        "",
                        f"Note: {note.get('path') or ''}",
                        "",
                        f"Status: {'present' if body else 'empty'}",
                        "",
                        tui_actions_block(
                            tui_next_actions(
                                scope="project",
                                has_note=bool(note.get("path")),
                                has_resources=self.state.current_context_has_resources,
                                has_progress=self.state.current_context_has_progress,
                            )
                        ),
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
                    if not self.state.current_task_ref:
                        self.notify("Select a task row in Recent first", severity="warning")
                        return
                    result = await asyncio.to_thread(
                        self.svc.add_to_task_heading,
                        self.state.current_task_ref,
                        heading=str(payload.get("heading") or ""),
                        text=str(payload.get("entry") or ""),
                        create_heading=bool(payload.get("create_heading")),
                        exact=False,
                    )
                elif kind == "chain":
                    if not self.state.current_task_ref:
                        self.notify("Select a task row in Recent first", severity="warning")
                        return
                    result = await asyncio.to_thread(
                        self.svc.add_to_chain_heading,
                        self.state.current_task_ref,
                        heading=str(payload.get("heading") or ""),
                        text=str(payload.get("entry") or ""),
                        create_heading=bool(payload.get("create_heading")),
                        exact=False,
                    )
                else:
                    project = self.state.current_project_name or self.state.current_task_project
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
            for token in result.get("warnings") or []:
                self.notify(f"Unknown placeholder left unchanged: {{{token}}}", severity="warning")
            await self._refresh_recent_async()
            await self._refresh_tasks_async()
            await self._refresh_projects_async()
            await self._refresh_notes_async()
            main_tab = self.query_one("#main-tabs", TabbedContent).active
            if main_tab == "latest-tab" and self.state.current_latest_task_ref:
                await self._load_latest_task_async(self.state.current_latest_task_ref)
            elif self.state.current_task_ref:
                await self._load_task_async(self.state.current_task_ref)

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
                    attach_resource,
                    self.svc,
                    target,
                    payload,
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
                    await asyncio.to_thread(open_resource, self.svc, target)
            except Exception as exc:
                self.notify(f"Open resource failed: {exc}", severity="error")
                return
            self.notify(f"Opened resource: {target}", severity="information")

        async def _apply_detach_resource_async(self, target: dict[str, Any], resource: dict[str, Any]) -> None:
            try:
                result = await asyncio.to_thread(
                    detach_resource,
                    self.svc,
                    target,
                    resource,
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
            await self._refresh_notes_async()
            main_tab = self.query_one("#main-tabs", TabbedContent).active
            if main_tab == "latest-tab" and self.state.current_latest_task_ref:
                await self._load_latest_task_async(self.state.current_latest_task_ref)
            elif main_tab == "notes-tab":
                return
            elif self.state.current_project_name and self.query_one("#browse-browser-tabs", TabbedContent).active == "project-browser-pane":
                await self._load_project_async(self.state.current_project_name)
            elif self.state.current_task_ref:
                await self._load_task_async(self.state.current_task_ref)

        async def _apply_progress_async(self, target: dict[str, Any], payload: dict[str, Any]) -> None:
            try:
                result = await asyncio.to_thread(
                    apply_progress,
                    self.svc,
                    target,
                    payload,
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
            if self.query_one("#main-tabs", TabbedContent).active == "time-tab":
                self.query_one("#context-hints", Static).update(
                    "Actions: timer buttons | a add | e amend | d delete | m all actions | Enter open task | u refresh | q quit"
                )
                return
            hints = ["Actions: m menu", "ctrl+p palette", "/ search", "r refresh", "u update", "q quit"]
            active_note = self._active_note_target()
            task_context = self.state.current_task_ref or self.state.current_latest_task_ref
            if active_note:
                hints.append("d delete-note")
                hints.extend(["f attach-resource", "o open-resource", "x detach-resource"])
            else:
                hints.append("select row then Enter")
            if self._progress_targets():
                hints.append("g progress")
            else:
                hints.append("select task/project for progress")
            if self.state.current_task_ref:
                hints.extend(["e edit-task", "a add-task"])
            elif self.state.current_latest_task_ref:
                hints.extend(["e edit-note", "a add-task"])
            else:
                hints.append("select task to edit/add")
            if task_context and self.state.current_task_chain_path:
                hints.append("c add-chain")
            elif task_context and self.state.current_task_has_chain:
                hints.append("open chain tab then c add-chain")
            if self.state.current_project_name or self.state.current_task_project:
                hints.append("p open-project")
            else:
                hints.append("select project for project actions")
            self.query_one("#context-hints", Static).update(" | ".join(hints))

        def _palette_entries(self) -> list[PaletteEntry]:
            entries = [
                PaletteEntry("browse-tasks", "Browse tasks", "Open the task browser workspace"),
                PaletteEntry("browse-projects", "Browse projects", "Open the project browser workspace"),
                PaletteEntry("browse-notes", "Browse notes", "Open the all-notes browser with kind and project filters"),
                PaletteEntry("time-report", "Time report", "Open time totals, rollups, and individual intervals"),
                PaletteEntry("time-session-start", "Start task timer", "Start a pending timer for a task"),
                PaletteEntry("time-session-stop", "Stop selected timer", "Stop the selected timer and record its interval", bool(self._selected_time_session())),
                PaletteEntry("time-session-stop-all", "Stop all timers", "Stop every active timer and record their intervals", bool(self.state.time_session_rows)),
                PaletteEntry("time-session-cancel", "Cancel selected timer", "Discard the selected timer without recording it", bool(self._selected_time_session())),
                PaletteEntry("time-add", "Add time interval", "Record a completed interval manually"),
                PaletteEntry("time-amend", "Amend selected interval", "Correct the selected interval and archive its original", bool(self._selected_time_row())),
                PaletteEntry("time-delete", "Delete selected interval", "Confirm, archive, and remove the selected interval", bool(self._selected_time_row())),
                PaletteEntry("time-restore", "Restore deleted interval", "Browse timelog trash and restore an archived interval"),
                PaletteEntry("latest-edits", "Latest edits", "Open the recent activity workspace"),
                PaletteEntry("search", "Search", "Focus the search tab and input"),
                PaletteEntry("refresh-current", "Refresh current", "Reload the active workspace"),
                PaletteEntry("refresh-all", "Refresh all", "Reload tasks, projects, and recent activity"),
                PaletteEntry("open-selected", "Open selected row", "Jump into the selected task, project, or recent item"),
                PaletteEntry("edit-note", "Edit active note", "Open the active note in your editor; saved changes show a diff", bool(self._active_note_target())),
                PaletteEntry("note-history", "Note history", "Review past revisions and restore one", bool(self._active_note_target())),
                PaletteEntry("delete-note", "Delete active note", "Show a confirmation, then move the active note to trash", bool(self._active_note_target())),
                PaletteEntry("attach-resource", "Attach resource", "Prompt for a file path or URL and store it on the active note", bool(self._active_note_target())),
                PaletteEntry("open-resource", "Open note resource", "Show resources on the active note and open the selected one", bool(self._active_note_target())),
                PaletteEntry("detach-resource", "Detach note resource", "Show resources on the active note and remove the selected one", bool(self._active_note_target())),
                PaletteEntry("update-progress", "Update progress", "Open the progress dialog for task, chain, or project scope", bool(self._progress_targets())),
                PaletteEntry("add-task", "Add to task heading", "Prompt for heading and text, then add a timestamped task entry", bool(self.state.current_task_ref)),
                PaletteEntry("add-chain", "Add to chain heading", "Prompt for heading and text, then add a timestamped chain entry", bool(self.state.current_task_ref and self.state.current_task_chain_path)),
                PaletteEntry("open-project", "Open project workspace", "Open the selected or current project note", bool(self.state.current_project_name or self.state.current_task_project)),
            ]
            return entries

        def _context_action_entries(self) -> list[PaletteEntry]:
            if self.query_one("#main-tabs", TabbedContent).active == "time-tab":
                selected_interval = bool(self._selected_time_row())
                selected_session = bool(self._selected_time_session())
                return [
                    PaletteEntry("time-session-start", "Start task timer", "Start a pending timer for a task"),
                    PaletteEntry("time-session-stop", "Stop selected timer", "Stop and record the selected timer", selected_session),
                    PaletteEntry("time-session-stop-all", "Stop all timers", "Stop and record every active timer", bool(self.state.time_session_rows)),
                    PaletteEntry("time-session-cancel", "Cancel selected timer", "Discard the selected timer without recording it", selected_session),
                    PaletteEntry("time-add", "Add time interval", "Record a completed interval manually"),
                    PaletteEntry("time-amend", "Amend selected interval", "Correct the selected interval", selected_interval),
                    PaletteEntry("time-delete", "Delete selected interval", "Archive and remove the selected interval", selected_interval),
                    PaletteEntry("time-restore", "Restore deleted interval", "Browse timelog trash and restore an interval"),
                ]
            target = self._active_note_target()
            progress_targets = self._progress_targets()
            task_ref = self.state.current_task_ref or self.state.current_latest_task_ref
            project = self.state.current_project_name or self.state.current_task_project
            main_tab = self.query_one("#main-tabs", TabbedContent).active
            note_row = self._selected_note_row() if main_tab == "notes-tab" else None
            if target is None and not progress_targets and not task_ref and not project:
                return []

            scope = str((target or {}).get("kind") or ("project" if project and not task_ref else "task"))
            has_resources = self.state.current_context_has_resources
            has_progress = self.state.current_context_has_progress
            if note_row:
                has_resources = int(note_row.get("resources") or 0) > 0
                has_progress = bool(str(note_row.get("progress") or "").strip())
                scope = str((target or {}).get("kind") or "").strip() or scope
            entries = tui_context_action_entries(
                scope=scope,
                has_note=target is not None,
                has_resources=has_resources,
                has_progress=has_progress,
                has_chain=bool(task_ref and self.state.current_task_has_chain),
                has_project=bool(project),
            )
            valid: set[str] = set()
            if target is not None:
                valid.update({"edit-note", "note-history", "delete-note", "attach-resource"})
                if has_resources:
                    valid.update({"open-resource", "detach-resource"})
            if progress_targets:
                valid.add("update-progress")
            if task_ref and main_tab != "notes-tab":
                valid.add("add-task")
                if self.state.current_task_chain_path:
                    valid.add("add-chain")
            if project and main_tab != "notes-tab":
                valid.add("open-project")
            return [entry for entry in entries if entry.id in valid]

        def _progress_targets(self) -> list[dict[str, Any]]:
            main_tab = self.query_one("#main-tabs", TabbedContent).active
            if main_tab not in {"browse-tab", "latest-tab", "notes-tab"}:
                return []
            if main_tab == "notes-tab":
                item = self._selected_note_row()
                if not item:
                    return []
                kind = str(item.get("kind") or "")
                if kind == "task-note":
                    task_ref = str(item.get("task_short_uuid") or item.get("id") or "").strip()
                    return [{"kind": "task", "task_ref": task_ref}] if task_ref else []
                if kind == "chain-note":
                    chain_id = str(item.get("chain_id") or item.get("id") or "").strip()
                    if not chain_id:
                        return []
                    try:
                        task_ref = self.svc.task_ref_for_chain_id(chain_id)
                    except Exception:
                        return []
                    return [{"kind": "chain", "task_ref": task_ref}]
                if kind == "project-note":
                    project = str(item.get("project") or item.get("id") or "").strip()
                    return [{"kind": "project", "project": project}] if project else []
                return []
            if main_tab == "browse-tab":
                browse_tab = self.query_one("#browse-browser-tabs", TabbedContent).active
                if browse_tab == "project-browser-pane":
                    current_project = self.state.current_project_name
                    return [{"kind": "project", "project": current_project}] if current_project else []
            active_task_ref = self.state.current_latest_task_ref if main_tab == "latest-tab" else self.state.current_task_ref
            if not active_task_ref:
                return []
            targets: list[dict[str, Any]] = [{"kind": "task", "task_ref": active_task_ref}]
            if self.state.current_task_has_chain:
                targets.append({"kind": "chain", "task_ref": active_task_ref})
            if self.state.current_task_project:
                targets.append({"kind": "project", "project": self.state.current_task_project})
            return targets

        def _active_note_target(self) -> dict[str, Any] | None:
            main_tab = self.query_one("#main-tabs", TabbedContent).active
            if main_tab == "notes-tab":
                return self._active_note_target_from_note_row()
            if main_tab == "browse-tab":
                browse_tab = self.query_one("#browse-browser-tabs", TabbedContent).active
                if browse_tab == "task-browser-pane":
                    if not self.state.current_task_ref:
                        return None
                    active = self.query_one("#task-workspace-tabs", TabbedContent).active
                    if active == "chain-note-pane":
                        note_path = self.svc.chain_note_path_for_task_ref(self.state.current_task_ref)
                        return {
                            "kind": "chain",
                            "label": "chain note",
                            "task_ref": self.state.current_task_ref,
                            "path": note_path,
                            "trash_path": str(preview_trash_path(self.svc.config, Path(note_path))),
                        }
                    if active == "project-note-pane":
                        project = self.state.current_task_project or self.state.current_project_name
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
                    note_path = self.svc.task_note_path_for_task_ref(self.state.current_task_ref)
                    return {
                        "kind": "task",
                        "label": "task note",
                        "task_ref": self.state.current_task_ref,
                        "path": note_path,
                        "trash_path": str(preview_trash_path(self.svc.config, Path(note_path))),
                    }
                if browse_tab == "project-browser-pane":
                    project = self.state.current_project_name or self.state.current_task_project
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
                if not self.state.current_latest_task_ref:
                    return None
                active = self.query_one("#latest-workspace-tabs", TabbedContent).active
                if active == "latest-chain-note-pane":
                    note_path = self.svc.chain_note_path_for_task_ref(self.state.current_latest_task_ref)
                    return {
                        "kind": "chain",
                        "label": "chain note",
                        "task_ref": self.state.current_latest_task_ref,
                        "path": note_path,
                        "trash_path": str(preview_trash_path(self.svc.config, Path(note_path))),
                    }
                if active == "latest-project-note-pane":
                    project = self.state.current_task_project
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
                note_path = self.svc.task_note_path_for_task_ref(self.state.current_latest_task_ref)
                return {
                    "kind": "task",
                    "label": "task note",
                    "task_ref": self.state.current_latest_task_ref,
                    "path": note_path,
                    "trash_path": str(preview_trash_path(self.svc.config, Path(note_path))),
                }
            return None

        def _selected_note_row(self) -> dict[str, Any] | None:
            try:
                table = self.query_one("#notes-table", DataTable)
            except Exception:
                return None
            row = table.cursor_row
            if row < 0 or row >= len(self.state.note_rows):
                return None
            return self.state.note_rows[row]

        def _active_note_target_from_note_row(self) -> dict[str, Any] | None:
            item = self._selected_note_row()
            if not item:
                return None
            kind = str(item.get("kind") or "").strip()
            path = str(item.get("path") or "").strip()
            if not path:
                return None
            if kind == "task-note":
                task_ref = str(item.get("task_short_uuid") or item.get("id") or "").strip()
                return {
                    "kind": "task",
                    "label": "task note",
                    "task_ref": task_ref,
                    "path": path,
                    "trash_path": str(preview_trash_path(self.svc.config, Path(path))),
                }
            if kind == "chain-note":
                chain_id = str(item.get("chain_id") or item.get("id") or "").strip()
                try:
                    task_ref = self.svc.task_ref_for_chain_id(chain_id)
                except Exception:
                    return None
                return {
                    "kind": "chain",
                    "label": "chain note",
                    "task_ref": task_ref,
                    "path": path,
                    "trash_path": str(preview_trash_path(self.svc.config, Path(path))),
                }
            if kind == "project-note":
                project = str(item.get("project") or item.get("id") or "").strip()
                return {
                    "kind": "project",
                    "label": "project note",
                    "project": project,
                    "path": path,
                    "trash_path": str(preview_trash_path(self.svc.config, Path(path))),
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
            if main_tab == "latest-tab" and self.state.current_latest_task_ref:
                await self._load_latest_task_async(self.state.current_latest_task_ref)
            elif self.state.current_task_ref:
                await self._load_task_async(self.state.current_task_ref)
            elif self.state.current_project_name:
                await self._load_project_async(self.state.current_project_name)

        def _open_task_workspace(self, task_ref: str) -> None:
            self.state.current_task_ref = task_ref
            self.state.current_project_name = None
            self.query_one("#main-tabs", TabbedContent).active = "browse-tab"
            self.query_one("#browse-browser-tabs", TabbedContent).active = "task-browser-pane"
            asyncio.create_task(self._load_task_async(task_ref))
            self._update_action_hints()

        def _open_latest_workspace(self, task_ref: str) -> None:
            self.state.current_latest_task_ref = task_ref
            self.state.current_task_ref = task_ref
            self.state.current_project_name = None
            self.query_one("#main-tabs", TabbedContent).active = "latest-tab"
            asyncio.create_task(self._load_latest_task_async(task_ref))
            self._update_action_hints()

        def _open_project_workspace(self, project_name: str) -> None:
            self.state.current_project_name = project_name
            self.query_one("#main-tabs", TabbedContent).active = "browse-tab"
            self.query_one("#browse-browser-tabs", TabbedContent).active = "project-browser-pane"
            asyncio.create_task(self._load_project_async(project_name))
            self._update_action_hints()

        def _open_note_inventory_row(self, item: dict[str, Any]) -> None:
            kind = str(item.get("kind") or "").strip()
            if kind == "project-note":
                project = str(item.get("project") or item.get("id") or "").strip()
                if project:
                    self._open_project_workspace(project)
                    return
            if kind == "task-note":
                short_uuid = str(item.get("task_short_uuid") or item.get("id") or "").strip()
                if short_uuid:
                    self._open_task_workspace(short_uuid)
                    return
            if kind == "chain-note":
                chain_id = str(item.get("chain_id") or item.get("id") or "").strip()
                if chain_id:
                    try:
                        short_uuid = self.svc.task_ref_for_chain_id(chain_id)
                    except Exception as exc:
                        self.notify(f"Chain open failed: {exc}", severity="error")
                        return
                    self._open_task_workspace(short_uuid)
                    return
            self.notify("This note row has no openable workspace target", severity="warning")

        def _open_active_note_in_editor(self) -> str:
            main_tab = self.query_one("#main-tabs", TabbedContent).active
            if main_tab == "notes-tab":
                target = self._active_note_target_from_note_row()
                if not target:
                    raise RuntimeError("select a note row first")
                kind = str(target.get("kind") or "")
                with self.suspend():
                    if kind == "task":
                        return self.svc.open_task_note_in_editor(str(target.get("task_ref") or ""))
                    if kind == "chain":
                        return self.svc.open_chain_note_in_editor(str(target.get("task_ref") or ""))
                    if kind == "project":
                        return self.svc.open_project_note_in_editor(str(target.get("project") or ""))
                raise RuntimeError("unknown note row kind")
            if main_tab == "browse-tab":
                browse_tab = self.query_one("#browse-browser-tabs", TabbedContent).active
                if browse_tab == "task-browser-pane":
                    if not self.state.current_task_ref:
                        raise RuntimeError("select a task first")
                    active = self.query_one("#task-workspace-tabs", TabbedContent).active
                    with self.suspend():
                        if active == "chain-note-pane":
                            return self.svc.open_chain_note_in_editor(self.state.current_task_ref)
                        if active == "project-note-pane":
                            project = self.state.current_task_project or self.state.current_project_name
                            if not project:
                                raise RuntimeError("selected task has no project note context")
                            return self.svc.open_project_note_in_editor(project)
                        return self.svc.open_task_note_in_editor(self.state.current_task_ref)
                if browse_tab == "project-browser-pane":
                    project = self.state.current_project_name
                    if not project:
                        raise RuntimeError("select a project first")
                    with self.suspend():
                        return self.svc.open_project_note_in_editor(project)
            if main_tab == "latest-tab":
                if not self.state.current_latest_task_ref:
                    raise RuntimeError("select a recent task first")
                active = self.query_one("#latest-workspace-tabs", TabbedContent).active
                with self.suspend():
                    if active == "latest-chain-note-pane":
                        return self.svc.open_chain_note_in_editor(self.state.current_latest_task_ref)
                    if active == "latest-project-note-pane":
                        project = self.state.current_task_project
                        if not project:
                            raise RuntimeError("selected recent task has no project note context")
                        return self.svc.open_project_note_in_editor(project)
                    return self.svc.open_task_note_in_editor(self.state.current_latest_task_ref)
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
            return render_note_panel(title, note, empty_guidance=tui_note_empty_guidance)

        def _render_events_panel(self, events: list[dict[str, Any]]) -> str:
            return render_events_panel(events)

        def _render_workspace_resources(self, note_items: list[tuple[str, dict[str, Any]]]) -> str:
            return render_workspace_resources(note_items)

        def _render_workspace_progress(self, note_items: list[tuple[str, dict[str, Any]]]) -> str:
            return render_workspace_progress(note_items)

        def _workspace_has_resources(self, notes: list[dict[str, Any]]) -> bool:
            return workspace_has_resources(notes)

        def _workspace_has_progress(self, notes: list[dict[str, Any]]) -> bool:
            return workspace_has_progress(notes)

        def _progress_bar(self, percentage: str, width: int = 24) -> str:
            return progress_bar(percentage, width)

        def _note_excerpt(self, body: str, *, max_lines: int = 16, max_width: int = 92) -> str:
            return note_excerpt(body, max_lines=max_lines, max_width=max_width)

        def _pretty_label(self, key: str) -> str:
            return pretty_label(key)

    return JotTUI(service)


def run_tui(service: JotService) -> int:
    app = build_tui(service)
    app.run()
    return 0
