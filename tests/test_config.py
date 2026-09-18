from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import os
import unittest
from unittest import mock

from jot_core.config import load_config


class ConfigTests(unittest.TestCase):
    def test_load_config_applies_paths_and_typed_options(self) -> None:
        with TemporaryDirectory(prefix="jot-config-") as temporary:
            root = Path(temporary)
            config_path = root / "config-jot.toml"
            config_path.write_text(
                f"""
[paths]
root = "{root / 'notes'}"
tasks = "{root / 'task-notes'}"
projects = "{root / 'project-notes'}"

[editor]
command = "nano -w"
show_diff_on_save = false
diff_color = "never"
post_save_actions = false

[display]
color = "always"
default_format = "json"

[nautical]
enabled = false

[timewarrior]
enabled = false

[ops]
max_entries = 20
keep_entries = 10
""",
                encoding="utf-8",
            )
            with (
                mock.patch.dict(
                    os.environ,
                    {"JOT_CONFIG": str(config_path), "EDITOR": "vim"},
                    clear=False,
                ),
                mock.patch("jot_core.config._taskdata_root", return_value=root / "taskdata"),
            ):
                config = load_config()

            self.assertEqual(config.config_path, config_path.resolve())
            self.assertEqual(config.root_dir, (root / "notes").resolve())
            self.assertEqual(config.tasks_dir, (root / "task-notes").resolve())
            self.assertEqual(config.projects_dir, (root / "project-notes").resolve())
            self.assertEqual(config.editor_command, "nano -w")
            self.assertFalse(config.editor_show_diff_on_save)
            self.assertEqual(config.editor_diff_color, "never")
            self.assertFalse(config.editor_post_save_actions)
            self.assertEqual(config.color_mode, "always")
            self.assertEqual(config.default_format, "json")
            self.assertFalse(config.nautical_enabled)
            self.assertFalse(config.timewarrior_enabled)
            self.assertEqual(config.ops_max_entries, 20)
            self.assertEqual(config.ops_keep_entries, 10)

    def test_load_config_rejects_unknown_keys_and_invalid_invariants(self) -> None:
        with TemporaryDirectory(prefix="jot-config-") as temporary:
            root = Path(temporary)
            config_path = root / "config-jot.toml"
            with mock.patch.dict(os.environ, {"JOT_CONFIG": str(config_path)}, clear=False):
                config_path.write_text("[display]\ncolour = 'always'\n", encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "unknown config key"):
                    load_config()

                config_path.write_text(
                    "[ops]\nmax_entries = 2\nkeep_entries = 3\n",
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(RuntimeError, "keep_entries"):
                    load_config()

    def test_load_config_rejects_invalid_choice_and_boolean(self) -> None:
        with TemporaryDirectory(prefix="jot-config-") as temporary:
            config_path = Path(temporary) / "config-jot.toml"
            with mock.patch.dict(os.environ, {"JOT_CONFIG": str(config_path)}, clear=False):
                config_path.write_text("[display]\ncolor = 'sometimes'\n", encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "display.color"):
                    load_config()

                config_path.write_text(
                    "[timewarrior]\nenabled = 'sometimes'\n",
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(RuntimeError, "timewarrior.enabled"):
                    load_config()


if __name__ == "__main__":
    unittest.main()
