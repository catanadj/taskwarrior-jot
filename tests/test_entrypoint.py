from __future__ import annotations

from pathlib import Path
import unittest
from unittest import mock


ROOT = Path(__file__).parents[1]


class EntrypointBoundaryTests(unittest.TestCase):
    def test_core_cli_has_no_presentation_layer_imports(self) -> None:
        source = (ROOT / "jot_core" / "cli.py").read_text(encoding="utf-8")

        self.assertNotIn("jot_tui", source)

    def test_launcher_delegates_command_arguments_to_core(self) -> None:
        from jot_tui.launcher import main

        with mock.patch("jot_core.cli.main", return_value=7) as core_main:
            result = main(["show", "42"])

        self.assertEqual(result, 7)
        core_main.assert_called_once_with(["show", "42"])


if __name__ == "__main__":
    unittest.main()
