from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import re


DATE_RANGE_RE = re.compile(r"^:?(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})$")
DATE_FILTER_HELP = (
    "use :yesterday, :day, :week, :month, :quarter, :year, :lastweek, "
    ":lastmonth, :lastquarter, :lastyear, or :YYYY-MM-DD..YYYY-MM-DD"
)


@dataclass(frozen=True, slots=True)
class NoteDateFilter:
    selector: str
    start: date
    end: date
    timezone: str

    def matches(self, timestamp: str | None) -> bool:
        raw = str(timestamp or "").strip()
        if not raw:
            return False
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            local_date = parsed.astimezone().date()
        except (OverflowError, OSError, ValueError):
            return False
        return self.start <= local_date <= self.end

    def to_payload(self) -> dict[str, str]:
        return {
            "selector": self.selector,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "timezone": self.timezone,
        }


def parse_list_date_filter(
    value: str | None,
    *,
    today: date | None = None,
) -> NoteDateFilter | None:
    raw = str(value or "").strip().casefold()
    if not raw:
        return None

    local_today = today or datetime.now().astimezone().date()
    period_start: date
    period_end: date
    if raw == ":yesterday":
        period_start = period_end = local_today - timedelta(days=1)
    elif raw == ":day":
        period_start = period_end = local_today
    elif raw == ":week":
        period_start = local_today - timedelta(days=local_today.weekday())
        period_end = period_start + timedelta(days=6)
    elif raw == ":month":
        period_start = local_today.replace(day=1)
        next_month = (
            local_today.replace(year=local_today.year + 1, month=1, day=1)
            if local_today.month == 12
            else local_today.replace(month=local_today.month + 1, day=1)
        )
        period_end = next_month - timedelta(days=1)
    elif raw == ":quarter":
        quarter_month = ((local_today.month - 1) // 3) * 3 + 1
        period_start = local_today.replace(month=quarter_month, day=1)
        next_quarter_month = quarter_month + 3
        if next_quarter_month > 12:
            next_quarter = date(local_today.year + 1, 1, 1)
        else:
            next_quarter = date(local_today.year, next_quarter_month, 1)
        period_end = next_quarter - timedelta(days=1)
    elif raw == ":year":
        period_start = local_today.replace(month=1, day=1)
        period_end = local_today.replace(month=12, day=31)
    elif raw == ":lastweek":
        period_end = local_today - timedelta(days=local_today.weekday() + 1)
        period_start = period_end - timedelta(days=6)
    elif raw == ":lastmonth":
        previous_month_end = local_today.replace(day=1) - timedelta(days=1)
        period_start = previous_month_end.replace(day=1)
        period_end = previous_month_end
    elif raw == ":lastquarter":
        current_quarter_month = ((local_today.month - 1) // 3) * 3 + 1
        current_quarter_start = local_today.replace(month=current_quarter_month, day=1)
        period_end = current_quarter_start - timedelta(days=1)
        previous_quarter_month = ((period_end.month - 1) // 3) * 3 + 1
        period_start = period_end.replace(month=previous_quarter_month, day=1)
    elif raw == ":lastyear":
        period_start = date(local_today.year - 1, 1, 1)
        period_end = date(local_today.year - 1, 12, 31)
    else:
        match = DATE_RANGE_RE.fullmatch(raw)
        if match is None:
            if raw.startswith(":") or ".." in raw:
                raise RuntimeError(f"invalid note date filter '{value}'; {DATE_FILTER_HELP}")
            return None
        try:
            period_start = date.fromisoformat(match.group(1))
            period_end = date.fromisoformat(match.group(2))
        except ValueError as exc:
            raise RuntimeError(f"invalid note date filter '{value}'; use valid YYYY-MM-DD dates") from exc
        if period_start > period_end:
            raise RuntimeError(f"invalid note date filter '{value}'; start date must not be after end date")

    timezone = str(datetime.now().astimezone().tzinfo or "local")
    return NoteDateFilter(raw, period_start, period_end, timezone)
