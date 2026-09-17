from __future__ import annotations

import re
from datetime import datetime, time as datetime_time, timedelta, timezone
from typing import Any, Callable

from .models import TimelogReport


DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DateParser = Callable[[str], datetime]
IsoFormatter = Callable[[datetime], str]
DurationFormatter = Callable[[float], str]
RangeFormatter = Callable[[datetime, datetime], str]


def build_time_log_report(
    records: list[dict[str, Any]],
    *,
    period: str,
    project: str,
    task_ref: str,
    chain_id: str,
    details: bool,
    since: str,
    until: str,
    now: datetime | None,
    parse_datetime: DateParser,
    iso_z: IsoFormatter,
    duration_text: DurationFormatter,
    time_range: RangeFormatter,
) -> TimelogReport:
    window_start, window_end = _report_window(period, since=since, until=until, now=now)
    if project:
        normalized_project = project.strip().casefold()
        records = [item for item in records if str(item.get("project") or "").casefold() == normalized_project]
    if task_ref:
        normalized_task = task_ref.strip()
        records = [
            item
            for item in records
            if str(item.get("task_short_uuid") or "") == normalized_task
            or str(item.get("task_uuid") or "") == normalized_task
        ]
    if chain_id:
        normalized_chain = chain_id.strip()
        records = [item for item in records if str(item.get("chain_id") or "") == normalized_chain]
    prepared = [
        _time_log_report_record(
            item,
            window_start=window_start,
            window_end=window_end,
            parse_datetime=parse_datetime,
            iso_z=iso_z,
            duration_text=duration_text,
            time_range=time_range,
        )
        for item in records
    ]
    records = [item for item in prepared if item is not None]
    day_segments = [segment for item in records for segment in item.pop("day_segments", [])]

    total_minutes = round(sum(float(item.get("minutes") or 0) for item in records), 2)
    report_period = "custom" if since or until else period
    return TimelogReport.from_mapping({
        "period": report_period,
        "details": bool(details),
        "window_start": iso_z(window_start) if window_start else None,
        "window_end": iso_z(window_end) if window_end else None,
        "filters": {
            "project": project or None,
            "task": task_ref or None,
            "chain": chain_id or None,
            "since": since or None,
            "until": until or None,
        },
        "total_minutes": total_minutes,
        "total": duration_text(total_minutes),
        "entry_count": len(records),
        "by_project": _time_log_groups(records, "project", fallback="(no project)", duration_text=duration_text),
        "by_chain": _time_log_groups(records, "chain_id", fallback="(no chain)", duration_text=duration_text),
        "by_task": _time_log_groups(records, "task_short_uuid", fallback="(no task)", duration_text=duration_text),
        "by_day": _time_log_day_groups(day_segments, duration_text=duration_text),
        "entries": records if details else [],
    })


def _report_window(
    period: str,
    *,
    since: str = "",
    until: str = "",
    now: datetime | None = None,
) -> tuple[datetime | None, datetime | None]:
    normalized = str(period or "all").strip().casefold()
    if normalized not in {"all", "today", "week", "month"}:
        raise RuntimeError("timelog report period must be all, today, week, or month")
    if since or until:
        if normalized != "all":
            raise RuntimeError("timelog report --since/--until cannot be combined with a named period")
        start = _parse_report_boundary(since, end_of_date=False) if since else None
        end = _parse_report_boundary(until, end_of_date=True) if until else None
        if start is not None and end is not None and end <= start:
            raise RuntimeError("timelog report --until must be after --since")
        return start, end
    if normalized == "all":
        return None, None
    local_now = (now or datetime.now(timezone.utc)).astimezone()
    if normalized == "today":
        start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif normalized == "week":
        day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        start = day_start - timedelta(days=day_start.weekday())
    else:
        start = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if normalized == "month":
        end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
    elif normalized == "week":
        end = start + timedelta(days=7)
    else:
        end = start + timedelta(days=1)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _time_log_groups(
    records: list[dict[str, Any]],
    key: str,
    *,
    fallback: str,
    duration_text: DurationFormatter,
) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for record in records:
        label = str(record.get(key) or "").strip() or fallback
        item = groups.setdefault(label, {"name": label, "minutes": 0.0, "entry_count": 0})
        item["minutes"] = round(float(item["minutes"]) + float(record.get("minutes") or 0), 2)
        item["entry_count"] = int(item["entry_count"]) + 1
    for item in groups.values():
        item["duration"] = duration_text(float(item["minutes"]))
    return sorted(groups.values(), key=lambda item: (-float(item["minutes"]), str(item["name"])))


def _time_log_day_groups(records: list[dict[str, Any]], *, duration_text: DurationFormatter) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for record in records:
        day = str(record.get("day") or "").strip() or "(unknown)"
        item = groups.setdefault(day, {"name": day, "minutes": 0.0, "entry_count": 0})
        item["minutes"] = round(float(item["minutes"]) + float(record.get("minutes") or 0), 2)
        item["entry_count"] = int(item["entry_count"]) + 1
    for item in groups.values():
        item["duration"] = duration_text(float(item["minutes"]))
    return sorted(groups.values(), key=lambda item: str(item["name"]))


def _time_log_report_record(
    record: dict[str, Any],
    *,
    window_start: datetime | None,
    window_end: datetime | None,
    parse_datetime: DateParser,
    iso_z: IsoFormatter,
    duration_text: DurationFormatter,
    time_range: RangeFormatter,
) -> dict[str, Any] | None:
    item = dict(record)
    try:
        started = parse_datetime(str(item.get("started") or ""))
        stopped = parse_datetime(str(item.get("stopped") or ""))
    except RuntimeError:
        return None
    effective_start = max(started, window_start) if window_start is not None else started
    effective_stop = min(stopped, window_end) if window_end is not None else stopped
    if effective_stop <= effective_start:
        return None
    minutes = round((effective_stop - effective_start).total_seconds() / 60, 2)
    day_segments = _split_interval_by_local_day(effective_start, effective_stop, iso_z=iso_z)
    item["stored_minutes"] = float(item.get("minutes") or 0)
    item["minutes"] = minutes
    item["report_started"] = iso_z(effective_start)
    item["report_stopped"] = iso_z(effective_stop)
    item["clipped"] = effective_start != started or effective_stop != stopped
    item["display_range"] = time_range(effective_start, effective_stop)
    item["day"] = str(day_segments[0]["day"]) if len(day_segments) == 1 else f"{day_segments[0]['day']}..{day_segments[-1]['day']}"
    item["duration"] = duration_text(minutes)
    item["day_segments"] = day_segments
    return item


def _split_interval_by_local_day(started: datetime, stopped: datetime, *, iso_z: IsoFormatter) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    cursor = started
    while cursor < stopped:
        local_cursor = cursor.astimezone()
        next_date = local_cursor.date() + timedelta(days=1)
        next_midnight = datetime.combine(next_date, datetime_time.min).astimezone(timezone.utc)
        segment_stop = min(stopped, next_midnight)
        if segment_stop <= cursor:
            segment_stop = stopped
        minutes = round((segment_stop - cursor).total_seconds() / 60, 2)
        segments.append({
            "day": local_cursor.strftime("%Y-%m-%d"),
            "minutes": minutes,
            "started": iso_z(cursor),
            "stopped": iso_z(segment_stop),
        })
        cursor = segment_stop
    return segments


def _parse_report_boundary(value: str, *, end_of_date: bool) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise RuntimeError("timelog report boundary is empty")
    if DATE_ONLY_RE.fullmatch(raw):
        try:
            local = datetime.combine(datetime.fromisoformat(raw).date(), datetime_time.min)
        except ValueError as exc:
            raise RuntimeError(f"invalid report date: {value}") from exc
        if end_of_date:
            local += timedelta(days=1)
        return local.astimezone(timezone.utc)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError(f"invalid report datetime: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.astimezone(timezone.utc)
