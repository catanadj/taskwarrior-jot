from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, TypeAlias, TypedDict


JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


class RawTask(TypedDict, total=False):
    uuid: str
    description: str
    status: str
    project: str
    chainID: str
    tags: list[str]


@dataclass(frozen=True, slots=True)
class Task:
    uuid: str
    short_uuid: str
    description: str
    status: str
    project: str
    chain_id: str
    tags: tuple[str, ...]
    raw: Mapping[str, JsonValue] = field(repr=False)


def normalize_task(raw: Mapping[str, JsonValue]) -> Task:
    uuid = str(raw.get("uuid") or "").strip()
    tags = raw.get("tags")
    tag_values = tuple(str(tag).strip() for tag in tags) if isinstance(tags, list) else ()
    return Task(
        uuid=uuid,
        short_uuid=uuid.split("-", 1)[0],
        description=str(raw.get("description") or "").strip(),
        status=str(raw.get("status") or "").strip(),
        project=str(raw.get("project") or "").strip(),
        chain_id=str(raw.get("chainID") or "").strip(),
        tags=tag_values,
        raw=dict(raw),
    )


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
