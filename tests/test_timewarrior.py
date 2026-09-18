from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import subprocess
import unittest
from unittest import mock

from jot_core.frontmatter import read_document, write_document
from jot_core.models import AppConfig, ResolvedTask, TaskRef
from jot_core.timewarrior import (
    clear_timewarrior_tags,
    inherit_timewarrior_tags,
    resolve_timewarrior_tags,
    set_timewarrior_tags,
    start_timewarrior_for_task,
)


class TimewarriorTests(unittest.TestCase):
    def _config(self, root: Path, *, enabled: bool = True) -> AppConfig:
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
            timewarrior_enabled=enabled,
        )

    def _task(self) -> ResolvedTask:
        task_uuid = "2d6d7d7d-1111-2222-3333-444444444444"
        return ResolvedTask(
            ref=TaskRef(raw="2d6d7d7d"),
            task_uuid=task_uuid,
            task_short_uuid="2d6d7d7d",
            description="Read book",
            project="work.reading",
            tags=[],
            task={"uuid": task_uuid, "chainID": "chain-1"},
        )

    def test_resolution_prefers_task_then_chain_then_project(self) -> None:
        with TemporaryDirectory(prefix="jot-timew-") as temporary:
            root = Path(temporary)
            config = self._config(root)
            config.tasks_dir.mkdir(parents=True)
            config.chains_dir.mkdir()
            config.projects_dir.mkdir()
            task = self._task()
            write_document(
                config.tasks_dir / "2d6d7d7d--read.md",
                {"task_short_uuid": "2d6d7d7d", "timew_tags": ["task"]},
                "",
            )
            write_document(
                config.chains_dir / "chain-1--cycle.md",
                {"chain_id": "chain-1", "timew_tags": ["chain"]},
                "",
            )
            project_dir = config.projects_dir / "work" / "reading"
            project_dir.mkdir(parents=True)
            write_document(
                project_dir / "index.md",
                {"project": "work.reading", "timew_tags": ["project"]},
                "",
            )

            resolved = resolve_timewarrior_tags(config, task)
            self.assertEqual(resolved["tags"], ["task"])
            (config.tasks_dir / "2d6d7d7d--read.md").unlink()
            resolved = resolve_timewarrior_tags(config, task)
            self.assertEqual(resolved["tags"], ["chain"])
            (config.chains_dir / "chain-1--cycle.md").unlink()
            resolved = resolve_timewarrior_tags(config, task)
            self.assertEqual(resolved["tags"], ["project"])

    def test_start_handles_disabled_empty_success_failure_and_timeout(self) -> None:
        task = self._task()
        with TemporaryDirectory(prefix="jot-timew-") as temporary:
            root = Path(temporary)
            disabled = self._config(root, enabled=False)
            self.assertEqual(start_timewarrior_for_task(disabled, task)["reason"], "integration-disabled")

            config = self._config(root)
            with mock.patch("jot_core.timewarrior.resolve_timewarrior_tags", return_value={"tags": [], "explicitly_disabled": False, "source": None, "enabled": True}):
                self.assertEqual(start_timewarrior_for_task(config, task)["reason"], "no-tags")
            with mock.patch("jot_core.timewarrior.resolve_timewarrior_tags", return_value={"tags": ["focus"], "explicitly_disabled": False, "source": None, "enabled": True}):
                with mock.patch("jot_core.timewarrior.subprocess.run", return_value=subprocess.CompletedProcess([], 0, stdout="ok\n", stderr="")):
                    started = start_timewarrior_for_task(config, task)
                self.assertTrue(started["started"])
                self.assertEqual(started["command"], ["timew", "start", "focus"])
                with mock.patch("jot_core.timewarrior.subprocess.run", side_effect=subprocess.TimeoutExpired([], 10)):
                    timed_out = start_timewarrior_for_task(config, task)
                self.assertIn("timed out", timed_out["error"])

    def test_metadata_set_clear_and_inherit_update_note(self) -> None:
        with TemporaryDirectory(prefix="jot-timew-") as temporary:
            root = Path(temporary)
            config = self._config(root)
            config.projects_dir.mkdir(parents=True)

            set_result = set_timewarrior_tags(config, scope="project", reference="work", tags=["focus", "focus"])
            self.assertTrue(set_result["changed"])
            note_path = Path(set_result["path"])
            metadata, _body = read_document(note_path)
            self.assertEqual(metadata["timew_tags"], ["focus"])

            unchanged = set_timewarrior_tags(config, scope="project", reference="work", tags=["focus"])
            self.assertFalse(unchanged["changed"])
            cleared = clear_timewarrior_tags(config, scope="project", reference="work")
            self.assertTrue(cleared["changed"])
            inherited = inherit_timewarrior_tags(config, scope="project", reference="work")
            self.assertTrue(inherited["changed"])
            self.assertFalse(inherit_timewarrior_tags(config, scope="project", reference="work")["changed"])
            metadata, _body = read_document(note_path)
            self.assertNotIn("timew_tags", metadata)


if __name__ == "__main__":
    unittest.main()
