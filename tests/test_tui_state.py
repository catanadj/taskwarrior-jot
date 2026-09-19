from __future__ import annotations

import unittest

from jot_tui.state import TuiState


class TuiStateTests(unittest.TestCase):
    def test_state_defaults_are_isolated_and_ready_for_each_app(self) -> None:
        first = TuiState()
        second = TuiState()
        first.task_rows.append({"id": "42"})
        first.current_task_ref = "42"

        self.assertEqual(second.task_rows, [])
        self.assertIsNone(second.current_task_ref)
        self.assertEqual(first.time_period, "week")


if __name__ == "__main__":
    unittest.main()
