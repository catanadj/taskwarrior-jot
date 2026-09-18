from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest import mock

from jot_core import timelog_hook


ROOT = Path(__file__).parents[1]


class TimelogHookLayoutTests(unittest.TestCase):
    def test_jot_hooks_delegate_to_one_canonical_implementation(self) -> None:
        canonical = ROOT / "jot_core" / "timelog_hook.py"
        hook_paths = (ROOT / "jot_core" / "data" / "hooks" / "on-modify_jot_timelog.py",)

        self.assertTrue(canonical.is_file())
        self.assertFalse((ROOT / "hooks" / "on-modify_jot_timelog.py").exists())
        for hook_path in hook_paths:
            source = hook_path.read_text(encoding="utf-8")
            self.assertIn("from jot_core.timelog_hook import main", source)
            self.assertNotIn("subprocess.run(", source)

    def _run_hook(
        self,
        input_text: str,
        *,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        completed: subprocess.CompletedProcess[str] | None = None,
    ) -> tuple[int, str, mock.Mock]:
        process = mock.Mock(
            returncode=0,
            stdout="",
            stderr="",
        ) if completed is None else completed
        with (
            mock.patch("sys.stdin", io.StringIO(input_text)),
            mock.patch("sys.stdout", io.StringIO()) as stdout,
            mock.patch("sys.argv", ["on-modify_jot_timelog.py", *(args or [])]),
            mock.patch.dict(os.environ, env or {}, clear=False),
            mock.patch("jot_core.timelog_hook.subprocess.run", return_value=process) as run,
        ):
            result = timelog_hook.main()
            return result, stdout.getvalue(), run

    def test_invalid_input_is_passed_through_without_ingest(self) -> None:
        result, output, run = self._run_hook("not-json\n{}\n")

        self.assertEqual(result, 0)
        self.assertEqual(output, "{}\n")
        run.assert_not_called()

    def test_successful_ingest_preserves_taskwarrior_output_and_taskdata(self) -> None:
        old = {"uuid": "abc", "status": "pending"}
        new = {"uuid": "abc", "status": "completed"}

        result, output, run = self._run_hook(
            json.dumps(old) + "\n" + json.dumps(new) + "\n",
            args=["data:/tmp/taskdata"],
            env={"JOT_BIN": "/tmp/jot"},
        )

        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output), new)
        run.assert_called_once()
        command = run.call_args.args[0]
        self.assertEqual(command, ["/tmp/jot", "--json", "timelog", "ingest"])
        self.assertEqual(run.call_args.kwargs["env"]["TASKDATA"], "/tmp/taskdata")

    def test_ingest_failure_is_fail_open_unless_strict(self) -> None:
        old = {"uuid": "abc", "status": "pending"}
        new = {"uuid": "abc", "status": "completed"}
        completed = subprocess.CompletedProcess(
            ["jot"],
            3,
            stdout="",
            stderr="ingest failed",
        )

        result, output, _run = self._run_hook(
            json.dumps(old) + "\n" + json.dumps(new) + "\n",
            completed=completed,
        )
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output), new)

        result, output, _run = self._run_hook(
            json.dumps(old) + "\n" + json.dumps(new) + "\n",
            env={"JOT_TIMELOG_STRICT": "1"},
            completed=completed,
        )
        self.assertEqual(result, 3)
        self.assertEqual(json.loads(output), new)


if __name__ == "__main__":
    unittest.main()
