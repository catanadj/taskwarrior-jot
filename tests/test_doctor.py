from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest import mock

from jot_core.doctor import (
    _directory_check,
    _editor_check,
    _index_check,
    _timewarrior_check,
    _tui_check,
    run_doctor,
)
from jot_core.frontmatter import write_document
from jot_core.index import rebuild_index, save_index
from jot_core.models import AppConfig


class DoctorTests(unittest.TestCase):
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

    def test_run_doctor_aggregates_storage_and_external_checks(self) -> None:
        with TemporaryDirectory(prefix="jot-doctor-") as temporary:
            root = Path(temporary) / "jot"
            config = self._config(root)
            client = SimpleNamespace(
                is_available=lambda: False,
                environment=lambda: SimpleNamespace(
                    executable="task",
                    rc_path=None,
                    data_path=None,
                    hooks_path=None,
                    warnings=[],
                ),
            )

            result = run_doctor(config, client)

            checks = {check["name"]: check for check in result.data.checks}
            self.assertTrue(checks["storage"]["ok"])
            self.assertTrue(checks["root_dir"]["ok"])
            self.assertTrue(checks["editor"]["ok"])
            self.assertTrue(checks["timewarrior"]["ok"])
            self.assertFalse(checks["taskwarrior"]["ok"])
            self.assertTrue(checks["taskwarrior_environment"]["ok"])
            self.assertEqual(result.data.repairs, ())

    def test_directory_check_reports_non_directory_path(self) -> None:
        with TemporaryDirectory(prefix="jot-doctor-") as temporary:
            path = Path(temporary) / "not-a-directory"
            path.write_text("occupied", encoding="utf-8")

            check = _directory_check("root_dir", path)

            self.assertFalse(check.ok)
            self.assertEqual(check.name, "root_dir")

    def test_editor_and_timewarrior_checks_report_missing_tools(self) -> None:
        self.assertFalse(_editor_check("missing-editor-command").ok)
        with mock.patch("jot_core.doctor.shutil.which", return_value=None):
            check = _timewarrior_check(SimpleNamespace(timewarrior_enabled=True))
        self.assertFalse(check.ok)
        self.assertEqual(check.severity, "warning")

    def test_tui_check_reports_dependency_incompatibility_as_warning(self) -> None:
        with mock.patch(
            "jot_core.doctor.tui_dependency_status",
            return_value=SimpleNamespace(
                compatible=False,
                ready=False,
                detail="Textual 6.1.0 / Rich 13.3.1: missing Rich API",
            ),
        ):
            check = _tui_check()

        self.assertFalse(check.ok)
        self.assertEqual(check.severity, "warning")
        self.assertIn("Rich 13.3.1", check.detail)

    def test_index_check_accepts_rebuilt_full_and_short_task_keys(self) -> None:
        with TemporaryDirectory(prefix="jot-doctor-index-alias-") as temporary:
            root = Path(temporary)
            config = self._config(root)
            config.tasks_dir.mkdir(parents=True)
            task_uuid = "2d6d7d7d-1111-2222-3333-444444444444"
            write_document(
                config.tasks_dir / "2d6d7d7d--task.md",
                {
                    "kind": "task-note",
                    "task_uuid": task_uuid,
                    "task_short_uuid": "2d6d7d7d",
                },
                "note",
            )
            save_index(config, rebuild_index(config))

            check = _index_check(config)

            self.assertTrue(check.ok, check.detail)
            self.assertIn("stale=False", check.detail)


if __name__ == "__main__":
    unittest.main()
