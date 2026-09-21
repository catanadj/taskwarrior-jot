from __future__ import annotations

from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from jot_core.config import ensure_app_dirs
from jot_core.frontmatter import read_document, write_document
from jot_core.migrations import MigrationError, migrate_notes, restore_migration_backup
from jot_core.models import AppConfig
from jot_core.schema import inspect_note_schemas


FIXTURE = Path(__file__).parent / "fixtures" / "jot-0.9"


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
            original_body = read_document(note)[1]
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

    def test_failed_migration_restores_all_touched_notes_and_can_retry(self) -> None:
        with TemporaryDirectory(prefix="jot-migrate-failure-") as temporary:
            root = Path(temporary)
            config = self._config(root)
            ensure_app_dirs(config)
            first = config.tasks_dir / "aaa--first.md"
            second = config.tasks_dir / "bbb--second.md"
            write_document(first, {"kind": "task-note", "task_short_uuid": "aaa"}, "# First\n")
            write_document(second, {"kind": "task-note", "task_short_uuid": "bbb"}, "# Second\n")
            original_write = write_document
            calls = 0

            def fail_second(path: Path, metadata, body: str) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated migration failure")
                original_write(path, metadata, body)

            with mock.patch("jot_core.migrations.write_document", side_effect=fail_second):
                with self.assertRaises(MigrationError) as raised:
                    migrate_notes(config)

            self.assertNotIn("schema_version", read_document(first)[0])
            self.assertNotIn("schema_version", read_document(second)[0])
            self.assertTrue(raised.exception.backup_path.exists())

            retried = migrate_notes(config)

            self.assertEqual(retried.migrated, 2)
            self.assertEqual(read_document(first)[0]["schema_version"], "1")
            self.assertEqual(read_document(second)[0]["schema_version"], "1")

    def test_migration_backup_can_restore_legacy_notes(self) -> None:
        with TemporaryDirectory(prefix="jot-migrate-restore-") as temporary:
            root = Path(temporary)
            config = self._config(root)
            ensure_app_dirs(config)
            note = config.tasks_dir / "abc--legacy.md"
            write_document(note, {"kind": "task-note", "task_short_uuid": "abc"}, "# Legacy\n")
            original_body = read_document(note)[1]

            migrated = migrate_notes(config)
            note.write_text(note.read_text(encoding="utf-8") + "changed\n", encoding="utf-8")

            restored = restore_migration_backup(config, Path(migrated.backup_path or ""))

            self.assertEqual(restored["restored"], 1)
            metadata, body = read_document(note)
            self.assertNotIn("schema_version", metadata)
            self.assertEqual(body, original_body)

    def test_jot_09_fixture_migrates_without_losing_companion_data(self) -> None:
        with TemporaryDirectory(prefix="jot-migrate-fixture-") as temporary:
            root = Path(temporary)
            shutil.copytree(FIXTURE, root, dirs_exist_ok=True)
            config = self._config(root)
            before = {
                relative: (root / relative).read_bytes()
                for relative in (
                    "config-jot.toml",
                    "templates/task-note.md",
                    ".jot_timelog/timelog-pending.json",
                    ".jot_trash/20260901T120000Z/tasks/old.md",
                )
            }
            original_ops = (root / "ops.jsonl").read_text(encoding="utf-8").splitlines()

            inspection = inspect_note_schemas(config)
            self.assertEqual(inspection["counts"]["legacy"], 4)
            result = migrate_notes(config)

            self.assertEqual(result.migrated, 4)
            self.assertEqual(inspect_note_schemas(config)["counts"]["legacy"], 0)
            for relative, content in before.items():
                self.assertEqual((root / relative).read_bytes(), content)
            self.assertTrue(
                (root / "ops.jsonl").read_text(encoding="utf-8").splitlines()[:1] == original_ops
            )
            backup_root = Path(result.backup_path or "")
            self.assertEqual(len(list(backup_root.rglob("*.md"))), 4)


if __name__ == "__main__":
    unittest.main()
