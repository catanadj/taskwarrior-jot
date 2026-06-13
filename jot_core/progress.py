from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .frontmatter import read_document, write_document
from .ops import iso_now


PROGRESS_KEYS = (
    "progress_current",
    "progress_target",
    "progress_unit",
    "progress_status",
    "progress_updated",
)
PROGRESS_TRACKS_KEY = "progress_tracks"
DEFAULT_TRACK = "default"


@dataclass(slots=True)
class ProgressResult:
    note_path: Path
    progress: dict[str, object] | None
    entry: str | None = None
    track: str = DEFAULT_TRACK
    tracks: tuple[dict[str, object], ...] = ()


def parse_progress_value(value: str) -> Decimal:
    normalized = str(value or "").strip()
    if not normalized:
        raise RuntimeError("progress value is empty")
    try:
        number = Decimal(normalized)
    except InvalidOperation as exc:
        raise RuntimeError(f"invalid progress value: {value}") from exc
    if not number.is_finite():
        raise RuntimeError("progress value must be finite")
    return number


def parse_progress_pair(value: str) -> tuple[Decimal, Decimal]:
    normalized = str(value or "").strip()
    if normalized.count("/") != 1:
        raise RuntimeError("progress must use CURRENT/TARGET, for example 120/350")
    current_text, target_text = normalized.split("/", 1)
    return parse_progress_value(current_text), parse_progress_value(target_text)


def read_note_progress(note_path: Path, track: str = DEFAULT_TRACK) -> ProgressResult:
    metadata, _body = read_document(note_path)
    normalized_track = normalize_progress_track(track)
    tracks = _progress_tracks_from_metadata(metadata)
    return ProgressResult(
        note_path=note_path,
        progress=_find_track(tracks, normalized_track),
        track=normalized_track,
        tracks=tracks,
    )


def read_note_progress_tracks(note_path: Path) -> tuple[dict[str, object], ...]:
    metadata, _body = read_document(note_path)
    return _progress_tracks_from_metadata(metadata)


def normalize_progress_track(track: str | None) -> str:
    normalized = " ".join(str(track or "").strip().split())
    if not normalized:
        return DEFAULT_TRACK
    if normalized.casefold() == DEFAULT_TRACK:
        return DEFAULT_TRACK
    if len(normalized) > 80:
        raise RuntimeError("progress track name must be 80 characters or fewer")
    if any(character in normalized for character in "\r\n"):
        raise RuntimeError("progress track name cannot contain line breaks")
    return normalized


def format_progress_summary(progress: dict[str, object] | None, *, prefix: str = "") -> str:
    if not isinstance(progress, dict):
        return ""
    current = str(progress.get("current") or "").strip()
    target = str(progress.get("target") or "").strip()
    if not current or not target:
        return ""
    measurement = f"{current}/{target}"
    unit = str(progress.get("unit") or "").strip()
    if unit:
        measurement += f" {unit}"
    percentage = progress.get("percentage")
    if percentage is not None:
        measurement += f" ({percentage}%)"
    normalized_prefix = str(prefix or "").strip()
    return f"{normalized_prefix} {measurement}".strip()


def format_progress_tracks_summary(
    tracks: tuple[dict[str, object], ...] | list[dict[str, object]],
    *,
    prefix: str = "",
    limit: int = 2,
) -> str:
    summaries: list[str] = []
    for progress in tracks[:limit]:
        track = str(progress.get("track") or DEFAULT_TRACK)
        label = "" if track == DEFAULT_TRACK else f"{track}:"
        summary = format_progress_summary(progress, prefix=label)
        if summary:
            summaries.append(summary)
    remaining = len(tracks) - len(summaries)
    if remaining > 0:
        summaries.append(f"+{remaining} more")
    joined = " | ".join(summaries)
    normalized_prefix = str(prefix or "").strip()
    return f"{normalized_prefix} {joined}".strip()


def set_note_progress(
    note_path: Path,
    current: Decimal,
    target: Decimal,
    *,
    unit: str | None = None,
    status: str | None = None,
    track: str = DEFAULT_TRACK,
) -> ProgressResult:
    metadata, body = read_document(note_path)
    normalized_track = normalize_progress_track(track)
    previous = _find_track(_progress_tracks_from_metadata(metadata), normalized_track)
    timestamp = iso_now()
    normalized_unit = _select_text(unit, previous, "unit")
    normalized_status = _select_text(status, previous, "status")
    progress = _build_progress(
        current=current,
        target=target,
        unit=normalized_unit,
        status=normalized_status,
        updated=timestamp,
        track=normalized_track,
    )
    _write_progress(
        metadata,
        progress,
    )
    entry = _history_entry(
        timestamp,
        "set",
        current=current,
        target=target,
        unit=normalized_unit,
        status=normalized_status,
        track=normalized_track,
    )
    write_document(note_path, metadata, _append_progress_history(body, entry))
    tracks = _progress_tracks_from_metadata(metadata)
    return ProgressResult(note_path, _find_track(tracks, normalized_track), entry, normalized_track, tracks)


def adjust_note_progress(note_path: Path, amount: Decimal, *, track: str | None = None) -> ProgressResult:
    metadata, body = read_document(note_path)
    normalized_track = _resolve_existing_track(metadata, track)
    previous = _required_track(metadata, normalized_track)
    current = parse_progress_value(str(previous["current"]))
    target = parse_progress_value(str(previous["target"]))
    updated_current = current + amount
    timestamp = iso_now()
    unit = str(previous.get("unit") or "").strip()
    status = str(previous.get("status") or "").strip()
    progress = _build_progress(
        current=updated_current,
        target=target,
        unit=unit,
        status=status,
        updated=timestamp,
        track=normalized_track,
    )
    _write_progress(metadata, progress)
    entry = _history_entry(
        timestamp,
        "adjust",
        current=updated_current,
        target=target,
        unit=unit,
        status=status,
        amount=amount,
        track=normalized_track,
    )
    write_document(note_path, metadata, _append_progress_history(body, entry))
    tracks = _progress_tracks_from_metadata(metadata)
    return ProgressResult(note_path, _find_track(tracks, normalized_track), entry, normalized_track, tracks)


def set_note_progress_status(
    note_path: Path,
    status: str,
    *,
    track: str | None = None,
) -> ProgressResult:
    normalized = str(status or "").strip()
    if not normalized:
        raise RuntimeError("progress status is empty")
    metadata, body = read_document(note_path)
    normalized_track = _resolve_existing_track(metadata, track)
    previous = _required_track(metadata, normalized_track)
    current = parse_progress_value(str(previous["current"]))
    target = parse_progress_value(str(previous["target"]))
    timestamp = iso_now()
    unit = str(previous.get("unit") or "").strip()
    progress = _build_progress(
        current=current,
        target=target,
        unit=unit,
        status=normalized,
        updated=timestamp,
        track=normalized_track,
    )
    _write_progress(metadata, progress)
    entry = _history_entry(
        timestamp,
        "status",
        current=current,
        target=target,
        unit=unit,
        status=normalized,
        track=normalized_track,
    )
    write_document(note_path, metadata, _append_progress_history(body, entry))
    tracks = _progress_tracks_from_metadata(metadata)
    return ProgressResult(note_path, _find_track(tracks, normalized_track), entry, normalized_track, tracks)


def clear_note_progress(note_path: Path, *, track: str | None = None) -> ProgressResult:
    metadata, body = read_document(note_path)
    normalized_track = _resolve_existing_track(metadata, track)
    previous = _find_track(_progress_tracks_from_metadata(metadata), normalized_track)
    if previous is None:
        raise RuntimeError(f"progress track '{normalized_track}' is not set")
    timestamp = iso_now()
    if normalized_track == DEFAULT_TRACK:
        for key in PROGRESS_KEYS:
            metadata.pop(key, None)
    else:
        named = [item for item in _named_tracks_from_metadata(metadata) if not _same_track(item, normalized_track)]
        _write_named_tracks(metadata, named)
    metadata["updated"] = timestamp
    entry = f"- [{timestamp}] [{normalized_track}] cleared progress state"
    write_document(note_path, metadata, _append_progress_history(body, entry))
    tracks = _progress_tracks_from_metadata(metadata)
    return ProgressResult(note_path, None, entry, normalized_track, tracks)


def _progress_from_metadata(metadata: dict[str, Any]) -> dict[str, object] | None:
    current_raw = metadata.get("progress_current")
    target_raw = metadata.get("progress_target")
    if current_raw in (None, "") or target_raw in (None, ""):
        return None
    current = parse_progress_value(str(current_raw))
    target = parse_progress_value(str(target_raw))
    percentage = None
    if target != 0:
        percentage = _percentage_text((current / target) * Decimal("100"))
    return {
        "track": DEFAULT_TRACK,
        "current": _decimal_text(current),
        "target": _decimal_text(target),
        "unit": str(metadata.get("progress_unit") or "").strip(),
        "status": str(metadata.get("progress_status") or "").strip(),
        "updated": str(metadata.get("progress_updated") or "").strip() or None,
        "percentage": percentage,
    }


def _build_progress(
    *,
    current: Decimal,
    target: Decimal,
    unit: str,
    status: str,
    updated: str,
    track: str,
) -> dict[str, object]:
    percentage = None if target == 0 else _percentage_text((current / target) * Decimal("100"))
    return {
        "track": track,
        "current": _decimal_text(current),
        "target": _decimal_text(target),
        "unit": unit,
        "status": status,
        "updated": updated,
        "percentage": percentage,
    }


def _write_progress(metadata: dict[str, Any], progress: dict[str, object]) -> None:
    track = str(progress["track"])
    if track == DEFAULT_TRACK:
        metadata["progress_current"] = progress["current"]
        metadata["progress_target"] = progress["target"]
        _write_optional(metadata, "progress_unit", progress.get("unit"))
        _write_optional(metadata, "progress_status", progress.get("status"))
        metadata["progress_updated"] = progress["updated"]
    else:
        named = [item for item in _named_tracks_from_metadata(metadata) if not _same_track(item, track)]
        named.append(progress)
        _write_named_tracks(metadata, named)
    metadata["updated"] = progress["updated"]


def _write_optional(metadata: dict[str, Any], key: str, value: object) -> None:
    if str(value or "").strip():
        metadata[key] = value
    else:
        metadata.pop(key, None)


def _progress_tracks_from_metadata(metadata: dict[str, Any]) -> tuple[dict[str, object], ...]:
    tracks: list[dict[str, object]] = []
    default = _progress_from_metadata(metadata)
    if default is not None:
        tracks.append(default)
    tracks.extend(_named_tracks_from_metadata(metadata))
    return tuple(tracks)


def _named_tracks_from_metadata(metadata: dict[str, Any]) -> list[dict[str, object]]:
    raw = metadata.get(PROGRESS_TRACKS_KEY)
    if raw in (None, ""):
        return []
    try:
        decoded = json.loads(str(raw))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("invalid progress_tracks metadata") from exc
    if not isinstance(decoded, list):
        raise RuntimeError("progress_tracks metadata must be a list")
    tracks: list[dict[str, object]] = []
    for item in decoded:
        if not isinstance(item, dict):
            raise RuntimeError("progress_tracks entries must be objects")
        track = normalize_progress_track(str(item.get("track") or ""))
        if track.casefold() == DEFAULT_TRACK:
            raise RuntimeError("named progress tracks cannot use the reserved name 'default'")
        current = parse_progress_value(str(item.get("current") or ""))
        target = parse_progress_value(str(item.get("target") or ""))
        tracks.append(
            _build_progress(
                current=current,
                target=target,
                unit=str(item.get("unit") or "").strip(),
                status=str(item.get("status") or "").strip(),
                updated=str(item.get("updated") or "").strip(),
                track=track,
            )
        )
    return tracks


def _write_named_tracks(metadata: dict[str, Any], tracks: list[dict[str, object]]) -> None:
    if not tracks:
        metadata.pop(PROGRESS_TRACKS_KEY, None)
        return
    stored = [
        {key: value for key, value in track.items() if key != "percentage" and value not in ("", None)}
        for track in tracks
    ]
    metadata[PROGRESS_TRACKS_KEY] = json.dumps(stored, ensure_ascii=True, separators=(",", ":"))


def _same_track(progress: dict[str, object], track: str) -> bool:
    return str(progress.get("track") or "").casefold() == track.casefold()


def _find_track(
    tracks: tuple[dict[str, object], ...],
    track: str,
) -> dict[str, object] | None:
    return next((item for item in tracks if _same_track(item, track)), None)


def _required_track(metadata: dict[str, Any], track: str) -> dict[str, object]:
    progress = _find_track(_progress_tracks_from_metadata(metadata), track)
    if progress is None:
        raise RuntimeError(f"progress track '{track}' is not set; use progress set first")
    return progress


def _resolve_existing_track(metadata: dict[str, Any], requested: str | None) -> str:
    tracks = _progress_tracks_from_metadata(metadata)
    if requested is not None:
        return normalize_progress_track(requested)
    default = _find_track(tracks, DEFAULT_TRACK)
    if default is not None:
        return DEFAULT_TRACK
    if len(tracks) == 1:
        return str(tracks[0].get("track") or DEFAULT_TRACK)
    if not tracks:
        raise RuntimeError("progress is not set; use progress set first")
    names = ", ".join(str(item.get("track") or DEFAULT_TRACK) for item in tracks)
    raise RuntimeError(f"multiple progress tracks exist ({names}); specify --track")


def _select_text(value: str | None, previous: dict[str, object] | None, key: str) -> str:
    if value is not None:
        return str(value).strip()
    if previous is None:
        return ""
    return str(previous.get(key) or "").strip()


def _history_entry(
    timestamp: str,
    action: str,
    *,
    current: Decimal,
    target: Decimal,
    unit: str,
    status: str,
    amount: Decimal | None = None,
    track: str = DEFAULT_TRACK,
) -> str:
    measurement = f"{_decimal_text(current)}/{_decimal_text(target)}"
    if unit:
        measurement += f" {unit}"
    details = [measurement]
    if amount is not None:
        sign = "+" if amount >= 0 else ""
        details.append(f"change {sign}{_decimal_text(amount)}")
    if status:
        details.append(f"status {status}")
    track_label = "" if track == DEFAULT_TRACK else f"[{track}] "
    return f"- [{timestamp}] {track_label}{action}: {'; '.join(details)}"


def _append_progress_history(body: str, entry: str) -> str:
    lines = str(body or "").splitlines()
    heading_index = _progress_heading_index(lines)
    if heading_index is None:
        while lines and not lines[-1].strip():
            lines.pop()
        if lines:
            lines.extend(["", "## Progress", "", entry])
        else:
            lines.extend(["## Progress", "", entry])
        return "\n".join(lines)

    next_index = len(lines)
    for index in range(heading_index + 1, len(lines)):
        stripped = lines[index].lstrip()
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            if level <= 2 and stripped[level : level + 1] == " ":
                next_index = index
                break
    section = lines[heading_index + 1 : next_index]
    while section and not section[-1].strip():
        section.pop()
    section.extend(["", entry])
    return "\n".join(lines[: heading_index + 1] + section + lines[next_index:])


def _progress_heading_index(lines: list[str]) -> int | None:
    for index, line in enumerate(lines):
        if line.strip().lower() == "## progress":
            return index
    return None


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"-0", ""} else text


def _percentage_text(value: Decimal) -> str:
    return _decimal_text(Decimal(format(value, ".2f")))
