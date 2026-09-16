from __future__ import annotations

from pathlib import Path
import unittest
import xml.etree.ElementTree as ET


BANNER = Path(__file__).parents[1] / "taskwarrior-jot-banner.svg"


class BannerAssetTests(unittest.TestCase):
    def test_banner_uses_renderer_safe_vector_effects_and_focal_elements(self) -> None:
        root = ET.parse(BANNER).getroot()
        svg_text = BANNER.read_text(encoding="utf-8")

        self.assertNotIn("feDropShadow", svg_text)
        self.assertIn("feGaussianBlur", svg_text)
        self.assertIn("Taskwarrior", "".join(root.itertext()))
        self.assertIn("Notebook", svg_text)
        self.assertIn("Quill", svg_text)
        self.assertIsNotNone(root.find("{http://www.w3.org/2000/svg}rect"))
