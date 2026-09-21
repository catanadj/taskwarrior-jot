import unittest

from jot_core.cli import build_parser
from jot_core.completion import render_completion


class CompletionTests(unittest.TestCase):
    def test_renders_supported_shell_scripts_with_cli_commands(self) -> None:
        parser = build_parser()

        bash = render_completion("bash", parser)
        zsh = render_completion("zsh", parser)
        fish = render_completion("fish", parser)

        self.assertIn("complete -F _jot_completions jot", bash)
        self.assertIn("compdef _jot jot", zsh)
        self.assertIn("complete -c jot", fish)
        for script in (bash, zsh, fish):
            self.assertIn("doctor", script)
            self.assertIn("progress", script)
            self.assertIn("timelog", script)

    def test_rejects_unknown_shell(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported shell"):
            render_completion("powershell", build_parser())


if __name__ == "__main__":
    unittest.main()
