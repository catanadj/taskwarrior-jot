from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from jot_core.config import ensure_app_dirs
from jot_core.models import AppConfig
from jot_core.notes import append_to_task_note
from jot_core.taskwarrior import TaskwarriorClient


TASK_BIN = shutil.which("task")


@unittest.skipUnless(TASK_BIN, "Taskwarrior is not installed")
class TaskwarriorIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory(prefix="jot-taskwarrior-integration-")
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.home = root / "home"
        self.data = root / "taskdata"
        self.hooks = root / "hooks"
        self.home.mkdir()
        self.data.mkdir()
        self.hooks.mkdir()
        self.taskrc = root / "taskrc"
        self.taskrc.write_text(
            f"data.location={self.data}\n"
            f"hooks.location={self.hooks}\n"
            "hooks=off\nconfirmation=off\nverbose=nothing\n",
            encoding="utf-8",
        )
        self.environment = {
            **os.environ,
            "HOME": str(self.home),
            "TASKDATA": str(self.data),
            "TASKRC": str(self.taskrc),
        }
        self.environment_patch = mock.patch.dict(
            os.environ,
            {
                "HOME": str(self.home),
                "TASKDATA": str(self.data),
                "TASKRC": str(self.taskrc),
            },
        )
        self.environment_patch.start()
        self.addCleanup(self.environment_patch.stop)
        self.client = TaskwarriorClient(task_bin=str(TASK_BIN), taskdata=str(self.data))

    def _run_task(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [str(TASK_BIN), f"rc.data.location={self.data}", "rc.hooks=off", *arguments],
            env=self.environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def _jot_config(self) -> AppConfig:
        root = self.data / "jot"
        config = AppConfig(
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
        ensure_app_dirs(config)
        return config

    def test_real_taskwarrior_lifecycle_and_jot_note(self) -> None:
        self._run_task("add", "project:integration", "+jot", "Integration task")

        pending = self.client.list_tasks(limit=10)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["project"], "integration")
        self.assertIn("jot", pending[0]["tags"])
        task_id = str(pending[0]["uuid"])
        task_short_uuid = str(pending[0]["short_uuid"])

        by_uuid = self.client.resolve_task(task_id)
        by_short_uuid = self.client.resolve_task(task_short_uuid)
        self.assertEqual(by_uuid.task_uuid, task_id)
        self.assertEqual(by_short_uuid.task_uuid, task_id)

        self.client.add_annotation(task_id, "real integration annotation")
        self._run_task(task_id, "modify", "description:Updated integration task")
        updated = self.client.resolve_task(task_id)
        self.assertEqual(updated.description, "Updated integration task")
        self.assertEqual(self.client.annotations_for_task(updated)[0]["description"], "real integration annotation")

        note = append_to_task_note(self._jot_config(), updated, "Written through the Jot storage layer")
        self.assertTrue(note.note_path.exists())
        self.assertIn("Written through the Jot storage layer", note.note_path.read_text(encoding="utf-8"))

        self._run_task(task_id, "start")
        started = json.loads(self._run_task("rc.json.array=1", task_id, "export").stdout)[0]
        self.assertTrue(started.get("start"))
        self._run_task(task_id, "stop")
        stopped = json.loads(self._run_task("rc.json.array=1", task_id, "export").stdout)[0]
        self.assertFalse(stopped.get("start"))

        self.client.complete_task(task_id)
        completed = self.client.list_tasks(limit=10, status="completed")
        self.assertEqual([item["uuid"] for item in completed], [task_id])


if __name__ == "__main__":
    unittest.main()
