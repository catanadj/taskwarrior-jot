from __future__ import annotations

import unittest

from jot_tui.state import TuiState
from jot_tui.controllers.progress import apply_progress
from jot_tui.controllers.resources import attach_resource, detach_resource


class TuiStateTests(unittest.TestCase):
    def test_state_defaults_are_isolated_and_ready_for_each_app(self) -> None:
        first = TuiState()
        second = TuiState()
        first.task_rows.append({"id": "42"})
        first.current_task_ref = "42"

        self.assertEqual(second.task_rows, [])
        self.assertIsNone(second.current_task_ref)
        self.assertEqual(first.time_period, "week")

    def test_progress_controller_translates_dialog_payload(self) -> None:
        class Service:
            def update_progress(self, *args, **kwargs):
                return args, kwargs

        args, kwargs = apply_progress(
            Service(),
            {"kind": "task", "task_ref": "42"},
            {"operation": "set", "value": "2/4", "track": "pages", "confirm_clear": False},
        )
        self.assertEqual(args, ("task",))
        self.assertEqual(kwargs["task_ref"], "42")
        self.assertEqual(kwargs["value"], "2/4")
        self.assertEqual(kwargs["track"], "pages")

    def test_resource_controller_translates_attach_and_detach_payloads(self) -> None:
        class Service:
            def attach_resource(self, *args, **kwargs):
                return args, kwargs

            def detach_resource(self, *args, **kwargs):
                return args, kwargs

        args, kwargs = attach_resource(Service(), {"kind": "task", "task_ref": "42"}, {"target": "x", "label": "Docs"})
        self.assertEqual(args, ("task",))
        self.assertEqual(kwargs["task_ref"], "42")
        self.assertEqual(kwargs["label"], "Docs")
        args, kwargs = detach_resource(Service(), {"kind": "project", "project": "study", "path": "/tmp/note.md"}, {"id": 3})
        self.assertEqual(args, ("project",))
        self.assertEqual(kwargs["project_name"], "study")
        self.assertEqual(kwargs["resource_id"], 3)


if __name__ == "__main__":
    unittest.main()
