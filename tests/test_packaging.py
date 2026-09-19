from __future__ import annotations

import tomllib
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_setuptools_discovers_all_jot_subpackages(self) -> None:
        with (PROJECT_ROOT / "pyproject.toml").open("rb") as handle:
            project = tomllib.load(handle)

        packages = project["tool"]["setuptools"]["packages"]["find"]
        self.assertEqual(packages["include"], ["jot_core*", "jot_tui*"])


if __name__ == "__main__":
    unittest.main()
