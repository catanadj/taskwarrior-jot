from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import unittest

from jot_core.progress_output import emit_progress


class ProgressOutputTests(unittest.TestCase):
    def _emit(self, payload: dict[str, object]) -> tuple[str, list[str], list[tuple[str, object]]]:
        output = StringIO()
        titles: list[str] = []
        sections: list[tuple[str, object]] = []
        fields: list[tuple[str, object]] = []
        with redirect_stdout(output):
            emit_progress(
                payload,
                write_title=titles.append,
                emit_field=lambda key, value, **_kwargs: fields.append((key, value)),
                write_section_title=lambda title, **kwargs: sections.append((title, kwargs.get("indent"))),
                style=lambda value, **_kwargs: f"<{value}>",
                progress_bar=lambda value: f"BAR({value})",
            )
        return output.getvalue(), titles, fields + sections

    def test_single_track_show_renders_visual_and_analysis(self) -> None:
        output, titles, entries = self._emit(
            {
                "note_kind": "task",
                "operation": "show",
                "path": "/tmp/task.md",
                "track": "pages",
                "progress": {
                    "track": "pages",
                    "current": "40",
                    "target": "100",
                    "unit": "pages",
                    "percentage": "40",
                    "status": "reading",
                    "updated": "2026-09-18",
                },
                "trends": [{"track": "pages", "updates": 2, "delta": "+20", "unit": "pages"}],
                "history": [{"track": "pages", "timestamp": "2026-09-18", "action": "set", "summary": "40/100"}],
            }
        )

        self.assertEqual(titles, ["Progress for task note"])
        self.assertIn("BAR(40)", output)
        self.assertIn("40/100 pages", output)
        self.assertIn("<pages>", output)
        self.assertIn(("Trends", 2), entries)
        self.assertIn(("Recent history", 2), entries)

    def test_multiple_tracks_and_items_show_not_set_paths(self) -> None:
        output, titles, _entries = self._emit(
            {
                "note_kind": "project",
                "operation": "show",
                "track": "",
                "tracks": [
                    {"track": "books", "current": "2", "target": "5", "unit": "books", "percentage": "40"},
                    {"track": "hours", "current": "3", "target": "10", "unit": "hours", "percentage": "30"},
                ],
            }
        )
        self.assertEqual(titles, ["Progress for project note"])
        self.assertIn("books", output)
        self.assertIn("hours", output)

        output, titles, _entries = self._emit(
            {
                "note_kind": "task",
                "track": "",
                "tracks": [],
            }
        )
        self.assertEqual(titles, ["Progress for task note"])
        self.assertIn("(not set)", output)

        output, titles, _entries = self._emit(
            {
                "note_kind": "task",
                "items": [{"reference": "abc", "task_short_uuid": "abc", "tracks": []}],
            }
        )
        self.assertEqual(titles, ["Progress for 1 task notes"])
        self.assertIn("abc", output)
        self.assertIn("(not set)", output)

    def test_mutation_without_visual_progress_uses_fields_and_entry(self) -> None:
        output, titles, entries = self._emit(
            {
                "note_kind": "project",
                "operation": "set",
                "path": "/tmp/project.md",
                "progress": {
                    "track": "default",
                    "current": "2",
                    "target": "5",
                    "unit": "books",
                    "percentage": "40",
                    "status": "active",
                    "updated": "2026-09-18",
                },
                "entry": "2/5 books",
            }
        )
        self.assertEqual(titles, ["Progress for project note"])
        self.assertIn(("track", "default"), entries)
        self.assertIn(("progress", "2/5 books"), entries)
        self.assertIn(("history", "2/5 books"), entries)
        self.assertNotIn("BAR", output)


if __name__ == "__main__":
    unittest.main()
