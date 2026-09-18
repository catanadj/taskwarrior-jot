from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from jot_core.frontmatter import write_document
from jot_core.models import AppConfig
from jot_core.ops import append_op, read_ops
from jot_core.trash import cleanup_trash, list_trash, restore_trash_item


class TrashTests(unittest.TestCase):
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

    def test_list_and_restore_recorded_trash_item(self) -> None:
        with TemporaryDirectory(prefix="jot-trash-") as temporary:
            root = Path(temporary)
            config = self._config(root)
            original = config.tasks_dir / "abc--task.md"
            trashed = config.trash_dir / "20260918T100000Z" / "tasks" / original.name
            trashed.parent.mkdir(parents=True)
            write_document(
                trashed,
                {"kind": "task-note", "task_short_uuid": "abc", "schema_version": 1},
                "body\n",
            )
            append_op(
                config,
                "task_note_delete",
                ts="2026-09-18T10:00:00Z",
                path=str(original),
                trash_path=str(trashed),
                task_short_uuid="abc",
            )

            items = list_trash(config)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].task_short_uuid, "abc")

            restored = restore_trash_item(config, 1)
            self.assertTrue(original.exists())
            self.assertFalse(trashed.exists())
            self.assertEqual(restored.path, str(original))
            self.assertEqual([item["op"] for item in read_ops(config)], ["task_note_delete", "trash_restore"])

    def test_restore_rejects_existing_target_and_cleanup_validates_age(self) -> None:
        with TemporaryDirectory(prefix="jot-trash-") as temporary:
            root = Path(temporary)
            config = self._config(root)
            original = config.tasks_dir / "abc--task.md"
            trashed = config.trash_dir / "20260918T100000Z" / "tasks" / original.name
            trashed.parent.mkdir(parents=True)
            original.parent.mkdir(parents=True)
            original.write_text("already here", encoding="utf-8")
            trashed.write_text("deleted copy", encoding="utf-8")
            append_op(
                config,
                "task_note_delete",
                ts="2026-09-18T10:00:00Z",
                path=str(original),
                trash_path=str(trashed),
            )

            with self.assertRaisesRegex(RuntimeError, "already exists"):
                restore_trash_item(config, 1)
            with self.assertRaisesRegex(RuntimeError, "at least 1 day"):
                cleanup_trash(config, older_than_days=0)

    def test_list_discovers_orphaned_note_from_trash_layout(self) -> None:
        with TemporaryDirectory(prefix="jot-trash-") as temporary:
            root = Path(temporary)
            config = self._config(root)
            orphan = config.trash_dir / "20260918T100000Z" / "tasks" / "abc--orphan.md"
            orphan.parent.mkdir(parents=True)
            write_document(
                orphan,
                {"kind": "task-note", "task_short_uuid": "abc", "schema_version": 1},
                "body\n",
            )

            items = list_trash(config)

            self.assertEqual(len(items), 1)
            self.assertTrue(items[0].orphaned)
            self.assertEqual(items[0].kind, "task-note")


if __name__ == "__main__":
    unittest.main()
