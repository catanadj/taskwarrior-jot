from __future__ import annotations

import asyncio
from collections import OrderedDict
from contextlib import nullcontext
from tempfile import TemporaryDirectory
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

from jot_tui.app import build_tui
from jot_core.frontmatter import read_document, write_document
from jot_core.models import AppConfig, ResolvedTask, TaskRef
from jot_core.ops import append_op
from jot_core.services import JotService
from jot_core.taskwarrior import TaskwarriorClient

try:
    from textual.widgets import Button, DataTable, Input, Static, TabbedContent
except ImportError:  # pragma: no cover - exercised in dependency-free CLI environments
    Button = DataTable = Input = Static = TabbedContent = None  # type: ignore[assignment,misc]


async def _call_inline(function: Any, *args: Any, **kwargs: Any) -> Any:
    return function(*args, **kwargs)


class FakeTuiService:
    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, Any]] = {}
        self.intervals: list[dict[str, Any]] = []
        self.cancelled: list[str] = []
        self.config = SimpleNamespace(root_dir=Path("/tmp"), trash_dir=Path("/tmp/.jot_trash"))
        self.fail_tasks = False

    def add_to_task_heading(self, task_ref: str, **kwargs: Any) -> dict[str, Any]:
        return {
            "task_short_uuid": task_ref,
            "path": "/tmp/2d6d7d7d--read-book.md",
            "heading": kwargs["heading"],
            "heading_match": "exact",
            "entry": kwargs["text"],
        }

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        return [
            {
                "ts": "2026-07-14T09:00:00Z",
                "kind": "task_note_edit",
                "task_short_uuid": "2d6d7d7d",
                "summary": "Updated reading notes",
            }
        ]

    def tasks(self, limit: int = 200) -> list[dict[str, Any]]:
        if self.fail_tasks:
            raise RuntimeError("task service unavailable")
        return [
            {
                "uuid": "2d6d7d7d-1111-2222-3333-444444444444",
                "short_uuid": "2d6d7d7d",
                "description": "Read book",
                "project": "reading",
                "tags": ["study"],
                "chain_id": "",
                "status": "pending",
                "progress": "120/350 pages",
                "has_task_note": True,
                "has_chain_note": False,
                "has_project_note": True,
            }
        ]

    def project_tree_rows(self, limit: int = 1000) -> list[dict[str, Any]]:
        return [
            {
                "project": "reading",
                "label": "reading",
                "depth": 0,
                "count": 1,
                "note": "yes",
                "progress": "1/3 books",
                "updated": "2026-07-14T09:00:00Z",
                "selectable": True,
            }
        ]

    def notes(self, *, kind: str = "", project: str = "") -> list[dict[str, Any]]:
        return [
            {
                "kind": "task-note",
                "id": "2d6d7d7d",
                "title": "Read book",
                "project": "reading",
                "progress": "120/350 pages",
                "resources": [],
                "updated": "2026-07-14T09:00:00Z",
                "path": "/tmp/2d6d7d7d--read-book.md",
            }
        ]

    def task_workspace(self, task_ref: str) -> dict[str, Any]:
        return {
            "task": {
                "short_uuid": task_ref,
                "description": "Read book",
                "project": "reading",
                "tags": ["study"],
            },
            "nautical": {},
            "notes": {
                "task": {
                    "path": "/tmp/2d6d7d7d--read-book.md",
                    "body": "Chapter 4 notes",
                    "resources": [],
                    "progress": None,
                },
                "chain": {},
                "project": {},
            },
            "events": [],
        }

    def project_workspace(self, project_name: str) -> dict[str, Any]:
        return {
            "project": project_name,
            "note": {"path": f"/tmp/{project_name}.md", "body": "Project notes", "resources": [], "progress": None},
        }

    def task_note_path_for_task_ref(self, task_ref: str) -> str:
        return f"/tmp/{task_ref}--read-book.md"

    def chain_note_path_for_task_ref(self, task_ref: str) -> str:
        return f"/tmp/{task_ref}--chain.md"

    def project_note_path_for_name(self, project_name: str) -> str:
        return f"/tmp/{project_name}.md"

    def timelog_pending(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self.sessions.values()]

    def timelog_report(self, period: str = "week", *, details: bool = True) -> dict[str, Any]:
        total = sum(int(item["minutes"]) for item in self.intervals)
        return {
            "period": period,
            "total": f"{total}m",
            "total_minutes": total,
            "entry_count": len(self.intervals),
            "by_day": [],
            "by_project": [],
            "by_task": [],
            "entries": [dict(item) for item in self.intervals],
        }

    def timelog_start(self, task_ref: str, *, started_at: str = "") -> dict[str, Any]:
        short_uuid = task_ref[:8]
        if short_uuid in self.sessions:
            return {**self.sessions[short_uuid], "already_started": True}
        session = {
            "task_uuid": f"{short_uuid}-1111-2222-3333-444444444444",
            "task_short_uuid": short_uuid,
            "description": f"Task {short_uuid}",
            "project": "reading",
            "chain_id": "",
            "started": started_at or "2026-07-14T09:00:00Z",
            "elapsed": "5m",
        }
        self.sessions[short_uuid] = session
        return dict(session)

    def timelog_stop(
        self,
        task_ref: str,
        *,
        stopped_at: str = "",
        scope: str = "auto",
    ) -> dict[str, Any]:
        short_uuid = task_ref[:8]
        self.sessions.pop(short_uuid)
        interval = {
            "key": f"key-{short_uuid}",
            "day": "2026-07-14",
            "duration": "30m",
            "duration_minutes": 30,
            "minutes": 30,
            "task_short_uuid": short_uuid,
            "project": "reading",
            "display_range": "12:00-12:30",
            "written": True,
        }
        self.intervals.append(interval)
        return dict(interval)

    def timelog_stop_all(self, *, stopped_at: str = "", scope: str = "auto") -> dict[str, Any]:
        task_refs = list(self.sessions)
        items = [self.timelog_stop(task_ref) for task_ref in task_refs]
        return {"count": len(items), "error_count": 0, "items": items, "errors": []}

    def timelog_cancel(self, task_ref: str) -> dict[str, Any]:
        short_uuid = task_ref[:8]
        session = self.sessions.pop(short_uuid)
        self.cancelled.append(short_uuid)
        return dict(session)


class RealTuiTaskwarrior(TaskwarriorClient):
    def __init__(self) -> None:
        super().__init__(task_bin="task")
        self.task = {
            "uuid": "2d6d7d7d-1111-2222-3333-444444444444",
            "description": "Read book",
            "project": "reading",
            "tags": ["study"],
            "status": "pending",
        }

    def list_tasks(self, *, limit: int = 200, status: str = "pending") -> list[dict[str, Any]]:
        return [dict(self.task)]

    def resolve_task(self, raw_ref: str) -> ResolvedTask:
        return ResolvedTask(
            ref=TaskRef(raw=raw_ref),
            task_uuid=self.task["uuid"],
            task_short_uuid=self.task["uuid"].split("-", 1)[0],
            description=self.task["description"],
            project=self.task["project"],
            tags=list(self.task["tags"]),
            task=dict(self.task),
        )

    def annotations_for_task(self, task: ResolvedTask) -> list[dict[str, Any]]:
        return []


def real_service_fixture(root: Path) -> JotService:
    tasks_dir = root / "tasks"
    chains_dir = root / "chains"
    projects_dir = root / "projects"
    templates_dir = root / "templates"
    trash_dir = root / "trash"
    for path in (tasks_dir, chains_dir, projects_dir, templates_dir, trash_dir):
        path.mkdir(parents=True, exist_ok=True)

    config = AppConfig(
        config_path=root / "config-jot.toml",
        root_dir=root,
        trash_dir=trash_dir,
        tasks_dir=tasks_dir,
        chains_dir=chains_dir,
        projects_dir=projects_dir,
        templates_dir=templates_dir,
        editor_command="",
        editor_show_diff_on_save=False,
        editor_diff_color="never",
        editor_post_save_actions=False,
        color_mode="never",
        default_format="text",
        nautical_enabled=False,
        timewarrior_enabled=False,
    )
    task_path = tasks_dir / "2d6d7d7d--read-book.md"
    write_document(
        task_path,
        OrderedDict(
            [
                ("task_uuid", "2d6d7d7d-1111-2222-3333-444444444444"),
                ("task_short_uuid", "2d6d7d7d"),
                ("description", "Read book"),
                ("project", "reading"),
                ("updated", "2026-07-14T09:00:00Z"),
            ]
        ),
        "Chapter 4 notes",
    )
    project_path = projects_dir / "reading" / "index.md"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    write_document(project_path, OrderedDict([("project", "reading")]), "Reading project")
    append_op(
        config,
        "task_note_edit",
        task_short_uuid="2d6d7d7d",
        task_uuid="2d6d7d7d-1111-2222-3333-444444444444",
        path=str(task_path),
    )
    return JotService(config=config, taskwarrior=RealTuiTaskwarrior())


@unittest.skipIf(DataTable is None, "Textual is not installed")
class TuiPilotTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        patcher = mock.patch("jot_tui.app.asyncio.to_thread", new=_call_inline)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def asyncSetUp(self) -> None:
        asyncio.get_running_loop().set_debug(False)

    async def test_command_palette_modal_has_a_separate_factory(self) -> None:
        from jot_tui.modals import build_command_palette_modal

        self.assertTrue(callable(build_command_palette_modal))

    async def test_modal_factories_are_grouped_with_legacy_imports_preserved(self) -> None:
        from jot_tui.common_modals import build_common_modals as legacy_common
        from jot_tui.modals import build_common_modals
        from jot_tui.modals.notes import build_note_modals
        from jot_tui.note_modals import build_note_modals as legacy_notes

        self.assertIs(build_common_modals, legacy_common)
        self.assertIs(build_note_modals, legacy_notes)

    async def test_real_service_loads_workspace_rows(self) -> None:
        with TemporaryDirectory(prefix="jot-tui-real-") as temporary:
            service = real_service_fixture(Path(temporary))
            app = build_tui(service, session_refresh_seconds=None)

            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                self.assertEqual(app.query_one("#tasks-table", DataTable).row_count, 1)
                self.assertEqual(app.query_one("#projects-table", DataTable).row_count, 1)
                self.assertEqual(app.query_one("#notes-table", DataTable).row_count, 2)
                self.assertEqual(app.query_one("#recent-table", DataTable).row_count, 1)

                app._open_task_workspace("2d6d7d7d")
                await pilot.pause()
                self.assertIn("Read book", str(app.query_one("#task-summary", Static).render()))
                self.assertIn("Chapter 4 notes", str(app.query_one("#task-note-preview", Static).render()))

    async def test_search_trash_preview_restores_and_refreshes_results(self) -> None:
        with TemporaryDirectory(prefix="jot-tui-trash-search-") as temporary:
            service = real_service_fixture(Path(temporary))
            deleted = service.delete_task_note("2d6d7d7d")
            app = build_tui(service, session_refresh_seconds=None)

            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                app.query_one("#main-tabs", TabbedContent).active = "search-tab"
                app.state.current_search_query = "Chapter 4"
                await app._run_search_async("Chapter 4")

                self.assertEqual(len(app.state.search_trash_rows), 1)
                self.assertEqual(
                    app.state.search_trash_rows[0]["original_path"],
                    str(deleted.note_path),
                )
                app.query_one("#search-results-tabs", TabbedContent).active = "search-trash-pane"
                await pilot.pause()
                table = app.query_one("#search-trash-table", DataTable)
                self.assertEqual(table.row_count, 1)
                self.assertIn("Chapter 4", str(app.state.search_trash_rows[0]["match"]))
                self.assertEqual(app.state.search_trash_rows[0]["description"], "Read book")
                with mock.patch.object(app, "_open_search_trash_preview") as open_preview:
                    app.on_data_table_row_selected(
                        SimpleNamespace(data_table=table, cursor_row=0)
                    )
                    open_preview.assert_called_once_with(app.state.search_trash_rows[0])
                app._open_search_trash_preview(app.state.search_trash_rows[0])
                await pilot.pause()

                self.assertIn("Chapter 4 notes", str(app.screen.query_one("#trash-preview-body", Static).render()))
                await pilot.click("#trash-preview-close-btn")
                await pilot.pause()
                self.assertEqual(app.state.current_search_query, "Chapter 4")
                self.assertEqual(table.row_count, 1)
                self.assertEqual(table.cursor_row, 0)
                app._open_search_trash_preview(app.state.search_trash_rows[0])
                await pilot.pause()
                await pilot.click("#trash-preview-restore-btn")
                await pilot.pause()

                self.assertTrue(Path(str(deleted.note_path)).exists())
                self.assertEqual(app.state.search_trash_rows, [])
                self.assertEqual(app.query_one("#search-trash-table", DataTable).row_count, 0)
                self.assertEqual(app.query_one("#search-notes-table", DataTable).row_count, 1)
                await app._run_search_async("no-such-note-match")
                self.assertEqual(app.state.search_note_rows, [])
                self.assertEqual(app.query_one("#search-notes-table", DataTable).row_count, 0)

    async def test_search_details_show_titles_paths_counts_and_empty_states(self) -> None:
        with TemporaryDirectory(prefix="jot-tui-search-details-") as temporary:
            service = real_service_fixture(Path(temporary))
            service.append_project_note("reading", "Chapter 4 project memo")
            app = build_tui(service, session_refresh_seconds=None)

            async with app.run_test(size=(80, 32)) as pilot:
                await pilot.pause()
                app.query_one("#main-tabs", TabbedContent).active = "search-tab"
                app.state.current_search_query = "Chapter 4"
                await app._run_search_async("Chapter 4")

                notes_table = app.query_one("#search-notes-table", DataTable)
                self.assertEqual(notes_table.row_count, 2)
                self.assertEqual(str(notes_table.get_row_at(0)[1]), "reading")
                self.assertIn("Search Notes (2)", str(app.query_one("#search-notes-title", Static).render()))
                app._update_search_result_detail("notes", 0)
                detail = str(app.query_one("#search-notes-detail", Static).render())
                self.assertIn(str(service.config.projects_dir / "reading" / "index.md"), detail)
                self.assertIn("Match type: content", detail)
                self.assertIn("Chapter 4", detail)
                notes_table.focus()
                notes_table.move_cursor(row=0)
                await pilot.press("down")
                await pilot.pause()
                self.assertIn(str(service.config.tasks_dir / "2d6d7d7d--read-book.md"), str(app.query_one("#search-notes-detail", Static).render()))

                app.state.current_search_query = "no-such-result"
                await app._run_search_async("no-such-result")
                self.assertIn("Search Notes (0)", str(app.query_one("#search-notes-title", Static).render()))
                self.assertIn("No matching notes", str(app.query_one("#search-notes-detail", Static).render()))
                self.assertIn("No matching deleted notes", str(app.query_one("#search-trash-detail", Static).render()))
                self.assertEqual(app.state.current_search_query, "no-such-result")

    async def test_note_history_palette_previews_diff_and_restores_revision(self) -> None:
        with TemporaryDirectory(prefix="jot-tui-history-") as temporary:
            service = real_service_fixture(Path(temporary))
            note_path = service.task_note_path_for_task_ref("2d6d7d7d")
            metadata, body = read_document(Path(note_path))
            metadata["kind"] = "task-note"
            write_document(Path(note_path), metadata, body)
            service.append_task_note("2d6d7d7d", "first history entry")
            service.append_task_note("2d6d7d7d", "second history entry")
            app = build_tui(service, session_refresh_seconds=None)

            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                await app._open_note_history_async({"kind": "task", "task_ref": "2d6d7d7d"})
                await pilot.pause()
                self.assertGreater(app.screen.query_one("#palette-table", DataTable).row_count, 0)
                await pilot.press("enter")
                await pilot.pause()
                self.assertIn("second history entry", str(app.screen.query_one("#history-diff-text", Static).render()))
                await pilot.click("#history-diff-restore-btn")
                await pilot.pause()
                note = Path(service.task_note_path_for_task_ref("2d6d7d7d")).read_text(encoding="utf-8")
                self.assertIn("first history entry", note)
                self.assertNotIn("second history entry", note)

    async def test_real_service_timer_persists_start_and_stop(self) -> None:
        with TemporaryDirectory(prefix="jot-tui-real-") as temporary:
            service = real_service_fixture(Path(temporary))
            app = build_tui(service, session_refresh_seconds=None)

            async with app.run_test(size=(120, 40)) as pilot:
                app.query_one("#main-tabs", TabbedContent).active = "time-tab"
                await pilot.pause()
                service.timelog_start("2d6d7d7d", started_at="2026-07-14T08:30:00Z")
                await app._refresh_time_sessions_async()
                self.assertTrue((service.config.root_dir / "timelog-pending.json").exists())
                self.assertEqual(app.query_one("#time-sessions-table", DataTable).row_count, 1)

                await app._apply_time_session_stop_async(app.state.time_session_rows[0])
                self.assertEqual(service.timelog_pending(), [])
                self.assertEqual(app.query_one("#time-sessions-table", DataTable).row_count, 0)
                self.assertEqual(app.query_one("#time-details-table", DataTable).row_count, 1)

    async def _start_timer(self, pilot: Any, task_ref: str) -> None:
        self.assertTrue(await pilot.click("#time-session-start"))
        await pilot.pause()
        self.assertTrue(await pilot.click("#time-session-task"))
        await pilot.press(*task_ref)
        self.assertTrue(await pilot.click("#start-btn"))
        await pilot.pause()

    async def test_mount_populates_primary_workspaces(self) -> None:
        service = FakeTuiService()
        app = build_tui(service, session_refresh_seconds=None)

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            self.assertEqual(app.query_one("#tasks-table", DataTable).row_count, 1)
            self.assertEqual(app.query_one("#projects-table", DataTable).row_count, 1)
            self.assertEqual(app.query_one("#notes-table", DataTable).row_count, 1)
            self.assertEqual(app.query_one("#recent-table", DataTable).row_count, 1)

            app.query_one("#main-tabs", TabbedContent).active = "time-tab"
            await pilot.pause()
            self.assertIn("Week: 0m", str(app.query_one("#time-summary", Static).render()))
            self.assertEqual(app.query_one("#time-sessions-table", DataTable).row_count, 0)

    async def test_task_refresh_failure_resets_rows_without_background_exception(self) -> None:
        service = FakeTuiService()
        service.fail_tasks = True
        app = build_tui(service, session_refresh_seconds=None)

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            self.assertEqual(app.state.task_all_rows, [])

    async def test_filters_palette_and_add_to_heading_modal(self) -> None:
        service = FakeTuiService()
        app = build_tui(service, session_refresh_seconds=None)

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.click("#task-filter-project")
            await pilot.press(*"reading")
            self.assertEqual(app.query_one("#tasks-table", DataTable).row_count, 1)

            await pilot.click("#task-filter-notes")
            self.assertTrue(app.state.task_filter_notes_only)
            await pilot.click("#task-filter-clear")
            self.assertEqual(app.state.task_filter_project, "")
            self.assertFalse(app.state.task_filter_notes_only)

            app.action_command_palette()
            await pilot.pause()
            await pilot.click("#palette-input")
            await pilot.press(*"refresh")
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(len(app.query("#palette-input")), 0)

            app.state.current_task_ref = "2d6d7d7d"
            app.action_add_to_selected_task()
            await pilot.pause()
            await pilot.click("#heading-input")
            await pilot.press(*"Next steps")
            await pilot.click("#entry-input")
            await pilot.press(*"Call vendor")
            await pilot.click("#add-btn")
            await pilot.pause()
            self.assertEqual(len(app.query("#heading-input")), 0)

    async def test_resource_progress_delete_and_open_actions_call_service(self) -> None:
        service = FakeTuiService()
        service.attach_resource = mock.Mock(return_value={"resource": {"label": "Docs", "target": "https://example.test"}})
        service.detach_resource = mock.Mock(return_value={"resource": {"label": "Docs", "target": "https://example.test"}})
        service.open_resource = mock.Mock(return_value=["xdg-open", "https://example.test"])
        service.update_progress = mock.Mock(return_value={"track": "pages", "progress": {"current": "2", "target": "4", "unit": "pages"}})
        service.delete_task_note = mock.Mock(return_value={"trash_path": "/tmp/.jot_trash/task.md"})
        app = build_tui(service, session_refresh_seconds=None)

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.state.current_task_ref = "2d6d7d7d"
            app.state.current_task_project = "reading"
            target = {"kind": "task", "task_ref": "2d6d7d7d", "path": "/tmp/task.md"}
            await app._apply_attach_resource_async(target, {"target": "https://example.test", "label": "Docs"})
            service.attach_resource.assert_called_once()
            with mock.patch.object(app, "suspend", return_value=nullcontext()):
                await app._apply_open_resource_async({"target": "https://example.test"})
            service.open_resource.assert_called_once_with("https://example.test")
            await app._apply_detach_resource_async(target, {"id": 1, "target": "https://example.test", "label": "Docs"})
            service.detach_resource.assert_called_once()
            await app._apply_progress_async(
                {"kind": "task", "task_ref": "2d6d7d7d"},
                {"operation": "set", "value": "2/4", "track": "pages", "unit": "pages"},
            )
            service.update_progress.assert_called_once()
            await app._apply_delete_async(target)
            service.delete_task_note.assert_called_once_with("2d6d7d7d")

    async def test_workspace_editor_and_palette_navigation_cover_project_paths(self) -> None:
        service = FakeTuiService()
        service.open_task_note_in_editor = mock.Mock(return_value="/tmp/task.md")
        service.open_project_note_in_editor = mock.Mock(return_value="/tmp/reading.md")
        app = build_tui(service, session_refresh_seconds=None)

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.state.current_task_ref = "2d6d7d7d"
            with mock.patch.object(app, "suspend", return_value=nullcontext()):
                self.assertEqual(app._open_active_note_in_editor(), "/tmp/task.md")
            service.open_task_note_in_editor.assert_called_once_with("2d6d7d7d")
            app.state.current_project_name = "reading"
            await app._execute_palette_command_async("browse-projects")
            self.assertEqual(app.query_one("#browse-browser-tabs", TabbedContent).active, "project-browser-pane")
            await app._execute_palette_command_async("search")
            self.assertEqual(app.query_one("#main-tabs", TabbedContent).active, "search-tab")
            await app._execute_palette_command_async("latest-edits")
            self.assertEqual(app.query_one("#main-tabs", TabbedContent).active, "latest-tab")

    async def test_timer_can_be_started_and_stopped_from_time_workspace(self) -> None:
        service = FakeTuiService()
        app = build_tui(service, session_refresh_seconds=None)

        async with app.run_test(size=(120, 40)) as pilot:
            app.query_one("#main-tabs", TabbedContent).active = "time-tab"
            await pilot.pause()
            await self._start_timer(pilot, "2d6d7d7d")

            self.assertEqual(app.query_one("#time-sessions-table", DataTable).row_count, 1)
            self.assertFalse(app.query_one("#time-session-stop", Button).disabled)
            self.assertTrue(await pilot.click("#time-session-stop"))
            await pilot.pause()

            self.assertEqual(service.sessions, {})
            self.assertEqual(len(service.intervals), 1)
            self.assertEqual(app.query_one("#time-sessions-table", DataTable).row_count, 0)
            self.assertEqual(app.query_one("#time-details-table", DataTable).row_count, 1)

    async def test_recent_selection_keeps_details_in_latest_workspace(self) -> None:
        service = FakeTuiService()
        app = build_tui(service, session_refresh_seconds=None)

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            recent = app.query_one("#recent-table", DataTable)
            recent.focus()
            recent.move_cursor(row=0)
            await pilot.press("enter")
            await pilot.pause(0.1)

            self.assertEqual(app.query_one("#main-tabs", TabbedContent).active, "latest-tab")
            self.assertIn("Read book", str(app.query_one("#latest-summary", Static).render()))
            self.assertIn("Chapter 4 notes", str(app.query_one("#latest-task-note-preview", Static).render()))

    async def test_timer_cancel_and_stop_all_confirmations(self) -> None:
        service = FakeTuiService()
        app = build_tui(service, session_refresh_seconds=None)

        async with app.run_test(size=(120, 40)) as pilot:
            app.query_one("#main-tabs", TabbedContent).active = "time-tab"
            await pilot.pause()
            await self._start_timer(pilot, "aaaaaaaa")

            self.assertTrue(await pilot.click("#time-session-cancel"))
            await pilot.pause()
            self.assertTrue(await pilot.click("#confirm-btn"))
            await pilot.pause()
            self.assertEqual(service.cancelled, ["aaaaaaaa"])
            self.assertEqual(service.intervals, [])

            await self._start_timer(pilot, "bbbbbbbb")
            await self._start_timer(pilot, "cccccccc")
            self.assertTrue(await pilot.click("#time-session-stop-all"))
            await pilot.pause()
            self.assertTrue(await pilot.click("#confirm-btn"))
            await pilot.pause()

            self.assertEqual(service.sessions, {})
            self.assertEqual(len(service.intervals), 2)
            self.assertEqual(app.query_one("#time-sessions-table", DataTable).row_count, 0)


if __name__ == "__main__":
    unittest.main()
