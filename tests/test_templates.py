from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from jot_core.editor import expand_note_content
from jot_core.frontmatter import parse_document, render_document
from jot_core.templates import expand_text


class TextExpansionTests(unittest.TestCase):
    def test_expands_known_tokens_and_preserves_unknown_tokens(self) -> None:
        result = expand_text(
            "On {date} at {{time}}: {task_short_uuid} {missing}",
            {"date": "2026-09-23", "time": "10:15 EEST", "task_short_uuid": "abc12345"},
        )

        self.assertEqual(
            result.text,
            "On 2026-09-23 at 10:15 EEST: abc12345 {missing}",
        )
        self.assertEqual(result.unknown_tokens, ("missing",))

    def test_backslash_escapes_a_placeholder(self) -> None:
        result = expand_text(r"Keep \{date} and \{{time}}", {"date": "today", "time": "now"})

        self.assertEqual(result.text, "Keep {date} and {{time}}")
        self.assertEqual(result.unknown_tokens, ())

    def test_editor_expansion_requires_confirmation_and_decline_preserves_note(self) -> None:
        with TemporaryDirectory(prefix="jot-expand-") as tempdir:
            path = Path(tempdir) / "note.md"
            metadata = {"task_short_uuid": "abc12345", "description": "Read"}
            candidate = render_document(metadata, "{task_short_uuid}: {date} \\{time}")
            stdin = mock.Mock()
            stdin.isatty.return_value = True
            stdin.readline.return_value = "no\n"
            with mock.patch("jot_core.editor.sys.stdin", stdin):
                result = expand_note_content(path, candidate, confirm=True)
            self.assertEqual(result, candidate)

    def test_editor_expansion_applies_after_confirmation(self) -> None:
        with TemporaryDirectory(prefix="jot-expand-") as tempdir:
            path = Path(tempdir) / "note.md"
            candidate = render_document({"task_short_uuid": "abc12345"}, "{task_short_uuid} \\{date}")
            stdin = mock.Mock()
            stdin.isatty.return_value = True
            stdin.readline.return_value = "yes\n"
            with mock.patch("jot_core.editor.sys.stdin", stdin):
                result = expand_note_content(path, candidate, confirm=True)
            _metadata, body = parse_document(result)
            self.assertEqual(body.strip(), "abc12345 {date}")

    def test_editor_expansion_can_skip_confirmation(self) -> None:
        with TemporaryDirectory(prefix="jot-expand-") as tempdir:
            path = Path(tempdir) / "note.md"
            candidate = render_document({"task_short_uuid": "abc12345"}, "{task_short_uuid} {unknown}")
            with mock.patch("jot_core.editor.sys.stdin.isatty", return_value=False):
                saved = expand_note_content(path, candidate, confirm=False)
            self.assertIn("abc12345 {unknown}", saved)


if __name__ == "__main__":
    unittest.main()
