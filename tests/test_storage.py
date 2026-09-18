from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from jot_core.config import ensure_app_dirs
from jot_core.frontmatter import read_document
from jot_core.models import AppConfig, ResolvedTask, TaskRef
from jot_core.ops import read_ops
from jot_core.storage import append_task_note_idempotent, mutate_project_progress_storage


class StorageTests(unittest.TestCase):
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

    def _task(self) -> ResolvedTask:
        task_uuid = "2d6d7d7d-1111-2222-3333-444444444444"
        return ResolvedTask(
            ref=TaskRef(raw="2d6d7d7d"),
            task_uuid=task_uuid,
            task_short_uuid="2d6d7d7d",
            description="Read book",
            project="reading",
            tags=["study"],
            task={"uuid": task_uuid, "description": "Read book", "project": "reading", "tags": ["study"]},
        )

    def test_agent_append_is_idempotent_by_operation_and_entry_marker(self) -> None:
        with TemporaryDirectory(prefix="jot-storage-") as temporary:
            root = Path(temporary)
            config = self._config(root)
            ensure_app_dirs(config)
            task = self._task()

            first = append_task_note_idempotent(
                config,
                task,
                "Read chapter one",
                operation_id="op-1",
                entry_id="entry-1",
            )
            duplicate = append_task_note_idempotent(
                config,
                task,
                "Read chapter one again",
                operation_id="op-1",
                entry_id="entry-1",
            )

            self.assertEqual(first.status, "applied")
            self.assertEqual(duplicate.status, "duplicate")
            note_path = config.tasks_dir / "2d6d7d7d--read-book.md"
            _metadata, body = read_document(note_path)
            self.assertEqual(body.count("<!-- jot-entry:entry-1 -->"), 1)
            self.assertEqual([item["op"] for item in read_ops(config)], ["agent_note_append"])

    def test_project_progress_storage_supports_set_add_and_clear(self) -> None:
        with TemporaryDirectory(prefix="jot-storage-") as temporary:
            root = Path(temporary)
            config = self._config(root)
            ensure_app_dirs(config)

            created = mutate_project_progress_storage(
                config,
                "reading",
                operation="set",
                current=Decimal("2"),
                target=Decimal("10"),
                unit="books",
                status="active",
            )
            added = mutate_project_progress_storage(
                config,
                "reading",
                operation="add",
                amount=Decimal("3"),
                track=None,
            )
            cleared = mutate_project_progress_storage(
                config,
                "reading",
                operation="clear",
                track=None,
            )

            self.assertFalse(created.opened)
            self.assertEqual(added.progress.current, "5")
            self.assertIsNone(cleared.progress)
            self.assertEqual([item["op"] for item in read_ops(config)], [
                "project_progress_set",
                "project_progress_add",
                "project_progress_clear",
            ])


if __name__ == "__main__":
    unittest.main()
