from __future__ import annotations

import json
import os
from pathlib import Path
import hashlib
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
                "--sha256", hashlib.sha256(archive.read_bytes()).hexdigest(),
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

            doctor = subprocess.run(
                [str(launcher), "doctor", "--installation-only", "--json"],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            self.assertEqual(doctor.returncode, 0, doctor.stderr)
            self.assertTrue(all(item["ok"] for item in json.loads(doctor.stdout)["checks"]))

    def test_bootstrap_installs_executable_timelog_hook(self) -> None:
        with TemporaryDirectory(prefix="jot-bootstrap-hook-") as temporary:
            root = Path(temporary)
            archive = make_fixture_archive(root)
            home = root / "home"
            taskdata = root / "taskdata"
            prefix = root / "prefix"
            hooks = root / "task-hooks"
            home.mkdir()
            taskdata.mkdir()
            hooks.mkdir()
            taskrc = home / ".taskrc"
            taskrc.write_text(
                f"data.location={taskdata}\n"
                f"hooks.location={hooks}\n",
                encoding="utf-8",
            )
            environment = dict(
                os.environ,
                HOME=str(home),
                TASKDATA=str(taskdata),
                TASKRC=str(taskrc),
            )

            result = self.run_bootstrap(
                "--archive-url", archive.as_uri(),
                "--prefix", str(prefix),
                "--taskdata", str(taskdata),
                "--with-timelog-hook",
                env=environment,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            installed_hook = hooks / "on-modify_jot_timelog.py"
            self.assertTrue(installed_hook.is_file())
            self.assertTrue(os.access(installed_hook, os.X_OK))

    def test_installation_doctor_rejects_corrupt_runtime(self) -> None:
        with TemporaryDirectory(prefix="jot-bootstrap-doctor-") as temporary:
            root = Path(temporary)
            archive = make_fixture_archive(root)
            prefix = root / "prefix"
            environment = dict(os.environ, HOME=str(root / "home"), TASKDATA=str(root / "taskdata"))

            installed = self.run_bootstrap(
                "--archive-url", archive.as_uri(),
                "--prefix", str(prefix),
                "--no-timelog-hook",
                env=environment,
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
            runtime = (prefix / "lib" / "jot" / "current").resolve()
            (runtime / "templates" / "task-note.md").unlink()

            doctor = subprocess.run(
                [str(prefix / "bin" / "jot"), "doctor", "--installation-only", "--json"],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )

            self.assertNotEqual(doctor.returncode, 0)
            checks = {item["name"]: item for item in json.loads(doctor.stdout)["checks"]}
            self.assertFalse(checks["runtime:templates/task-note.md"]["ok"])

    def test_checksum_mismatch_is_rejected_before_installation(self) -> None:
        with TemporaryDirectory(prefix="jot-bootstrap-checksum-") as temporary:
            root = Path(temporary)
            archive = make_fixture_archive(root)
            prefix = root / "prefix"
            result = self.run_bootstrap(
                "--archive-url", archive.as_uri(),
                "--sha256", "0" * 64,
                "--prefix", str(prefix),
                env=dict(os.environ, HOME=str(root / "home")),
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("archive checksum mismatch", result.stderr)
            self.assertFalse(prefix.exists())

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
