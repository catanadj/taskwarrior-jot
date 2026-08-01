from __future__ import annotations

import difflib
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .frontmatter import atomic_write_text, exclusive_file_lock

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


def open_in_editor(
    path: Path,
    editor_command: str,
    *,
    show_diff: bool = True,
    color_mode: str = "auto",
) -> str:
    before = path.read_text(encoding="utf-8") if path.exists() else ""
    cmd = split_editor_command(editor_command)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.edit-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(before)
        editor_cmd = [*cmd, str(temporary_path)]
        completed = subprocess.run(editor_cmd, check=False)
        if completed.returncode != 0:
            raise RuntimeError(f"editor exited with code {completed.returncode}")
        after = temporary_path.read_text(encoding="utf-8")
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    with exclusive_file_lock(path):
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current != before:
            conflict_path = path.with_name(f"{path.stem}.conflict-{os.getpid()}{path.suffix}")
            counter = 1
            while conflict_path.exists():
                conflict_path = path.with_name(
                    f"{path.stem}.conflict-{os.getpid()}-{counter}{path.suffix}"
                )
                counter += 1
            atomic_write_text(conflict_path, after)
            raise RuntimeError(
                f"note changed while editor was open; edited copy saved to {conflict_path}"
            )
        atomic_write_text(path, after)

    diff = note_diff(before, after, path=path)
    if diff and show_diff:
        sys.stderr.write(colorize_diff(diff, color_mode=color_mode))
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


def colorize_diff(diff: str, *, color_mode: str = "auto") -> str:
    if not _use_diff_color(color_mode):
        return diff
    styled_lines: list[str] = []
    for line in diff.splitlines(keepends=True):
        content = line[:-1] if line.endswith("\n") else line
        newline = "\n" if line.endswith("\n") else ""
        if content.startswith("--- ") or content.startswith("+++ "):
            styled_lines.append(f"\033[1;36m{content}\033[0m{newline}")
        elif content.startswith("@@"):
            styled_lines.append(f"\033[36m{content}\033[0m{newline}")
        elif content.startswith("+"):
            styled_lines.append(f"\033[32m{content}\033[0m{newline}")
        elif content.startswith("-"):
            styled_lines.append(f"\033[31m{content}\033[0m{newline}")
        else:
            styled_lines.append(line)
    return "".join(styled_lines)


def _use_diff_color(color_mode: str) -> bool:
    mode = str(color_mode or "auto").strip().casefold()
    if mode in {"never", "false", "off", "no"}:
        return False
    if "NO_COLOR" in os.environ:
        return False
    if mode in {"always", "true", "on", "yes"}:
        return True
    return sys.stderr.isatty()
