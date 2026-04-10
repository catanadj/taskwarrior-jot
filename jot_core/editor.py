from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path


def split_editor_command(editor_command: str) -> list[str]:
    cmd = shlex.split(editor_command)
    if not cmd:
        raise RuntimeError("editor command is empty")
    return cmd


def resolve_editor_executable(editor_command: str) -> str | None:
    cmd = split_editor_command(editor_command)
    executable = cmd[0]
    if "/" in executable:
        path = Path(executable).expanduser()
        return str(path) if path.exists() else None
    return shutil.which(executable)


def open_in_editor(path: Path, editor_command: str) -> None:
    cmd = split_editor_command(editor_command)
    cmd.append(str(path))
    completed = subprocess.run(cmd, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"editor exited with code {completed.returncode}")
