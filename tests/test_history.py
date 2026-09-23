from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import os
import unittest
from unittest import mock

from jot_core.frontmatter import parse_document, render_document, write_document
from jot_core.editor import open_in_editor
from jot_core.history import (
    list_note_revisions,
    note_content_digest,
    note_revision_diff,
    restore_note_revision,
)


class NoteHistoryTests(unittest.TestCase):
    def test_changed_note_keeps_previous_revision_and_skips_no_op(self) -> None:
        with TemporaryDirectory(prefix="jot-history-") as tempdir:
            path = Path(tempdir) / "tasks" / "abc12345--read.md"
            write_document(path, {"kind": "task-note", "updated": "one"}, "first")
            write_document(path, {"kind": "task-note", "updated": "two"}, "second")

            revisions = list_note_revisions(path)
            self.assertEqual(len(revisions), 1)
            self.assertEqual(revisions[0].content, "---\nkind: task-note\nupdated: one\n---\n\nfirst\n")

            write_document(path, {"kind": "task-note", "updated": "three"}, "second")
            self.assertEqual(len(list_note_revisions(path)), 1)

    def test_non_jot_markdown_is_not_added_to_note_history(self) -> None:
        with TemporaryDirectory(prefix="jot-history-") as tempdir:
            path = Path(tempdir) / "ordinary.md"
            write_document(path, {"kind": "meeting"}, "first")
            write_document(path, {"kind": "meeting"}, "second")
            self.assertEqual(list_note_revisions(path), ())

    def test_diff_and_restore_keep_the_pre_restore_content_recoverable(self) -> None:
        with TemporaryDirectory(prefix="jot-history-") as tempdir:
            path = Path(tempdir) / "task.md"
            write_document(path, {"kind": "task-note"}, "before")
            write_document(path, {"kind": "task-note", "updated": "later"}, "current")
            original = list_note_revisions(path)[0]

            diff = note_revision_diff(path, original.revision_id)
            self.assertIn("-before", diff)
            self.assertIn("+current", diff)

            restore_note_revision(path, original.revision_id)
            self.assertIn("before", path.read_text(encoding="utf-8"))
            revisions = list_note_revisions(path)
            self.assertGreaterEqual(len(revisions), 2)
            self.assertTrue(any("current" in item.content for item in revisions))

    def test_restore_rejects_changes_after_diff_preview(self) -> None:
        with TemporaryDirectory(prefix="jot-history-") as tempdir:
            path = Path(tempdir) / "task.md"
            write_document(path, {"kind": "task-note"}, "before")
            write_document(path, {"kind": "task-note"}, "current")
            revision = list_note_revisions(path)[0]
            expected = note_content_digest(path)
            write_document(path, {"kind": "task-note"}, "concurrent edit")
            with self.assertRaisesRegex(RuntimeError, "changed after the revision diff"):
                restore_note_revision(path, revision.revision_id, expected_current_digest=expected)
            self.assertIn("concurrent edit", path.read_text(encoding="utf-8"))

    def test_history_retention_keeps_only_the_configured_newest_revisions(self) -> None:
        with TemporaryDirectory(prefix="jot-history-") as tempdir:
            path = Path(tempdir) / "task.md"
            write_document(path, {"kind": "task-note"}, "version-0")
            with mock.patch("jot_core.history.HISTORY_LIMIT", 2):
                for index in range(1, 5):
                    write_document(path, {"kind": "task-note"}, f"version-{index}")
            self.assertEqual(len(list_note_revisions(path)), 2)

    def test_failed_note_replacement_does_not_leave_a_revision(self) -> None:
        with TemporaryDirectory(prefix="jot-history-") as tempdir:
            path = Path(tempdir) / "task.md"
            write_document(path, {"kind": "task-note"}, "before")
            original_replace = os.replace

            def fail_target_replace(source: str | Path, destination: str | Path) -> None:
                if Path(destination) == path:
                    raise OSError("simulated replace failure")
                original_replace(source, destination)

            with mock.patch("jot_core.frontmatter.os.replace", side_effect=fail_target_replace):
                with self.assertRaisesRegex(OSError, "simulated replace failure"):
                    write_document(path, {"kind": "task-note"}, "after")
            self.assertIn("before", path.read_text(encoding="utf-8"))
            self.assertEqual(list_note_revisions(path), ())

    def test_editor_save_with_expansion_creates_only_one_revision(self) -> None:
        with TemporaryDirectory(prefix="jot-history-") as tempdir:
            path = Path(tempdir) / "task.md"
            write_document(path, {"kind": "task-note", "task_short_uuid": "abc12345"}, "original")

            def fake_editor(command: list[str], check: bool = False):
                temporary = Path(command[-1])
                metadata, _body = parse_document(temporary.read_text(encoding="utf-8"))
                temporary.write_text(
                    render_document(metadata, "edited {task_short_uuid}"),
                    encoding="utf-8",
                )
                return type("ProcessResult", (), {"returncode": 0})()

            with mock.patch("jot_core.editor.subprocess.run", side_effect=fake_editor):
                open_in_editor(
                    path,
                    "test-editor",
                    show_diff=False,
                    expand_on_save=True,
                    confirm_expansion=False,
                )
            self.assertEqual(len(list_note_revisions(path)), 1)
            self.assertIn("edited abc12345", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
