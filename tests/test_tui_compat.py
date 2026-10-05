from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest import mock

from jot_core.tui_compat import main, tui_dependency_status


class TuiCompatibilityTests(unittest.TestCase):
    def test_reports_missing_optional_textual_dependency(self) -> None:
        with mock.patch(
            "jot_core.tui_compat.import_module",
            side_effect=ModuleNotFoundError("No module named 'textual'", name="textual"),
        ):
            status = tui_dependency_status()

        self.assertFalse(status.available)
        self.assertTrue(status.compatible)
        self.assertFalse(status.ready)
        self.assertIn("optional", status.detail)
        self.assertIn("Textual", status.detail)
        with mock.patch("jot_core.tui_compat.tui_dependency_status", return_value=status):
            self.assertEqual(main(), 1)

    def test_reports_incompatible_rich_api_with_actionable_versions(self) -> None:
        fake_textual = SimpleNamespace()
        fake_rich_style = SimpleNamespace(Style=type("Style", (), {}))

        with mock.patch(
            "jot_core.tui_compat.import_module",
            side_effect=lambda name: {
                "textual": fake_textual,
                "rich.style": fake_rich_style,
            }[name],
        ), mock.patch(
            "jot_core.tui_compat.package_version",
            side_effect=lambda name: {"textual": "6.1.0", "rich": "13.3.1"}[name],
        ):
            status = tui_dependency_status()

        self.assertFalse(status.compatible)
        self.assertIn("Textual 6.1.0", status.detail)
        self.assertIn("Rich 13.3.1", status.detail)
        self.assertIn("pip install --upgrade", status.detail)

    def test_reports_missing_rich_as_incompatible(self) -> None:
        def fake_import(name: str):
            if name == "textual":
                return SimpleNamespace()
            raise ModuleNotFoundError("No module named 'rich'", name="rich")

        with mock.patch("jot_core.tui_compat.import_module", side_effect=fake_import):
            status = tui_dependency_status()

        self.assertFalse(status.available)
        self.assertFalse(status.compatible)
        self.assertIn("Rich is missing", status.detail)
        self.assertIn("rich>=13.3.5", status.detail)

    def test_accepts_rich_with_required_textual_api(self) -> None:
        fake_textual = SimpleNamespace()
        fake_style = type("Style", (), {"clear_meta_and_links": lambda self: self})
        fake_rich_style = SimpleNamespace(Style=fake_style)

        with mock.patch(
            "jot_core.tui_compat.import_module",
            side_effect=lambda name: {
                "textual": fake_textual,
                "rich.style": fake_rich_style,
            }[name],
        ), mock.patch(
            "jot_core.tui_compat.package_version",
            side_effect=lambda name: {"textual": "6.1.0", "rich": "15.0.0"}[name],
        ):
            status = tui_dependency_status()

        self.assertTrue(status.ready)
        self.assertIn("Textual 6.1.0", status.detail)
        self.assertIn("Rich 15.0.0", status.detail)


if __name__ == "__main__":
    unittest.main()
