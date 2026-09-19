"""Install a built wheel in an isolated environment and smoke-test it."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import venv


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1:
        print("usage: check_install.py WHEEL", file=sys.stderr)
        return 2

    wheel = Path(arguments[0]).resolve()
    if wheel.suffix != ".whl" or not wheel.is_file():
        print(f"install check: wheel not found: {wheel}", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="jot-wheel-install-") as temporary:
        environment = Path(temporary) / "venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(environment)
        python = environment / "bin" / "python"
        jot = environment / "bin" / "jot"
        subprocess.run(
            [str(python), "-m", "pip", "install", "--no-deps", str(wheel)],
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
    print(f"install check: validated {wheel.name} without optional UI dependencies")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
