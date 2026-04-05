from __future__ import annotations

import shlex
import subprocess
from pathlib import Path


def open_in_editor(path: Path, editor_command: str) -> None:
    cmd = shlex.split(editor_command)
    if not cmd:
        raise RuntimeError("editor command is empty")
    cmd.append(str(path))
    completed = subprocess.run(cmd, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"editor exited with code {completed.returncode}")
