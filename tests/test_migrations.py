from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from jot_core.config import ensure_app_dirs
from jot_core.frontmatter import read_document, write_document
from jot_core.migrations import migrate_notes
from jot_core.models import AppConfig


class MigrationTests(unittest.TestCase):
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

    def test_dry_run_does_not_modify_legacy_note(self) -> None:
        with TemporaryDirectory(prefix="jot-migrate-") as temporary:
            root = Path(temporary)
            config = self._config(root)
            ensure_app_dirs(config)
            note = config.tasks_dir / "abc--legacy.md"
            write_document(note, {"kind": "task-note", "task_short_uuid": "abc"}, "# Legacy\n")
            before = note.read_text(encoding="utf-8")

            result = migrate_notes(config, dry_run=True)

            self.assertTrue(result.dry_run)
            self.assertEqual(result.planned, 1)
            self.assertEqual(result.migrated, 0)
            self.assertEqual(note.read_text(encoding="utf-8"), before)

    def test_future_schema_blocks_migration_without_backup(self) -> None:
        with TemporaryDirectory(prefix="jot-migrate-") as temporary:
            root = Path(temporary)
            config = self._config(root)
            ensure_app_dirs(config)
            note = config.tasks_dir / "abc--future.md"
            write_document(
                note,
                {"kind": "task-note", "task_short_uuid": "abc", "schema_version": 99},
                "# Future\n",
            )
            before = note.read_text(encoding="utf-8")

            result = migrate_notes(config)

            self.assertEqual(result.blocked, 1)
            self.assertEqual(result.migrated, 0)
            self.assertIsNone(result.backup_path)
            self.assertEqual(note.read_text(encoding="utf-8"), before)

    def test_apply_migrates_and_backups_legacy_note(self) -> None:
        with TemporaryDirectory(prefix="jot-migrate-") as temporary:
            root = Path(temporary)
            config = self._config(root)
            ensure_app_dirs(config)
            note = config.tasks_dir / "abc--legacy.md"
            write_document(note, {"kind": "task-note", "task_short_uuid": "abc"}, "# Legacy\n")

            result = migrate_notes(config)

            self.assertEqual(result.migrated, 1)
            self.assertIsNotNone(result.backup_path)
            metadata, body = read_document(note)
            self.assertEqual(metadata["schema_version"], "1")
            self.assertIn("Legacy", body)
            backup = Path(result.backup_path) / "tasks" / note.name
            self.assertTrue(backup.exists())
            self.assertNotIn("schema_version", read_document(backup)[0])


if __name__ == "__main__":
    unittest.main()
