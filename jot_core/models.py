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
class TimelogSessionResult(PayloadModel):
    task_uuid: str
    task_short_uuid: str
    chain_id: str | None
    started: str
    path: str
    operation: str
    stopped: str | None = None
    session_cleared: bool = False
    already_started: bool = False
    timewarrior: Mapping[str, Any] | None = None
    timewarrior_retry: bool = False
    raw: Mapping[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_mapping(cls, item: Mapping[str, Any], *, operation: str = "") -> "TimelogSessionResult":
        return cls(
            task_uuid=str(item.get("task_uuid") or "").strip(),
            task_short_uuid=str(item.get("task_short_uuid") or "").strip(),
            chain_id=str(item.get("chain_id") or "").strip() or None,
            started=str(item.get("started") or "").strip(),
            path=str(item.get("path") or "").strip(),
            operation=operation or str(item.get("operation") or "").strip(),
            stopped=str(item.get("stopped") or "").strip() or None,
            session_cleared=bool(item.get("session_cleared")),
            already_started=bool(item.get("already_started")),
            timewarrior=item.get("timewarrior") if isinstance(item.get("timewarrior"), Mapping) else None,
            timewarrior_retry=bool(item.get("timewarrior_retry")),
            raw=dict(item),
        )

    def to_payload(self) -> dict[str, Any]:
        payload = dict(self.raw)
        payload.update(
            {
                "task_uuid": self.task_uuid,
                "task_short_uuid": self.task_short_uuid,
                "chain_id": self.chain_id,
                "started": self.started,
                "path": self.path,
                "operation": self.operation,
            }
        )
        optional = {
            "stopped": self.stopped,
            "session_cleared": self.session_cleared,
            "already_started": self.already_started,
            "timewarrior": dict(self.timewarrior) if self.timewarrior is not None else None,
            "timewarrior_retry": self.timewarrior_retry,
        }
        for key, value in optional.items():
            if key in self.raw or value not in (None, False):
                payload[key] = value
        return payload


@dataclass(frozen=True, slots=True)
class TimelogStopResult(PayloadModel):
    written: bool
    duplicate: bool
    task_short_uuid: str
    task_uuid: str
    chain_id: str | None
    started: str
    stopped: str
    duration_minutes: float
    timelog_key: str
    path: str
    session_cleared: bool
    session_path: str
    note_kind: str = ""
    reason: str = ""
    raw: Mapping[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_mapping(cls, item: Mapping[str, Any]) -> "TimelogStopResult":
        try:
            duration = float(item.get("duration_minutes") or 0)
        except (TypeError, ValueError):
            duration = 0.0
        return cls(
            written=bool(item.get("written")),
            duplicate=bool(item.get("duplicate")),
            task_short_uuid=str(item.get("task_short_uuid") or "").strip(),
            task_uuid=str(item.get("task_uuid") or "").strip(),
            chain_id=str(item.get("chain_id") or "").strip() or None,
            started=str(item.get("started") or "").strip(),
            stopped=str(item.get("stopped") or "").strip(),
            duration_minutes=duration,
            timelog_key=str(item.get("timelog_key") or "").strip(),
            path=str(item.get("path") or "").strip(),
            session_cleared=bool(item.get("session_cleared")),
            session_path=str(item.get("session_path") or "").strip(),
            note_kind=str(item.get("note_kind") or "").strip(),
            reason=str(item.get("reason") or "").strip(),
            raw=dict(item),
        )

    def to_payload(self) -> dict[str, Any]:
        payload = dict(self.raw)
        payload.update({
            "written": self.written,
            "duplicate": self.duplicate,
            "task_short_uuid": self.task_short_uuid,
            "task_uuid": self.task_uuid,
            "chain_id": self.chain_id,
            "started": self.started,
            "stopped": self.stopped,
            "duration_minutes": self.duration_minutes,
            "timelog_key": self.timelog_key,
            "path": self.path,
            "session_cleared": self.session_cleared,
            "session_path": self.session_path,
            "note_kind": self.note_kind,
            "reason": self.reason,
        })
        return payload


@dataclass(frozen=True, slots=True)
class TimelogEntryMutation(PayloadModel):
    operation: str
    key: str
    task_short_uuid: str
    path: str
    archive_path: str
    new_key: str | None = None
    started: str | None = None
    stopped: str | None = None
    duration_minutes: float | None = None
    raw: Mapping[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_mapping(cls, item: Mapping[str, Any], *, operation: str) -> "TimelogEntryMutation":
        duration_value = item.get("duration_minutes")
        try:
            duration = float(duration_value) if duration_value is not None else None
        except (TypeError, ValueError):
            duration = None
        return cls(
            operation=operation,
            key=str(item.get("timelog_key") or "").strip(),
            task_short_uuid=str(item.get("task_short_uuid") or "").strip(),
            path=str(item.get("path") or "").strip(),
            archive_path=str(item.get("archive_path") or "").strip(),
            new_key=str(item.get("new_timelog_key") or "").strip() or None,
            started=str(item.get("started") or "").strip() or None,
            stopped=str(item.get("stopped") or "").strip() or None,
            duration_minutes=duration,
            raw=dict(item),
        )

    def to_payload(self) -> dict[str, Any]:
        payload = dict(self.raw)
        payload.update({
            "operation": self.operation,
            "timelog_key": self.key,
            "task_short_uuid": self.task_short_uuid,
            "path": self.path,
            "archive_path": self.archive_path,
            "new_timelog_key": self.new_key,
            "started": self.started,
            "stopped": self.stopped,
            "duration_minutes": self.duration_minutes,
        })
        return payload


@dataclass(frozen=True, slots=True)
class TimelogStopAllResult(PayloadModel):
    stopped: str
    count: int
    error_count: int
    # Mapping.items is inherited, so explicit defaults avoid dataclass treating
    # that method as a field default during class construction.
    items: tuple[TimelogStopResult, ...] = field(default_factory=tuple)
    errors: tuple[Mapping[str, str], ...] = field(default_factory=tuple)

    @classmethod
    def from_mapping(cls, item: Mapping[str, Any]) -> "TimelogStopAllResult":
        raw_items = item.get("items")
        raw_errors = item.get("errors")
        return cls(
            stopped=str(item.get("stopped") or "").strip(),
            count=int(item.get("count") or 0),
            error_count=int(item.get("error_count") or 0),
            items=tuple(TimelogStopResult.from_mapping(row) for row in raw_items if isinstance(row, Mapping))
            if isinstance(raw_items, list) else (),
            errors=tuple(dict(row) for row in raw_errors if isinstance(row, Mapping))
            if isinstance(raw_errors, list) else (),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "stopped": self.stopped,
            "count": self.count,
            "error_count": self.error_count,
            "items": [item.to_payload() for item in self.items],
            "errors": [dict(item) for item in self.errors],
        }


@dataclass(frozen=True, slots=True)
class TimelogReport(PayloadModel):
    period: str
    details: bool
    window_start: str | None
    window_end: str | None
    filters: Mapping[str, Any]
    total_minutes: float
    total: str
    entry_count: int
    by_project: tuple[Mapping[str, Any], ...]
    by_chain: tuple[Mapping[str, Any], ...]
    by_task: tuple[Mapping[str, Any], ...]
    by_day: tuple[Mapping[str, Any], ...]
    entries: tuple[Mapping[str, Any], ...]

    @classmethod
    def from_mapping(cls, item: Mapping[str, Any]) -> "TimelogReport":
        def rows(name: str) -> tuple[Mapping[str, Any], ...]:
            value = item.get(name)
            return tuple(row for row in value if isinstance(row, Mapping)) if isinstance(value, list) else ()

        try:
            total_minutes = float(item.get("total_minutes") or 0)
        except (TypeError, ValueError):
            total_minutes = 0.0
        return cls(
            period=str(item.get("period") or "all"),
            details=bool(item.get("details")),
            window_start=str(item.get("window_start") or "").strip() or None,
            window_end=str(item.get("window_end") or "").strip() or None,
            filters=dict(item.get("filters") or {}) if isinstance(item.get("filters"), Mapping) else {},
            total_minutes=total_minutes,
            total=str(item.get("total") or "0m"),
            entry_count=int(item.get("entry_count") or 0),
            by_project=rows("by_project"),
            by_chain=rows("by_chain"),
            by_task=rows("by_task"),
            by_day=rows("by_day"),
            entries=rows("entries"),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "details": self.details,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "filters": dict(self.filters),
            "total_minutes": self.total_minutes,
            "total": self.total,
            "entry_count": self.entry_count,
            "by_project": [dict(item) for item in self.by_project],
            "by_chain": [dict(item) for item in self.by_chain],
            "by_task": [dict(item) for item in self.by_task],
            "by_day": [dict(item) for item in self.by_day],
            "entries": [dict(item) for item in self.entries],
        }


@dataclass(frozen=True, slots=True)
class ProgressTrack(PayloadModel):
    track: str
    current: str
    target: str
    unit: str
    status: str
    updated: str | None
    percentage: str | None

    @classmethod
    def from_mapping(cls, item: Mapping[str, Any]) -> "ProgressTrack":
        return cls(
            track=str(item.get("track") or "default").strip() or "default",
            current=str(item.get("current") or "").strip(),
            target=str(item.get("target") or "").strip(),
            unit=str(item.get("unit") or "").strip(),
            status=str(item.get("status") or "").strip(),
            updated=str(item.get("updated") or "").strip() or None,
            percentage=str(item.get("percentage") or "").strip() or None,
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "track": self.track,
            "current": self.current,
            "target": self.target,
            "unit": self.unit,
            "status": self.status,
            "updated": self.updated,
            "percentage": self.percentage,
        }


@dataclass(frozen=True, slots=True)
class ProgressMutationResult(PayloadModel):
    note_path: Path
    opened: bool
    progress: ProgressTrack | None
    track: str
    tracks: tuple[ProgressTrack, ...]
    entry: str | None

    @classmethod
    def from_mapping(cls, item: Mapping[str, Any]) -> "ProgressMutationResult":
        raw_progress = item.get("progress")
        raw_tracks = item.get("tracks")
        return cls(
            note_path=Path(str(item.get("note_path") or "")),
            opened=bool(item.get("opened")),
            progress=ProgressTrack.from_mapping(raw_progress) if isinstance(raw_progress, Mapping) else None,
            track=str(item.get("track") or "default").strip() or "default",
            tracks=tuple(
                ProgressTrack.from_mapping(row)
                for row in raw_tracks
                if isinstance(row, Mapping)
            ) if isinstance(raw_tracks, list) else (),
            entry=str(item.get("entry") or "") or None,
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "note_path": str(self.note_path),
            "opened": self.opened,
            "progress": self.progress.to_payload() if self.progress is not None else None,
            "track": self.track,
            "tracks": [item.to_payload() for item in self.tracks],
            "entry": self.entry,
        }


@dataclass(frozen=True, slots=True)
class NoteWorkspace(PayloadModel):
    path: str
    body: str
    resources: tuple[Mapping[str, Any], ...]
    progress: ProgressTrack | None
    progress_tracks: tuple[ProgressTrack, ...]
    exists: bool = True
    truncated: bool = False
    digest: str | None = None
    revision: int | None = None

    @classmethod
    def from_mapping(cls, item: Mapping[str, Any]) -> "NoteWorkspace":
        raw_resources = item.get("resources")
        raw_tracks = item.get("progress_tracks")
        raw_progress = item.get("progress")
        revision = item.get("revision")
        return cls(
            path=str(item.get("path") or ""),
            body=str(item.get("body") or ""),
            resources=tuple(dict(row) for row in raw_resources if isinstance(row, Mapping))
            if isinstance(raw_resources, list) else (),
            progress=ProgressTrack.from_mapping(raw_progress) if isinstance(raw_progress, Mapping) else None,
            progress_tracks=tuple(
                ProgressTrack.from_mapping(row)
                for row in raw_tracks
                if isinstance(row, Mapping)
            ) if isinstance(raw_tracks, list) else (),
            exists=bool(item.get("exists", True)),
            truncated=bool(item.get("truncated")),
            digest=str(item.get("digest") or "").strip() or None,
            revision=int(revision) if revision is not None else None,
        )

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "path": self.path,
            "body": self.body,
            "resources": [dict(item) for item in self.resources],
            "progress": self.progress.to_payload() if self.progress is not None else None,
            "progress_tracks": [item.to_payload() for item in self.progress_tracks],
        }
        if not self.exists:
            payload["exists"] = False
        if self.truncated:
            payload["truncated"] = True
        if self.digest is not None:
            payload["digest"] = self.digest
        if self.revision is not None:
            payload["revision"] = self.revision
        return payload


@dataclass(frozen=True, slots=True)
class TaskSummaryResult(PayloadModel):
    task: Mapping[str, Any]
    notes: Mapping[str, str]
    events: tuple[Mapping[str, Any], ...]
    nautical: Mapping[str, Any]

    @classmethod
    def from_mapping(cls, item: Mapping[str, Any]) -> "TaskSummaryResult":
        raw_task = item.get("task")
        raw_notes = item.get("notes")
        raw_events = item.get("events")
        raw_nautical = item.get("nautical")
        return cls(
            task=dict(raw_task) if isinstance(raw_task, Mapping) else {},
            notes={str(key): str(value or "") for key, value in raw_notes.items()}
            if isinstance(raw_notes, Mapping) else {},
            events=tuple(dict(row) for row in raw_events if isinstance(row, Mapping))
            if isinstance(raw_events, list) else (),
            nautical=dict(raw_nautical) if isinstance(raw_nautical, Mapping) else {},
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "task": dict(self.task),
            "notes": dict(self.notes),
            "events": [dict(item) for item in self.events],
            "nautical": dict(self.nautical),
        }


@dataclass(frozen=True, slots=True)
class SearchHit(PayloadModel):
    kind: str
    path: str
    match: str
    description: str = ""
    project: str | None = None
    chain_id: str | None = None
    task_short_uuid: str | None = None
    timestamp: str | None = None
    annotation: str | None = None
    raw: Mapping[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_mapping(cls, item: Mapping[str, Any]) -> "SearchHit":
        return cls(
            kind=str(item.get("kind") or "").strip(),
            path=str(item.get("path") or "").strip(),
            match=str(item.get("match") or "").strip(),
            description=str(item.get("description") or "").strip(),
            project=str(item.get("project") or "").strip() or None,
            chain_id=str(item.get("chain_id") or "").strip() or None,
            task_short_uuid=str(item.get("task_short_uuid") or "").strip() or None,
            timestamp=str(item.get("ts") or "").strip() or None,
            annotation=str(item.get("annotation") or "") or None,
            raw=dict(item),
        )

    def to_payload(self) -> dict[str, Any]:
        return dict(self.raw)


@dataclass(frozen=True, slots=True)
class SearchResults(PayloadModel):
    notes: tuple[SearchHit, ...]
    events: tuple[SearchHit, ...]

    @classmethod
    def from_mapping(cls, item: Mapping[str, Any]) -> "SearchResults":
        def hits(key: str) -> tuple[SearchHit, ...]:
            value = item.get(key)
            return tuple(SearchHit.from_mapping(row) for row in value if isinstance(row, Mapping)) \
                if isinstance(value, list) else ()

        return cls(notes=hits("notes"), events=hits("events"))

    def to_payload(self) -> dict[str, Any]:
        return {
            "notes": [item.to_payload() for item in self.notes],
            "events": [item.to_payload() for item in self.events],
        }


@dataclass(frozen=True, slots=True)
class ActivityItem(PayloadModel):
    kind: str
    timestamp: str
    title: str
    path: str = ""
    project: str | None = None
    chain_id: str | None = None
    task_short_uuid: str | None = None
    raw: Mapping[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_mapping(cls, item: Mapping[str, Any]) -> "ActivityItem":
        return cls(
            kind=str(item.get("kind") or "").strip(),
            timestamp=str(item.get("ts") or "").strip(),
            title=str(item.get("title") or item.get("description") or item.get("annotation") or "").strip(),
            path=str(item.get("path") or "").strip(),
            project=str(item.get("project") or "").strip() or None,
            chain_id=str(item.get("chain_id") or "").strip() or None,
            task_short_uuid=str(item.get("task_short_uuid") or "").strip() or None,
            raw=dict(item),
        )

    def to_payload(self) -> dict[str, Any]:
        return dict(self.raw)


@dataclass(frozen=True, slots=True)
class TaskWorkspace(PayloadModel):
    task: Mapping[str, Any]
    nautical: Mapping[str, Any]
    notes: Mapping[str, NoteWorkspace]
    events: tuple[Mapping[str, Any], ...]

    @classmethod
    def from_mapping(cls, item: Mapping[str, Any]) -> "TaskWorkspace":
        raw_notes = item.get("notes")
        raw_events = item.get("events")
        return cls(
            task=dict(item.get("task")) if isinstance(item.get("task"), Mapping) else {},
            nautical=dict(item.get("nautical")) if isinstance(item.get("nautical"), Mapping) else {},
            notes={str(key): NoteWorkspace.from_mapping(value) for key, value in raw_notes.items()
                   if isinstance(value, Mapping)} if isinstance(raw_notes, Mapping) else {},
            events=tuple(dict(row) for row in raw_events if isinstance(row, Mapping))
            if isinstance(raw_events, list) else (),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "task": dict(self.task),
            "nautical": dict(self.nautical),
            "notes": {key: value.to_payload() for key, value in self.notes.items()},
            "events": [dict(item) for item in self.events],
        }


@dataclass(frozen=True, slots=True)
class ProjectWorkspace(PayloadModel):
    project: str
    note: NoteWorkspace

    @classmethod
    def from_mapping(cls, item: Mapping[str, Any]) -> "ProjectWorkspace":
        raw_note = item.get("note")
        return cls(
            project=str(item.get("project") or "").strip(),
            note=NoteWorkspace.from_mapping(raw_note) if isinstance(raw_note, Mapping)
            else NoteWorkspace(path="", body="", resources=(), progress=None, progress_tracks=(), exists=False),
        )

    def to_payload(self) -> dict[str, Any]:
        return {"project": self.project, "note": self.note.to_payload()}


@dataclass(frozen=True, slots=True)
class AgentContext(PayloadModel):
    task: Mapping[str, Any]
    context: Mapping[str, Any]
    notes: Mapping[str, Any]
    events: Mapping[str, Any]
    nautical: Mapping[str, Any]
    warnings: tuple[str, ...]

    @classmethod
    def from_mapping(cls, item: Mapping[str, Any]) -> "AgentContext":
        raw_warnings = item.get("warnings")
        return cls(
            task=dict(item.get("task")) if isinstance(item.get("task"), Mapping) else {},
            context=dict(item.get("context")) if isinstance(item.get("context"), Mapping) else {},
            notes=dict(item.get("notes")) if isinstance(item.get("notes"), Mapping) else {},
            events=dict(item.get("events")) if isinstance(item.get("events"), Mapping) else {},
            nautical=dict(item.get("nautical")) if isinstance(item.get("nautical"), Mapping) else {},
            warnings=tuple(str(value) for value in raw_warnings) if isinstance(raw_warnings, list) else (),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "task": dict(self.task),
            "context": dict(self.context),
            "notes": dict(self.notes),
            "events": dict(self.events),
            "nautical": dict(self.nautical),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class ProgressHistoryEntry(PayloadModel):
    timestamp: str
    track: str
    action: str
    summary: str
    raw: Mapping[str, Any] = field(repr=False)
    current: str | None = None
    target: str | None = None
    unit: str | None = None
    percentage: str | None = None
    change: str | None = None
    status: str | None = None

    @classmethod
    def from_mapping(cls, item: Mapping[str, Any]) -> "ProgressHistoryEntry":
        return cls(
            timestamp=str(item.get("timestamp") or "").strip(),
            track=str(item.get("track") or "default").strip() or "default",
            action=str(item.get("action") or "unknown").strip() or "unknown",
            summary=str(item.get("summary") or "").strip(),
            raw=dict(item),
            current=str(item.get("current") or "").strip() or None,
            target=str(item.get("target") or "").strip() or None,
            unit=str(item.get("unit") or "").strip() or None,
            percentage=str(item.get("percentage") or "").strip() or None,
            change=str(item.get("change") or "").strip() or None,
            status=str(item.get("status") or "").strip() or None,
        )

    def to_payload(self) -> dict[str, Any]:
        return dict(self.raw)


@dataclass(frozen=True, slots=True)
class ProgressTrend(PayloadModel):
    track: str
    raw: Mapping[str, Any] = field(repr=False)
    updates: int = 0
    entries: int = 0
    delta: str | None = None
    direction: str | None = None
    remaining: str | None = None
    last_change: str | None = None
    average_change: str | None = None
    unit: str | None = None
    status: str | None = None

    @classmethod
    def from_mapping(cls, item: Mapping[str, Any]) -> "ProgressTrend":
        return cls(
            track=str(item.get("track") or "default").strip() or "default",
            raw=dict(item),
            updates=int(item.get("updates") or 0),
            entries=int(item.get("entries") or 0),
            delta=str(item.get("delta") or "").strip() or None,
            direction=str(item.get("direction") or "").strip() or None,
            remaining=str(item.get("remaining") or "").strip() or None,
            last_change=str(item.get("last_change") or "").strip() or None,
            average_change=str(item.get("average_change") or "").strip() or None,
            unit=str(item.get("unit") or "").strip() or None,
            status=str(item.get("status") or "").strip() or None,
        )

    def to_payload(self) -> dict[str, Any]:
        return dict(self.raw)


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
class TrashItem(PayloadModel):
    id: int
    kind: str
    deleted_at: str
    path: str
    trash_path: str
    raw: Mapping[str, Any] = field(repr=False)
    task_short_uuid: str = ""
    task_uuid: str = ""
    chain_id: str = ""
    project: str = ""
    orphaned: bool = False

    @classmethod
    def from_mapping(cls, item: Mapping[str, Any]) -> "TrashItem":
        return cls(
            id=int(item.get("id") or 0),
            kind=str(item.get("kind") or "").strip(),
            deleted_at=str(item.get("deleted_at") or "").strip(),
            path=str(item.get("path") or "").strip(),
            trash_path=str(item.get("trash_path") or "").strip(),
            raw=dict(item),
            task_short_uuid=str(item.get("task_short_uuid") or "").strip(),
            task_uuid=str(item.get("task_uuid") or "").strip(),
            chain_id=str(item.get("chain_id") or "").strip(),
            project=str(item.get("project") or "").strip(),
            orphaned=bool(item.get("orphaned")),
        )

    def to_payload(self) -> dict[str, Any]:
        payload = dict(self.raw)
        payload.update(
            {
                "id": self.id,
                "kind": self.kind,
                "deleted_at": self.deleted_at,
                "path": self.path,
                "trash_path": self.trash_path,
            }
        )
        return payload


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
