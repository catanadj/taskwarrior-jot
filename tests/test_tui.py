from __future__ import annotations

import asyncio
import unittest
from typing import Any
from unittest import mock

from jot_tui.app import build_tui

try:
    from textual.widgets import Button, DataTable, Static, TabbedContent
except ImportError:  # pragma: no cover - exercised in dependency-free CLI environments
    Button = DataTable = Static = TabbedContent = None  # type: ignore[assignment,misc]


async def _call_inline(function: Any, *args: Any, **kwargs: Any) -> Any:
    return function(*args, **kwargs)


class FakeTuiService:
    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, Any]] = {}
        self.intervals: list[dict[str, Any]] = []
        self.cancelled: list[str] = []

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


@unittest.skipIf(DataTable is None, "Textual is not installed")
class TuiPilotTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        patcher = mock.patch("jot_tui.app.asyncio.to_thread", new=_call_inline)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def asyncSetUp(self) -> None:
        asyncio.get_running_loop().set_debug(False)

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
