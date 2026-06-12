from __future__ import annotations

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


@dataclass(slots=True)
class ProgressResult:
    note_path: Path
    progress: dict[str, object] | None
    entry: str | None = None


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


def read_note_progress(note_path: Path) -> ProgressResult:
    metadata, _body = read_document(note_path)
    return ProgressResult(note_path=note_path, progress=_progress_from_metadata(metadata))


def set_note_progress(
    note_path: Path,
    current: Decimal,
    target: Decimal,
    *,
    unit: str | None = None,
    status: str | None = None,
) -> ProgressResult:
    metadata, body = read_document(note_path)
    previous = _progress_from_metadata(metadata)
    timestamp = iso_now()
    normalized_unit = _select_text(unit, previous, "unit")
    normalized_status = _select_text(status, previous, "status")
    _write_progress_metadata(
        metadata,
        current=current,
        target=target,
        unit=normalized_unit,
        status=normalized_status,
        updated=timestamp,
    )
    entry = _history_entry(
        timestamp,
        "set",
        current=current,
        target=target,
        unit=normalized_unit,
        status=normalized_status,
    )
    write_document(note_path, metadata, _append_progress_history(body, entry))
    return ProgressResult(note_path=note_path, progress=_progress_from_metadata(metadata), entry=entry)


def adjust_note_progress(note_path: Path, amount: Decimal) -> ProgressResult:
    metadata, body = read_document(note_path)
    current = _required_decimal(metadata, "progress_current")
    target = _required_decimal(metadata, "progress_target")
    updated_current = current + amount
    timestamp = iso_now()
    unit = str(metadata.get("progress_unit") or "").strip()
    status = str(metadata.get("progress_status") or "").strip()
    _write_progress_metadata(
        metadata,
        current=updated_current,
        target=target,
        unit=unit,
        status=status,
        updated=timestamp,
    )
    entry = _history_entry(
        timestamp,
        "adjust",
        current=updated_current,
        target=target,
        unit=unit,
        status=status,
        amount=amount,
    )
    write_document(note_path, metadata, _append_progress_history(body, entry))
    return ProgressResult(note_path=note_path, progress=_progress_from_metadata(metadata), entry=entry)


def set_note_progress_status(note_path: Path, status: str) -> ProgressResult:
    normalized = str(status or "").strip()
    if not normalized:
        raise RuntimeError("progress status is empty")
    metadata, body = read_document(note_path)
    current = _required_decimal(metadata, "progress_current")
    target = _required_decimal(metadata, "progress_target")
    timestamp = iso_now()
    unit = str(metadata.get("progress_unit") or "").strip()
    _write_progress_metadata(
        metadata,
        current=current,
        target=target,
        unit=unit,
        status=normalized,
        updated=timestamp,
    )
    entry = _history_entry(
        timestamp,
        "status",
        current=current,
        target=target,
        unit=unit,
        status=normalized,
    )
    write_document(note_path, metadata, _append_progress_history(body, entry))
    return ProgressResult(note_path=note_path, progress=_progress_from_metadata(metadata), entry=entry)


def clear_note_progress(note_path: Path) -> ProgressResult:
    metadata, body = read_document(note_path)
    previous = _progress_from_metadata(metadata)
    if previous is None:
        raise RuntimeError("progress is not set")
    timestamp = iso_now()
    for key in PROGRESS_KEYS:
        metadata.pop(key, None)
    metadata["updated"] = timestamp
    entry = f"- [{timestamp}] cleared progress state"
    write_document(note_path, metadata, _append_progress_history(body, entry))
    return ProgressResult(note_path=note_path, progress=None, entry=entry)


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
        "current": _decimal_text(current),
        "target": _decimal_text(target),
        "unit": str(metadata.get("progress_unit") or "").strip(),
        "status": str(metadata.get("progress_status") or "").strip(),
        "updated": str(metadata.get("progress_updated") or "").strip() or None,
        "percentage": percentage,
    }


def _write_progress_metadata(
    metadata: dict[str, Any],
    *,
    current: Decimal,
    target: Decimal,
    unit: str,
    status: str,
    updated: str,
) -> None:
    metadata["progress_current"] = _decimal_text(current)
    metadata["progress_target"] = _decimal_text(target)
    if unit:
        metadata["progress_unit"] = unit
    else:
        metadata.pop("progress_unit", None)
    if status:
        metadata["progress_status"] = status
    else:
        metadata.pop("progress_status", None)
    metadata["progress_updated"] = updated
    metadata["updated"] = updated


def _required_decimal(metadata: dict[str, Any], key: str) -> Decimal:
    value = metadata.get(key)
    if value in (None, ""):
        raise RuntimeError("progress is not set; use progress set first")
    return parse_progress_value(str(value))


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
    return f"- [{timestamp}] {action}: {'; '.join(details)}"


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
