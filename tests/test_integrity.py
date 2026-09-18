from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from jot_core.frontmatter import read_document, write_document
from jot_core.integrity import reconcile_integrity, scan_integrity
from jot_core.models import AppConfig, ResolvedTask, TaskRef


class IntegrityTests(unittest.TestCase):
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

    def test_scan_reports_missing_uuid_and_invalid_index(self) -> None:
        with TemporaryDirectory(prefix="jot-integrity-") as temporary:
            root = Path(temporary)
            config = self._config(root)
            config.tasks_dir.mkdir(parents=True)
            write_document(
                config.tasks_dir / "missing.md",
                {"kind": "task-note", "schema_version": 1},
                "note\n",
            )
            (root / "index.json").write_text("not-json\n", encoding="utf-8")

            report = scan_integrity(config, SimpleNamespace())

            kinds = {finding.kind for finding in report.findings}
            self.assertIn("missing-task-uuid", kinds)
            self.assertIn("invalid-index", kinds)
            self.assertEqual(report.counts["total"], 2)

    def test_reconcile_dry_run_then_apply_repairs_stale_metadata(self) -> None:
        with TemporaryDirectory(prefix="jot-integrity-") as temporary:
            root = Path(temporary)
            config = self._config(root)
            config.tasks_dir.mkdir(parents=True)
            note_path = config.tasks_dir / "task.md"
            task_uuid = "2d6d7d7d-1111-2222-3333-444444444444"
            write_document(
                note_path,
                {
                    "kind": "task-note",
                    "schema_version": 1,
                    "task_uuid": task_uuid,
                    "description": "Old description",
                    "project": "old.project",
                    "tags": ["old"],
                },
                "keep this body\n",
            )
            client = SimpleNamespace(
                resolve_task=lambda _ref: ResolvedTask(
                    ref=TaskRef(raw=task_uuid),
                    task_uuid=task_uuid,
                    task_short_uuid=task_uuid[:8],
                    description="New description",
                    project="new.project",
                    tags=["new"],
                    task={"uuid": task_uuid},
                )
            )

            dry_run = reconcile_integrity(config, client, apply=False)
            self.assertTrue(dry_run.dry_run)
            metadata, body = read_document(note_path)
            self.assertEqual(metadata["description"], "Old description")
            self.assertIn("keep this body\n", body)

            repaired = reconcile_integrity(config, client, apply=True)
            self.assertFalse(repaired.dry_run)
            self.assertEqual(repaired.repaired, 1)
            self.assertTrue(repaired.backup_path)
            updated, updated_body = read_document(note_path)
            self.assertEqual(updated["description"], "New description")
            self.assertEqual(updated["project"], "new.project")
            self.assertEqual(updated["tags"], ["new"])
            self.assertIn("keep this body\n", updated_body)
            self.assertTrue((Path(repaired.backup_path) / "notes" / note_path.name).exists())
            self.assertTrue((root / "index.json").exists())


if __name__ == "__main__":
    unittest.main()
