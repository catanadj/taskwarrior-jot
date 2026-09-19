from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess
from tempfile import TemporaryDirectory
import unittest

from jot_core import __version__


ROOT = Path(__file__).parents[1]


class InstallSmokeTests(unittest.TestCase):
    def test_install_creates_runnable_layout_and_optional_hook(self) -> None:
        with TemporaryDirectory(prefix="jot-install-") as temporary:
            root = Path(temporary)
            home = root / "home"
            taskdata = root / "taskdata"
            prefix = root / "prefix"
            home.mkdir()
            taskdata.mkdir()
            environment = dict(os.environ)
            environment.update({
                "HOME": str(home),
                "TASKDATA": str(taskdata),
                "PREFIX": str(prefix),
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
            })

            installed = subprocess.run(
                [str(ROOT / "install.sh"), "--no-timelog-hook"],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)

            launcher = prefix / "bin" / "jot"
            library = prefix / "lib" / "jot"
            config = taskdata / "jot" / "config-jot.toml"
            self.assertTrue(launcher.is_symlink())
            self.assertTrue(launcher.exists())
            self.assertTrue(config.exists())
            self.assertTrue((library / "jot_core" / "cli.py").exists())
            self.assertTrue((library / "templates" / "task-note.md").exists())
            self.assertTrue((library / "hooks" / "on-modify_jot_timelog.py").exists())
            self.assertTrue(
                stat.S_IMODE((library / "jot").stat().st_mode) & stat.S_IXUSR
            )
            self.assertTrue(
                stat.S_IMODE((library / "hooks" / "on-modify_jot_timelog.py").stat().st_mode)
                & stat.S_IXUSR
            )

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
            self.assertEqual(version.stdout.strip(), f"jot {__version__}")

            hook_environment = dict(environment)
            hook_environment["PREFIX"] = str(root / "second-prefix")
            enabled = subprocess.run(
                [str(ROOT / "install.sh"), "--with-timelog-hook"],
                cwd=ROOT,
                env=hook_environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(enabled.returncode, 0, enabled.stderr)
            hook = root / "config" / "task" / "hooks" / "on-modify_jot_timelog.py"
            self.assertTrue(hook.exists())
            self.assertTrue(stat.S_IMODE(hook.stat().st_mode) & stat.S_IXUSR)


if __name__ == "__main__":
    unittest.main()
