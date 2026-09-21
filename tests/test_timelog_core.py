from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from jot_core.config import ensure_app_dirs
from jot_core.frontmatter import read_document
from jot_core.models import AppConfig, ResolvedTask, TaskRef
from jot_core.ops import read_ops
from jot_core.timelog import (
    add_time_log,
    delete_time_log,
    list_deleted_time_logs,
    list_time_sessions,
    report_time_logs,
    restore_deleted_time_log,
    start_time_session,
    stop_time_session,
    write_time_log,
)


class TimelogCoreTests(unittest.TestCase):
    def _config(self, root: Path) -> AppConfig:
        return AppConfig(
            config_path=root / "config-jot.toml",
            root_dir=root,
            trash_dir=root / ".jot_trash",
            tasks_dir=root / "tasks",
            chains_dir=root / "chains",
            projects_dir=root / "projects",
            templates_dir=root / "templates",
            editor_command="true",
            editor_show_diff_on_save=True,
            editor_diff_color="never",
            editor_post_save_actions=True,
            color_mode="never",
            default_format="text",
            nautical_enabled=False,
            timewarrior_enabled=False,
        )

    def _task(self) -> ResolvedTask:
        task_uuid = "77946f97-1111-2222-3333-444444444444"
        return ResolvedTask(
            ref=TaskRef(raw="77946f97"),
            task_uuid=task_uuid,
            task_short_uuid="77946f97",
            description="Read book",
            project="personal.reading",
            tags=["study"],
            task={
                "uuid": task_uuid,
                "description": "Read book",
                "project": "personal.reading",
                "tags": ["study"],
            },
        )

    def test_session_start_stop_is_idempotent_and_writes_one_entry(self) -> None:
        with TemporaryDirectory(prefix="jot-timelog-") as temporary:
            config = self._config(Path(temporary))
            ensure_app_dirs(config)
            task = self._task()

            started = start_time_session(config, task, started_at="2026-09-19T09:00:00Z")
            duplicate = start_time_session(config, task, started_at="2026-09-19T09:05:00Z")
            stopped = stop_time_session(config, task, stopped_at="2026-09-19T09:45:00Z", scope="task")

            self.assertFalse(started.already_started)
            self.assertTrue(duplicate.already_started)
            self.assertTrue(stopped.written)
            self.assertEqual(stopped.duration_minutes, 45)
            self.assertEqual(list_time_sessions(config), [])
            note_path = next(config.tasks_dir.glob("*.md"))
            _metadata, body = read_document(note_path)
            self.assertEqual(body.count("jot-time-log"), 1)
            self.assertEqual(
                [item["op"] for item in read_ops(config)],
                ["timelog_session_start", "task_note_timelog", "timelog_session_stop"],
            )

    def test_duplicate_write_is_suppressed_and_report_uses_recorded_minutes(self) -> None:
        with TemporaryDirectory(prefix="jot-timelog-") as temporary:
            config = self._config(Path(temporary))
            ensure_app_dirs(config)
            task = self._task()
            first = add_time_log(
                config,
                task,
                started_at="2026-09-19T10:00:00Z",
                stopped_at="2026-09-19T10:30:00Z",
                scope="task",
            )
            duplicate = write_time_log(
                config,
                task,
                started=datetime(2026, 9, 19, 10, tzinfo=timezone.utc),
                stopped=datetime(2026, 9, 19, 10, 30, tzinfo=timezone.utc),
                scope="task",
            )

            report = report_time_logs(config, period="all", details=True)
            self.assertTrue(first.written)
            self.assertTrue(duplicate.duplicate)
            self.assertEqual(report.total_minutes, 30)
            self.assertEqual(report.entry_count, 1)
            self.assertEqual(len(report.entries), 1)

    def test_concurrent_timelog_writes_preserve_every_interval(self) -> None:
        with TemporaryDirectory(prefix="jot-timelog-concurrent-") as temporary:
            config = self._config(Path(temporary))
            ensure_app_dirs(config)
            task = self._task()
            intervals = [
                (
                    f"2026-09-19T{hour:02d}:00:00Z",
                    f"2026-09-19T{hour:02d}:15:00Z",
                )
                for hour in range(8, 20)
            ]

            with ThreadPoolExecutor(max_workers=8) as executor:
                results = list(
                    executor.map(
                        lambda interval: add_time_log(
                            config,
                            task,
                            started_at=interval[0],
                            stopped_at=interval[1],
                            scope="task",
                        ),
                        intervals,
                    )
                )

            self.assertEqual(sum(result.written for result in results), len(intervals))
            note_path = next(config.tasks_dir.glob("*.md"))
            _metadata, body = read_document(note_path)
            self.assertEqual(body.count("jot-time-log"), len(intervals))
            self.assertEqual(
                sum(item["op"] == "task_note_timelog" for item in read_ops(config)),
                len(intervals),
            )

    def test_deleted_entry_can_be_restored_and_is_not_duplicated(self) -> None:
        with TemporaryDirectory(prefix="jot-timelog-") as temporary:
            config = self._config(Path(temporary))
            ensure_app_dirs(config)
            task = self._task()
            written = add_time_log(
                config,
                task,
                started_at="2026-09-19T11:00:00Z",
                stopped_at="2026-09-19T11:15:00Z",
                scope="task",
            )

            deleted = delete_time_log(config, written.timelog_key)
            self.assertEqual(deleted.operation, "delete")
            self.assertEqual(len(list_deleted_time_logs(config)), 1)
            restored = restore_deleted_time_log(config, written.timelog_key[:6])
            self.assertEqual(restored.operation, "restore")
            self.assertEqual(list_deleted_time_logs(config), [])
            with self.assertRaisesRegex(RuntimeError, "not found"):
                restore_deleted_time_log(config, written.timelog_key[:6])
            self.assertEqual(report_time_logs(config, period="all").total_minutes, 15)

    def test_session_lifecycle_delegates_to_timelog_store(self) -> None:
        with TemporaryDirectory(prefix="jot-timelog-") as temporary:
            config = self._config(Path(temporary))
            ensure_app_dirs(config)
            task = self._task()
            with mock.patch("jot_core.timelog_store.read_sessions", wraps=lambda path: {}) as read_sessions:
                start_time_session(config, task, started_at="2026-09-19T10:00:00Z")
            self.assertGreaterEqual(read_sessions.call_count, 1)


if __name__ == "__main__":
    unittest.main()
