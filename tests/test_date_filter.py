from __future__ import annotations

from datetime import date
import os
import time
import unittest
from unittest import mock

from jot_core.date_filter import parse_list_date_filter


class ListDateFilterTests(unittest.TestCase):
    def test_named_periods_resolve_to_local_calendar_dates(self) -> None:
        today = date(2026, 9, 23)
        expected = {
            ":yesterday": (date(2026, 9, 22), date(2026, 9, 22)),
            ":day": (date(2026, 9, 23), date(2026, 9, 23)),
            ":week": (date(2026, 9, 21), date(2026, 9, 27)),
            ":month": (date(2026, 9, 1), date(2026, 9, 30)),
            ":quarter": (date(2026, 7, 1), date(2026, 9, 30)),
            ":year": (date(2026, 1, 1), date(2026, 12, 31)),
            ":lastweek": (date(2026, 9, 14), date(2026, 9, 20)),
            ":lastmonth": (date(2026, 8, 1), date(2026, 8, 31)),
            ":lastquarter": (date(2026, 4, 1), date(2026, 6, 30)),
            ":lastyear": (date(2025, 1, 1), date(2025, 12, 31)),
        }

        for selector, (start, end) in expected.items():
            with self.subTest(selector=selector):
                result = parse_list_date_filter(selector, today=today)
                self.assertIsNotNone(result)
                self.assertEqual((result.start, result.end), (start, end))

    def test_previous_periods_cross_calendar_boundaries(self) -> None:
        cases = {
            (date(2026, 1, 1), ":lastweek"): (date(2025, 12, 22), date(2025, 12, 28)),
            (date(2026, 1, 1), ":lastmonth"): (date(2025, 12, 1), date(2025, 12, 31)),
            (date(2026, 1, 1), ":lastquarter"): (date(2025, 10, 1), date(2025, 12, 31)),
            (date(2026, 1, 1), ":yesterday"): (date(2025, 12, 31), date(2025, 12, 31)),
        }

        for (today, selector), expected in cases.items():
            with self.subTest(today=today, selector=selector):
                result = parse_list_date_filter(selector, today=today)
                self.assertIsNotNone(result)
                self.assertEqual((result.start, result.end), expected)

    def test_explicit_range_is_inclusive_and_converts_timestamp_to_local_date(self) -> None:
        if not hasattr(time, "tzset"):
            self.skipTest("local timezone conversion requires time.tzset")
        old_tz = os.environ.get("TZ")
        try:
            with mock.patch.dict(os.environ, {"TZ": "Etc/GMT+3"}):
                time.tzset()
                result = parse_list_date_filter(":2026-09-01..2026-09-30")
                self.assertIsNotNone(result)
                self.assertTrue(result.matches("2026-10-01T02:59:59Z"))
                self.assertFalse(result.matches("2026-10-01T03:00:00Z"))
                self.assertFalse(result.matches(None))
                self.assertFalse(result.matches("not-a-timestamp"))
        finally:
            if old_tz is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old_tz
            time.tzset()

    def test_invalid_periods_and_date_ranges_are_rejected(self) -> None:
        for value in (":today", ":2026-09-30..2026-09-01", ":2026-02-30..2026-03-01", ":2026-09-01-2026-09-30"):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                parse_list_date_filter(value, today=date(2026, 9, 23))

        with self.assertRaises(RuntimeError) as raised:
            parse_list_date_filter(":today", today=date(2026, 9, 23))
        for selector in (
            ":yesterday", ":day", ":week", ":month", ":quarter", ":year",
            ":lastweek", ":lastmonth", ":lastquarter", ":lastyear",
        ):
            self.assertIn(selector, str(raised.exception))

    def test_non_filter_argument_is_not_claimed(self) -> None:
        self.assertIsNone(parse_list_date_filter("123"))


if __name__ == "__main__":
    unittest.main()
