from __future__ import annotations

import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from jot_core.taskwarrior import TaskwarriorClient


UUID = "2d6d7d7d-1111-2222-3333-444444444444"
TASK = {
    "uuid": UUID,
    "description": "Read book",
    "project": "study",
    "chainID": "chain-1",
    "tags": ["focus"],
    "status": "pending",
}


class TaskwarriorClientTests(unittest.TestCase):
    def test_export_contract_works_with_a_real_taskwarrior_executable(self) -> None:
        with TemporaryDirectory(prefix="jot-taskwarrior-") as temporary:
            root = Path(temporary)
            script = root / "task"
            calls = root / "calls.json"
            script.write_text(
                "#!/usr/bin/env python3\n"
                "import json\n"
                "import pathlib\n"
                "import sys\n"
                f"pathlib.Path({str(calls)!r}).write_text(json.dumps(sys.argv[1:]))\n"
                f"payload = {[TASK]!r}\n"
                "print(json.dumps(payload))\n",
                encoding="utf-8",
            )
            script.chmod(0o755)

            resolved = TaskwarriorClient(task_bin=str(script)).resolve_task("42")

            self.assertEqual(resolved.task_short_uuid, "2d6d7d7d")
            self.assertEqual(
                json.loads(calls.read_text(encoding="utf-8")),
                [
                    "rc.hooks=off",
                    "rc.verbose=nothing",
                    "rc.color=off",
                    "rc.json.array=1",
                    "42",
                    "export",
                ],
            )

    def test_availability_and_version_use_configured_binary(self) -> None:
        client = TaskwarriorClient(task_bin="task-custom")
        with mock.patch("jot_core.taskwarrior.shutil.which", return_value="/bin/task"):
            self.assertTrue(client.is_available())
        with mock.patch(
            "jot_core.taskwarrior.TaskwarriorClient._run",
            return_value=subprocess.CompletedProcess([], 0, "2.6.2\n", ""),
        ) as run:
            self.assertEqual(client.version(), "2.6.2")
        run.assert_called_once_with(["--version"])

    def test_version_and_mutations_surface_taskwarrior_errors(self) -> None:
        client = TaskwarriorClient()
        failed = subprocess.CompletedProcess([], 1, "", "bad command\n")
        with mock.patch("jot_core.taskwarrior.TaskwarriorClient._run", return_value=failed):
            with self.assertRaisesRegex(RuntimeError, "bad command"):
                client.version()
            with self.assertRaisesRegex(RuntimeError, "bad command"):
                client.add_annotation(UUID, "note")
            with self.assertRaisesRegex(RuntimeError, "bad command"):
                client.complete_task(UUID)

    def test_resolve_task_validates_refs_and_handles_missing_or_ambiguous_tasks(self) -> None:
        client = TaskwarriorClient()
        with self.assertRaisesRegex(RuntimeError, "reference is empty"):
            client.resolve_task(" ")
        with self.assertRaisesRegex(RuntimeError, "unsupported task reference"):
            client.resolve_task("read book")

        with mock.patch("jot_core.taskwarrior.TaskwarriorClient._export_for_ref", return_value=[]):
            with self.assertRaisesRegex(RuntimeError, "no task found"):
                client.resolve_task("42")
        with mock.patch("jot_core.taskwarrior.TaskwarriorClient._export_for_ref", return_value=[TASK, {**TASK, "uuid": UUID.replace("2d6d7d7d", "aaaaaaaa")}]):
            with self.assertRaisesRegex(RuntimeError, "ambiguous.*2d6d7d7d.*aaaaaaaa"):
                client.resolve_task("42")

        with mock.patch("jot_core.taskwarrior.TaskwarriorClient._export_for_ref", return_value=[TASK]):
            resolved = client.resolve_task("42")
        self.assertEqual(resolved.task_short_uuid, "2d6d7d7d")
        self.assertEqual(resolved.task["chainID"], "chain-1")
        self.assertEqual(resolved.tags, ["focus"])

    def test_resolve_first_list_and_annotations_normalize_data(self) -> None:
        client = TaskwarriorClient()
        with mock.patch("jot_core.taskwarrior.TaskwarriorClient._run_export", return_value=[TASK]):
            resolved = client.resolve_first_for_filter("status:pending")
            self.assertEqual(resolved.description, "Read book")
        with self.assertRaisesRegex(RuntimeError, "filter is empty"):
            client.resolve_first_for_filter(" ")
        with mock.patch("jot_core.taskwarrior.TaskwarriorClient._run_export", return_value=[]):
            with self.assertRaisesRegex(RuntimeError, "no task found"):
                client.resolve_first_for_filter("status:pending")

        resolved.task["annotations"] = [
            {"entry": "2026-09-18", "description": "  Started  "},
            "invalid",
            {"description": "No date"},
        ]
        self.assertEqual(
            client.annotations_for_task(resolved),
            [{"entry": "2026-09-18", "description": "Started"}, {"entry": None, "description": "No date"}],
        )
        resolved.task["annotations"] = "invalid"
        self.assertEqual(client.annotations_for_task(resolved), [])

        with mock.patch("jot_core.taskwarrior.TaskwarriorClient._run_export", return_value=[TASK, {"description": "missing uuid"}]):
            listed = client.list_tasks(limit=2, status="pending")
        self.assertEqual(listed, [{"uuid": UUID, "short_uuid": "2d6d7d7d", "description": "Read book", "project": "study", "tags": ["focus"], "chain_id": "chain-1", "status": "pending", "due": None}])
        with self.assertRaisesRegex(RuntimeError, "limit"):
            client.list_tasks(limit=0)

    def test_export_parsing_and_subprocess_failures_are_actionable(self) -> None:
        client = TaskwarriorClient()
        with mock.patch("jot_core.taskwarrior.TaskwarriorClient._run", return_value=subprocess.CompletedProcess([], 0, "", "")):
            self.assertEqual(client._run_export(["42"]), [])
        with mock.patch("jot_core.taskwarrior.TaskwarriorClient._run", return_value=subprocess.CompletedProcess([], 0, json.dumps(TASK), "")):
            with self.assertRaisesRegex(RuntimeError, "non-array"):
                client._run_export(["42"])
        with mock.patch("jot_core.taskwarrior.TaskwarriorClient._run", return_value=subprocess.CompletedProcess([], 1, "", "failed")):
            with self.assertRaisesRegex(RuntimeError, "failed"):
                client._run_export(["42"])
        with mock.patch("jot_core.taskwarrior.subprocess.run", side_effect=FileNotFoundError()):
            with self.assertRaisesRegex(RuntimeError, "executable not found"):
                client.version()
        with mock.patch("jot_core.taskwarrior.subprocess.run", side_effect=OSError("broken")):
            with self.assertRaisesRegex(RuntimeError, "could not run"):
                client.version()

    def test_command_prefix_uses_taskdata_or_environment(self) -> None:
        client = TaskwarriorClient(taskdata="/tmp/tasks")
        with mock.patch("jot_core.taskwarrior.TaskwarriorClient.environment") as environment:
            environment.return_value.data_path = "/effective/tasks"
            environment.return_value.rc_path = Path("/missing/taskrc")
            self.assertEqual(client._command_prefix(), ["rc.data.location=/effective/tasks"])
        with mock.patch.dict("os.environ", {"TASKDATA": "/env/tasks"}):
            with mock.patch("jot_core.taskwarrior.TaskwarriorClient.environment") as environment:
                environment.return_value.data_path = "/env/tasks"
                environment.return_value.rc_path = Path("/missing/taskrc")
                self.assertEqual(client._command_prefix(), ["rc.data.location=/env/tasks"])

    def test_command_prefix_uses_existing_taskrc(self) -> None:
        client = TaskwarriorClient(taskdata="/tmp/tasks")
        with TemporaryDirectory() as directory:
            taskrc = Path(directory) / "taskrc"
            taskrc.touch()
            with mock.patch("jot_core.taskwarrior.TaskwarriorClient.environment") as environment:
                environment.return_value.data_path = "/effective/tasks"
                environment.return_value.rc_path = taskrc
                self.assertEqual(
                    client._command_prefix(),
                    [f"rc:{taskrc}", "rc.data.location=/effective/tasks"],
                )


if __name__ == "__main__":
    unittest.main()
