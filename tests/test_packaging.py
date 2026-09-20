from __future__ import annotations

import hashlib
from tempfile import TemporaryDirectory
import tomllib
import unittest
from pathlib import Path

from tools.write_checksums import write_checksums


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_setuptools_discovers_all_jot_subpackages(self) -> None:
        with (PROJECT_ROOT / "pyproject.toml").open("rb") as handle:
            project = tomllib.load(handle)

        packages = project["tool"]["setuptools"]["packages"]["find"]
        self.assertEqual(packages["include"], ["jot_core*", "jot_tui*"])

    def test_checksum_manifest_is_deterministic_and_excludes_other_files(self) -> None:
        with TemporaryDirectory(prefix="jot-checksums-") as temporary:
            dist = Path(temporary)
            wheel = dist / "jot_taskwarrior-0.9.0-py3-none-any.whl"
            source = dist / "jot_taskwarrior-0.9.0.tar.gz"
            wheel.write_bytes(b"wheel")
            source.write_bytes(b"source")
            (dist / "notes.txt").write_text("ignored", encoding="utf-8")

            manifest = write_checksums(dist)

            self.assertEqual(
                manifest.read_text(encoding="ascii"),
                "\n".join(
                    (
                        f"{hashlib.sha256(wheel.read_bytes()).hexdigest()}  {wheel.name}",
                        f"{hashlib.sha256(source.read_bytes()).hexdigest()}  {source.name}",
                    )
                )
                + "\n",
            )


if __name__ == "__main__":
    unittest.main()
