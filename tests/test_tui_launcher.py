from __future__ import annotations

import unittest
from unittest import mock

from jot_tui import launcher


class TuiLauncherTests(unittest.TestCase):
    def test_main_routes_empty_tui_and_regular_commands(self) -> None:
        with mock.patch.object(launcher.sys.stdin, "isatty", return_value=True), mock.patch.object(
            launcher.sys.stdout, "isatty", return_value=True
        ), mock.patch("jot_tui.launcher._run_command_browser", return_value=3) as browser:
            self.assertEqual(launcher.main([]), 3)
        browser.assert_called_once_with()

        with mock.patch("jot_tui.launcher._run_tui", return_value=0) as tui:
            with mock.patch("jot_tui.launcher.expand_command_prefixes", return_value=["tui"]):
                self.assertEqual(launcher.main(["tui"]), 0)
        tui.assert_called_once_with()

        with mock.patch("jot_tui.launcher.core_cli.main", return_value=2) as cli:
            with mock.patch("jot_tui.launcher.expand_command_prefixes", return_value=["show", "42"]):
                self.assertEqual(launcher.main(["show", "42"]), 2)
        cli.assert_called_once_with(["show", "42"])

    def test_main_uses_help_for_noninteractive_empty_invocation(self) -> None:
        with mock.patch.object(launcher.sys.stdin, "isatty", return_value=False), mock.patch.object(
            launcher.sys.stdout, "isatty", return_value=False
        ), mock.patch("jot_tui.launcher.core_cli.main", return_value=0) as cli:
            self.assertEqual(launcher.main([]), 0)
        cli.assert_called_once_with([])

    def test_main_falls_back_to_cli_for_ambiguous_prefix(self) -> None:
        with mock.patch(
            "jot_tui.launcher.expand_command_prefixes",
            side_effect=launcher.AmbiguousCommandPrefix("p", ("paths", "project-list")),
        ), mock.patch("jot_tui.launcher.core_cli.main", return_value=1) as cli:
            self.assertEqual(launcher.main(["p"]), 1)
        cli.assert_called_once_with(["p"])

    def test_command_browser_falls_back_when_optional_ui_fails(self) -> None:
        with mock.patch("jot_tui.launcher.build_command_catalog", return_value=["commands"]):
            with mock.patch(
                "jot_tui.command_browser.run_command_browser",
                side_effect=RuntimeError("no tty"),
            ), mock.patch("jot_tui.launcher.core_cli.main", return_value=0) as cli:
                self.assertEqual(launcher._run_command_browser(), 0)
        cli.assert_called_once_with([])

    def test_tui_runner_builds_context_and_reports_failures(self) -> None:
        context = mock.Mock()
        context.config.color_mode = "never"
        service = mock.Mock()
        with mock.patch("jot_tui.launcher.build_app_context", return_value=context), mock.patch(
            "jot_tui.launcher.ensure_app_dirs"
        ) as ensure, mock.patch("jot_tui.launcher.configure_output") as configure, mock.patch(
            "jot_tui.launcher.JotService", return_value=service
        ), mock.patch("jot_tui.app.run_tui", return_value=4) as run_tui:
            self.assertEqual(launcher._run_tui(), 4)
        ensure.assert_called_once_with(context.config)
        configure.assert_called_once_with(color_mode="never")
        run_tui.assert_called_once()

        with mock.patch("jot_tui.launcher.build_app_context", side_effect=RuntimeError("broken")), mock.patch(
            "jot_tui.launcher.warn"
        ) as warn:
            self.assertEqual(launcher._run_tui(), 1)
        warn.assert_called_once()


if __name__ == "__main__":
    unittest.main()
