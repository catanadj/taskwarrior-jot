from __future__ import annotations

from decimal import Decimal
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from jot_core.config import ensure_app_dirs, load_config
from jot_core.frontmatter import read_document
from jot_core.index import load_or_rebuild_index, read_index_status
from jot_core.models import AppConfig, ResolvedTask, TaskRef
from jot_core.ops import read_ops
from jot_core.storage import (
    append_chain_note_storage,
    append_project_note_storage,
    append_task_note_storage,
    attach_task_resource_storage,
    delete_chain_note_storage,
    delete_project_note_storage,
    delete_task_note_storage,
    mutate_project_progress_storage,
    mutate_task_progress_storage,
)
from jot_core.trash import list_trash, restore_trash_item


class CoreLifecycleTests(unittest.TestCase):
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
                "chainID": "chain-1",
            },
        )

    def test_task_chain_project_lifecycle_keeps_index_ops_and_trash_consistent(self) -> None:
        with TemporaryDirectory(prefix="jot-lifecycle-") as temporary:
            config = self._config(Path(temporary))
            ensure_app_dirs(config)
            task = self._task()

            task_append = append_task_note_storage(config, task, "Task entry")
            chain_append = append_chain_note_storage(config, task, "Chain entry")
            project_append = append_project_note_storage(config, task.project, "Project entry")
            resource = attach_task_resource_storage(
                config,
                task,
                target="https://example.test/book",
                label="Book",
            )
            progress = mutate_task_progress_storage(
                config,
                task,
                note_kind="task",
                operation="set",
                current=Decimal("2"),
                target=Decimal("10"),
                unit="chapters",
                track="reading",
            )
            project_progress = mutate_project_progress_storage(
                config,
                task.project,
                operation="set",
                current=Decimal("1"),
                target=Decimal("3"),
                unit="books",
            )

            self.assertTrue(task_append.note_path.exists())
            self.assertTrue(chain_append.note_path.exists())
            self.assertTrue(project_append.note_path.exists())
            self.assertTrue(resource.note_path.exists())
            self.assertEqual(progress.progress.current, "2")
            self.assertEqual(project_progress.progress.current, "1")

            index = load_or_rebuild_index(config)
            self.assertEqual(index["tasks"][task.task_uuid]["task_short_uuid"], task.task_short_uuid)
            self.assertIn("chain-1", index["chains"])
            self.assertIn(task.project, index["projects"])
            self.assertTrue(read_index_status(config)["valid"])

            task_deleted = delete_task_note_storage(config, task)
            chain_deleted = delete_chain_note_storage(config, task)
            project_deleted = delete_project_note_storage(config, task.project)
            self.assertFalse(task_deleted.note_path.exists())
            self.assertFalse(chain_deleted.note_path.exists())
            self.assertFalse(project_deleted.note_path.exists())
            self.assertEqual({item["kind"] for item in list_trash(config)}, {
                "task-note", "chain-note", "project-note"
            })
            index_after_delete = load_or_rebuild_index(config)
            self.assertNotIn(task.task_uuid, index_after_delete["tasks"])
            self.assertNotIn("chain-1", index_after_delete["chains"])
            self.assertNotIn(task.project, index_after_delete["projects"])

            restored = restore_trash_item(config, next(
                item.id for item in list_trash(config) if item.kind == "task-note"
            ))
            self.assertTrue(Path(restored.path).exists())
            self.assertEqual(len(list_trash(config)), 2)
            rebuilt = load_or_rebuild_index(config)
            self.assertIn(task.task_uuid, rebuilt["tasks"])

            operations = read_ops(config)
            self.assertEqual(
                [item["op"] for item in operations],
                [
                    "task_note_append",
                    "chain_note_append",
                    "project_note_append",
                    "task_resource_attach",
                    "task_progress_set",
                    "project_progress_set",
                    "task_note_delete",
                    "chain_note_delete",
                    "project_note_delete",
                    "trash_restore",
                ],
            )
            metadata, body = read_document(task_deleted.note_path)
            self.assertEqual(metadata["task_uuid"], task.task_uuid)
            self.assertIn("Task entry", body)

    def test_config_resolves_jot_under_non_default_taskdata(self) -> None:
        with TemporaryDirectory(prefix="jot-taskdata-") as temporary:
            root = Path(temporary)
            taskdata = root / "taskdata"
            taskdata.mkdir()
            taskrc = root / "taskrc"
            taskrc.write_text("", encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "HOME": str(root / "home"),
                    "TASKDATA": str(taskdata),
                    "TASKRC": str(taskrc),
                    "JOT_CONFIG": "",
                },
                clear=False,
            ):
                config = load_config()

            self.assertEqual(config.root_dir, (taskdata / "jot").resolve())
            self.assertEqual(config.tasks_dir, (taskdata / "jot" / "tasks").resolve())
            self.assertFalse((root / "home" / ".task" / "jot").exists())


if __name__ == "__main__":
    unittest.main()
