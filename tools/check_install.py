"""Install a built distribution artifact in an isolated environment."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import venv


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1:
        print("usage: check_install.py ARTIFACT", file=sys.stderr)
        return 2

    artifact = Path(arguments[0]).resolve()
    if not (artifact.name.endswith((".whl", ".tar.gz")) and artifact.is_file()):
        print(f"install check: distribution artifact not found: {artifact}", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="jot-wheel-install-") as temporary:
        environment = Path(temporary) / "venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(environment)
        python = environment / "bin" / "python"
        jot = environment / "bin" / "jot"
        subprocess.run(
            [str(python), "-m", "pip", "install", "--no-deps", str(artifact)],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                str(python),
                "-c",
                "import importlib.util; assert importlib.util.find_spec('textual') is None",
            ],
            check=True,
        )
        subprocess.run([str(jot), "--version"], check=True, capture_output=True, text=True)
        subprocess.run([str(jot), "--help"], check=True, capture_output=True, text=True)
        subprocess.run(
            [
                str(python),
                "-c",
                "import jot_tui.controllers, jot_tui.modals, jot_tui.panes",
            ],
            check=True,
        )
    print(f"install check: validated {artifact.name} without optional UI dependencies")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
