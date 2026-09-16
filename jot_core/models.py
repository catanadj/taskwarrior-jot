from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generic, Iterator, Mapping, TypeAlias, TypedDict, TypeVar


JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
ResultT = TypeVar("ResultT")


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


class PayloadModel(Mapping[str, Any]):
    """Read-only mapping compatibility for models during the migration."""

    def to_payload(self) -> dict[str, Any]:
        raise NotImplementedError

    def __getitem__(self, key: str) -> Any:
        return self.to_payload()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_payload())

    def __len__(self) -> int:
        return len(self.to_payload())


@dataclass(frozen=True, slots=True)
class TimelogSession(PayloadModel):
    task_uuid: str
    task_short_uuid: str
    description: str
    project: str
    chain_id: str | None
    started: str
    elapsed_minutes: float | None
    elapsed: str
    raw: Mapping[str, Any] = field(repr=False)

    @classmethod
    def from_mapping(cls, item: Mapping[str, Any]) -> "TimelogSession":
        elapsed_minutes = item.get("elapsed_minutes")
        try:
            parsed_elapsed = float(elapsed_minutes) if elapsed_minutes is not None else None
        except (TypeError, ValueError):
            parsed_elapsed = None
        return cls(
            task_uuid=str(item.get("task_uuid") or "").strip(),
            task_short_uuid=str(item.get("task_short_uuid") or "").strip(),
            description=str(item.get("description") or "").strip(),
            project=str(item.get("project") or "").strip(),
            chain_id=str(item.get("chain_id") or "").strip() or None,
            started=str(item.get("started") or "").strip(),
            elapsed_minutes=parsed_elapsed,
            elapsed=str(item.get("elapsed") or "").strip(),
            raw=dict(item),
        )

    def to_payload(self) -> dict[str, Any]:
        payload = dict(self.raw)
        payload.update(
            {
                "task_uuid": self.task_uuid,
                "task_short_uuid": self.task_short_uuid,
                "description": self.description,
                "project": self.project,
                "chain_id": self.chain_id,
                "started": self.started,
                "elapsed_minutes": self.elapsed_minutes,
                "elapsed": self.elapsed,
            }
        )
        return payload


@dataclass(frozen=True, slots=True)
class TimelogWriteResult(PayloadModel):
    written: bool
    note_kind: str
    path: str
    task_short_uuid: str
    task_uuid: str
    chain_id: str | None
    started: str
    stopped: str
    duration_minutes: float
    timelog_key: str
    raw: Mapping[str, Any] = field(repr=False)
    reason: str = ""
    duplicate: bool = False
    heading: str = ""
    entry: str = ""

    @classmethod
    def from_mapping(cls, item: Mapping[str, Any]) -> "TimelogWriteResult":
        try:
            duration = float(item.get("duration_minutes") or 0)
        except (TypeError, ValueError):
            duration = 0.0
        return cls(
            written=bool(item.get("written")),
            note_kind=str(item.get("note_kind") or "").strip(),
            path=str(item.get("path") or "").strip(),
            task_short_uuid=str(item.get("task_short_uuid") or "").strip(),
            task_uuid=str(item.get("task_uuid") or "").strip(),
            chain_id=str(item.get("chain_id") or "").strip() or None,
            started=str(item.get("started") or "").strip(),
            stopped=str(item.get("stopped") or "").strip(),
            duration_minutes=duration,
            timelog_key=str(item.get("timelog_key") or "").strip(),
            reason=str(item.get("reason") or "").strip(),
            duplicate=bool(item.get("duplicate")),
            heading=str(item.get("heading") or "").strip(),
            entry=str(item.get("entry") or ""),
            raw=dict(item),
        )

    def to_payload(self) -> dict[str, Any]:
        payload = dict(self.raw)
        payload.update(
            {
                "written": self.written,
                "note_kind": self.note_kind,
                "path": self.path,
                "task_short_uuid": self.task_short_uuid,
                "task_uuid": self.task_uuid,
                "chain_id": self.chain_id,
                "started": self.started,
                "stopped": self.stopped,
                "duration_minutes": self.duration_minutes,
                "timelog_key": self.timelog_key,
                "reason": self.reason,
                "duplicate": self.duplicate,
                "heading": self.heading,
                "entry": self.entry,
            }
        )
        return payload


@dataclass(frozen=True, slots=True)
class TaskSummary(PayloadModel):
    uuid: str
    short_uuid: str
    description: str
    project: str
    tags: tuple[str, ...]
    chain_id: str
    status: str
    due: str | None
    progress: str = "-"
    has_task_note: bool = False
    has_chain_note: bool = False
    has_project_note: bool = False
    has_notes: bool = False

    @classmethod
    def from_mapping(cls, item: Mapping[str, Any]) -> "TaskSummary":
        tags = item.get("tags")
        return cls(
            uuid=str(item.get("uuid") or "").strip(),
            short_uuid=str(item.get("short_uuid") or "").strip(),
            description=str(item.get("description") or "").strip(),
            project=str(item.get("project") or "").strip(),
            tags=tuple(str(tag) for tag in tags) if isinstance(tags, (list, tuple)) else (),
            chain_id=str(item.get("chain_id") or "").strip(),
            status=str(item.get("status") or "").strip(),
            due=str(item.get("due") or "").strip() or None,
            progress=str(item.get("progress") or "-") or "-",
            has_task_note=bool(item.get("has_task_note")),
            has_chain_note=bool(item.get("has_chain_note")),
            has_project_note=bool(item.get("has_project_note")),
            has_notes=bool(item.get("has_notes")),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "uuid": self.uuid,
            "short_uuid": self.short_uuid,
            "description": self.description,
            "project": self.project,
            "tags": list(self.tags),
            "chain_id": self.chain_id,
            "status": self.status,
            "due": self.due,
            "progress": self.progress,
            "has_task_note": self.has_task_note,
            "has_chain_note": self.has_chain_note,
            "has_project_note": self.has_project_note,
            "has_notes": self.has_notes,
        }


@dataclass(frozen=True, slots=True)
class NoteSummary(PayloadModel):
    kind: str
    identifier: str
    title: str
    description: str
    project: str
    updated: str | None
    path: str
    preview: str = ""
    resources: int = 0
    progress: str = ""
    task_short_uuid: str = ""
    chain_id: str = ""

    @classmethod
    def from_mapping(cls, item: Mapping[str, Any]) -> "NoteSummary":
        return cls(
            kind=str(item.get("kind") or "").strip(),
            identifier=str(item.get("id") or "").strip(),
            title=str(item.get("title") or "").strip(),
            description=str(item.get("description") or "").strip(),
            project=str(item.get("project") or "").strip(),
            updated=str(item.get("updated") or "").strip() or None,
            path=str(item.get("path") or "").strip(),
            preview=str(item.get("preview") or ""),
            resources=int(item.get("resources") or 0),
            progress=str(item.get("progress") or ""),
            task_short_uuid=str(item.get("task_short_uuid") or "").strip(),
            chain_id=str(item.get("chain_id") or "").strip(),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "id": self.identifier,
            "title": self.title,
            "description": self.description,
            "project": self.project,
            "updated": self.updated,
            "path": self.path,
            "preview": self.preview,
            "resources": self.resources,
            "progress": self.progress,
            "task_short_uuid": self.task_short_uuid,
            "chain_id": self.chain_id,
        }


@dataclass(frozen=True, slots=True)
class ProjectTreeRow(PayloadModel):
    project: str
    label: str
    depth: int
    count: int
    note: str
    progress: str
    updated: str
    selectable: bool

    @classmethod
    def from_mapping(cls, item: Mapping[str, Any]) -> "ProjectTreeRow":
        return cls(
            project=str(item.get("project") or "").strip(),
            label=str(item.get("label") or "").strip(),
            depth=int(item.get("depth") or 0),
            count=int(item.get("count") or 0),
            note=str(item.get("note") or ""),
            progress=str(item.get("progress") or "-"),
            updated=str(item.get("updated") or "").strip(),
            selectable=bool(item.get("selectable")),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "label": self.label,
            "depth": self.depth,
            "count": self.count,
            "note": self.note,
            "progress": self.progress,
            "updated": self.updated,
            "selectable": self.selectable,
        }


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


_MISSING = object()


@dataclass(slots=True, init=False)
class CommandResult(Generic[ResultT]):
    command: str
    data: ResultT

    def __init__(
        self,
        command: str,
        data: ResultT | object = _MISSING,
        *,
        payload: ResultT | object = _MISSING,
    ) -> None:
        if data is not _MISSING and payload is not _MISSING:
            raise TypeError("CommandResult accepts data or payload, not both")
        value = data if data is not _MISSING else payload
        self.command = command
        self.data = value  # type: ignore[assignment]

    @property
    def payload(self) -> ResultT:
        """Compatibility alias while command handlers migrate to ``data``."""
        return self.data
