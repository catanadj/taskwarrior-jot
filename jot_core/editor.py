from __future__ import annotations

import difflib
import shlex
import shutil
import subprocess
import sys
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


def open_in_editor(path: Path, editor_command: str) -> str:
    before = path.read_text(encoding="utf-8") if path.exists() else ""
    cmd = split_editor_command(editor_command)
    cmd.append(str(path))
    completed = subprocess.run(cmd, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"editor exited with code {completed.returncode}")
    after = path.read_text(encoding="utf-8") if path.exists() else ""
    diff = note_diff(before, after, path=path)
    if diff:
        sys.stderr.write(diff)
        if not diff.endswith("\n"):
            sys.stderr.write("\n")
    return diff


def note_diff(before: str, after: str, *, path: Path) -> str:
    if before == after:
        return ""
    diff = difflib.unified_diff(
        before.splitlines(),
        after.splitlines(),
        fromfile=f"{path} (before)",
        tofile=f"{path} (after)",
        lineterm="",
    )
    return "\n".join(diff) + "\n"
