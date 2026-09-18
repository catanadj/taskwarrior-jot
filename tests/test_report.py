from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from jot_core.frontmatter import write_document
from jot_core.models import AppConfig, TimelogReport
from jot_core.ops import append_op
from jot_core.report import (
    list_notes,
    list_project_notes,
    normalize_note_kinds,
    project_rollup,
    recent_activity,
)


class ReportTests(unittest.TestCase):
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
            editor_diff_color="auto",
            editor_post_save_actions=True,
            color_mode="never",
            default_format="text",
            nautical_enabled=False,
            timewarrior_enabled=False,
        )

    def test_note_inventory_activity_and_project_listing(self) -> None:
        with TemporaryDirectory(prefix="jot-report-") as temporary:
            root = Path(temporary)
            config = self._config(root)
            config.tasks_dir.mkdir(parents=True)
            config.chains_dir.mkdir()
            project_dir = config.projects_dir / "work"
            project_dir.mkdir(parents=True)
            write_document(
                config.tasks_dir / "abc--task.md",
                {
                    "kind": "task-note",
                    "task_short_uuid": "abc",
                    "description": "Vendor report",
                    "project": "work",
                    "updated": "2026-09-18T10:00:00Z",
                    "schema_version": 1,
                },
                "# Report\nBody\n",
            )
            write_document(
                config.chains_dir / "chain--cycle.md",
                {"kind": "chain-note", "chain_id": "chain", "updated": "2026-09-17T10:00:00Z", "schema_version": 1},
                "# Cycle\n",
            )
            write_document(
                project_dir / "index.md",
                {"kind": "project-note", "project": "work", "updated": "2026-09-16T10:00:00Z", "schema_version": 1},
                "# Work\n",
            )
            append_op(
                config,
                "event_add",
                ts="2026-09-18T11:00:00Z",
                task_short_uuid="abc",
                project="work",
                annotation="vendor contacted",
            )

            notes = list_notes(config, project="WORK")
            self.assertEqual([item["kind"] for item in notes], ["task-note", "project-note"])
            self.assertEqual(list_project_notes(config)[0]["project"], "work")
            activity = recent_activity(config, limit=2)
            self.assertEqual(len(activity), 2)
            self.assertEqual(activity[0].kind, "event")
            self.assertEqual(recent_activity(config, kinds={"event"})[0].title, "vendor contacted")

    def test_project_rollup_collects_tasks_chains_recent_and_timelog(self) -> None:
        with TemporaryDirectory(prefix="jot-report-") as temporary:
            root = Path(temporary)
            config = self._config(root)
            config.tasks_dir.mkdir(parents=True)
            config.chains_dir.mkdir()
            config.projects_dir.mkdir()
            (config.projects_dir / "work").mkdir()
            write_document(
                config.projects_dir / "work" / "index.md",
                {"kind": "project-note", "project": "work", "updated": "2026-09-18T10:00:00Z", "schema_version": 1},
                "# Work\n## Goals\n",
            )
            write_document(
                config.tasks_dir / "abc--task.md",
                {"kind": "task-note", "task_short_uuid": "abc", "project": "work", "schema_version": 1},
                "# Task\n",
            )
            write_document(
                config.chains_dir / "chain--cycle.md",
                {"kind": "chain-note", "chain_id": "chain", "project": "work", "updated": "2026-09-18T09:00:00Z", "schema_version": 1},
                "# Chain\n",
            )
            task = {"uuid": "abc-full", "short_uuid": "abc", "description": "Task", "project": "work", "tags": [], "chain_id": "chain", "due": None}
            report = TimelogReport.from_mapping({"period": "week", "total": "0m"})
            with mock.patch("jot_core.report.report_time_logs", return_value=report):
                rollup = project_rollup(config, [task], "work", limit=5)

            self.assertEqual(rollup.project, "work")
            self.assertEqual(len(rollup.tasks), 1)
            self.assertEqual(rollup.tasks[0]["notes"]["task"], True)
            self.assertEqual(rollup.chains[0]["task_count"], 1)
            self.assertIn("Goals", rollup.note["headings"])

        self.assertEqual(normalize_note_kinds(["task", "project-note"]), {"task-note", "project-note"})
        with self.assertRaisesRegex(RuntimeError, "unknown note kind"):
            normalize_note_kinds(["unknown"])
        with self.assertRaisesRegex(RuntimeError, "limit"):
            recent_activity(self._config(Path("/tmp")), limit=0)


if __name__ == "__main__":
    unittest.main()
