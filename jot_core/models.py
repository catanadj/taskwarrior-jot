from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class TaskRef:
    raw: str


@dataclass(slots=True)
class ResolvedTask:
    ref: TaskRef
    task_uuid: str
    task_short_uuid: str
    description: str
    project: str
    tags: list[str]
    task: dict[str, Any] = field(repr=False)


@dataclass(slots=True)
class AppConfig:
    config_path: Path
    root_dir: Path
    trash_dir: Path
    tasks_dir: Path
    chains_dir: Path
    projects_dir: Path
    templates_dir: Path
    editor_command: str
    editor_show_diff_on_save: bool
    editor_diff_color: str
    editor_post_save_actions: bool
    color_mode: str
    default_format: str
    nautical_enabled: bool
    timewarrior_enabled: bool
    ops_max_entries: int = 10000
    ops_keep_entries: int = 5000


@dataclass(slots=True)
class NotePaths:
    note_path: Path
    existed: bool


@dataclass(slots=True)
class AppendResult:
    note_path: Path
    existed: bool
    appended_text: str


@dataclass(slots=True)
class DeleteResult:
    note_path: Path
    trash_path: Path
    existed: bool


@dataclass(slots=True)
class DoctorCheck:
    name: str
    ok: bool
    detail: str
    severity: str = "error"


@dataclass(slots=True)
class CommandResult:
    command: str
    payload: dict[str, Any]
