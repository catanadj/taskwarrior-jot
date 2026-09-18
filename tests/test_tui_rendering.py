from __future__ import annotations

import unittest

from jot_tui.rendering import (
    note_excerpt,
    pretty_label,
    progress_bar,
    render_events_panel,
    render_note_panel,
    render_workspace_progress,
    render_workspace_resources,
    workspace_has_progress,
    workspace_has_resources,
)


class TuiRenderingTests(unittest.TestCase):
    def test_note_panel_handles_empty_and_populated_notes(self) -> None:
        guidance = lambda title, path: f"EMPTY {title} {path}"
        self.assertEqual(render_note_panel("Task", {}, empty_guidance=guidance), "EMPTY Task ")
        panel = render_note_panel(
            "Task",
            {"path": "/tmp/task.md", "body": "# Heading\n\nA useful note"},
            empty_guidance=guidance,
        )
        self.assertIn("Path: /tmp/task.md", panel)
        self.assertIn("A useful note", panel)
        self.assertIn("e edit", panel)

    def test_events_and_excerpt_limit_and_normalize_content(self) -> None:
        self.assertEqual(render_events_panel([]), "Events\n\n(none)")
        events = render_events_panel(
            [{"entry": "2026-09-18", "description": "Started"}, {"description": "Updated"}]
        )
        self.assertIn("2026-09-18  Started", events)
        self.assertIn("Updated", events)
        self.assertEqual(note_excerpt("\n  short  \n\n"), "short")
        self.assertEqual(note_excerpt("x" * 10, max_width=6), "xxx...")
        self.assertEqual(note_excerpt("\n\n"), "")
        self.assertEqual(pretty_label("task_short_uuid"), "Task short uuid")

    def test_resources_panel_covers_empty_and_status_variants(self) -> None:
        empty = render_workspace_resources([("task", {})])
        self.assertIn("No resources attached yet.", empty)
        populated = render_workspace_resources(
            [
                ("task", {"path": "/tmp/task.md", "resources": []}),
                (
                    "project",
                    {
                        "resources": [
                            {"id": 1, "label": "Docs", "target": "https://example.test", "kind": "url", "status": "exists"},
                            {"id": 2, "label": "", "target": "/missing", "kind": "file", "status": "missing"},
                        ]
                    },
                ),
            ]
        )
        self.assertIn("Task note", populated)
        self.assertIn("Project note", populated)
        self.assertIn("https://example.test", populated)
        self.assertIn("[file] missing", populated)
        self.assertTrue(workspace_has_resources([{"resources": [{"target": "x"}]}]))
        self.assertFalse(workspace_has_resources([{}]))

    def test_progress_panel_supports_legacy_and_multiple_tracks(self) -> None:
        empty = render_workspace_progress([("task", {})])
        self.assertIn("No progress tracks yet.", empty)
        rendered = render_workspace_progress(
            [
                ("task", {"progress": {"current": "2", "target": "4", "percentage": "50", "unit": "pages"}}),
                (
                    "chain",
                    {
                        "progress_tracks": [
                            {"track": "sets", "current": "3", "target": "5", "status": "active", "updated": "today"},
                            "invalid",
                        ]
                    },
                ),
            ]
        )
        self.assertIn("2/4 pages", rendered)
        self.assertIn("[sets] 3/5", rendered)
        self.assertIn("Status: active", rendered)
        self.assertIn("Action: g", rendered)
        self.assertTrue(workspace_has_progress([{"progress": {"current": "1"}}]))
        self.assertTrue(workspace_has_progress([{"progress_tracks": [{"track": "x"}]}]))
        self.assertFalse(workspace_has_progress([{}]))

    def test_progress_bar_clamps_invalid_and_out_of_range_values(self) -> None:
        self.assertEqual(progress_bar("bad", width=4), "[----]")
        self.assertEqual(progress_bar("-1", width=4), "[----]")
        self.assertEqual(progress_bar("150", width=4), "[####]")


if __name__ == "__main__":
    unittest.main()
