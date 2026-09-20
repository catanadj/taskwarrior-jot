from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tarfile
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).parents[1]


def make_fixture_archive(destination: Path) -> Path:
    archive = destination / "jot-fixture.tar.gz"
    archive_root = "jot-fixture"
    with tarfile.open(archive, "w:gz") as bundle:
        for name in ("install.sh", "uninstall.sh", "jot", "jot_core", "jot_tui"):
            bundle.add(ROOT / name, arcname=f"{archive_root}/{name}")
    return archive


class BootstrapTests(unittest.TestCase):
    def run_bootstrap(self, *args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(ROOT / "bootstrap.sh"), *args],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

    def test_local_archive_bootstrap_installs_and_verifies(self) -> None:
        with TemporaryDirectory(prefix="jot-bootstrap-") as temporary:
            root = Path(temporary)
            archive = make_fixture_archive(root)
            home = root / "home"
            taskdata = root / "taskdata"
            prefix = root / "prefix"
            home.mkdir()
            taskdata.mkdir()
            environment = dict(os.environ, HOME=str(home), TASKDATA=str(taskdata))

            result = self.run_bootstrap(
                "--version", "fixture",
                "--archive-url", archive.as_uri(),
                "--prefix", str(prefix),
                "--taskdata", str(taskdata),
                "--no-timelog-hook",
                env=environment,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            launcher = prefix / "bin" / "jot"
            self.assertTrue(launcher.is_symlink())
            self.assertTrue(launcher.exists())
            version = subprocess.run(
                [str(launcher), "--version"],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            self.assertEqual(version.returncode, 0, version.stderr)
            self.assertTrue(version.stdout.startswith("jot "))

    def test_dry_run_does_not_create_prefix(self) -> None:
        with TemporaryDirectory(prefix="jot-bootstrap-dry-") as temporary:
            root = Path(temporary)
            archive = make_fixture_archive(root)
            prefix = root / "prefix"
            result = self.run_bootstrap(
                "--archive-url", archive.as_uri(),
                "--prefix", str(prefix),
                "--dry-run",
                env=dict(os.environ, HOME=str(root / "home")),
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("No files were installed", result.stdout)
            self.assertFalse(prefix.exists())


if __name__ == "__main__":
    unittest.main()
