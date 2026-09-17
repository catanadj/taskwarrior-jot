from __future__ import annotations

import sys
from collections.abc import Callable, Mapping
from typing import Any


WriteTitle = Callable[[str], None]
EmitField = Callable[..., None]
WriteSectionTitle = Callable[..., None]
Style = Callable[..., str]
ProgressBar = Callable[[object], str]


def emit_progress(
    payload: dict[str, Any],
    *,
    write_title: WriteTitle,
    emit_field: EmitField,
    write_section_title: WriteSectionTitle,
    style: Style,
    progress_bar: ProgressBar,
) -> None:
    items = payload.get("items")
    if isinstance(items, list):
        _emit_progress_items(
            payload,
            items,
            write_title=write_title,
            emit_field=emit_field,
            write_section_title=write_section_title,
            style=style,
            progress_bar=progress_bar,
        )
        return
    progress = payload.get("progress")
    tracks = payload.get("tracks") or []
    kind = str(payload.get("note_kind") or "note")
    operation = str(payload.get("operation") or "show")
    write_title(f"Progress for {kind} note")
    emit_field("path", payload.get("path"), indent=0)
    emit_field("operation", operation, indent=0)
    selected_track = str(payload.get("track") or "").strip()
    if operation == "show" and not selected_track and isinstance(tracks, list):
        if not tracks:
            sys.stdout.write("\n(not set)\n")
            return
        sys.stdout.write("\n")
        for item in tracks:
            if isinstance(item, Mapping):
                _emit_progress_track(
                    item,
                    visual=True,
                    emit_field=emit_field,
                    style=style,
                    progress_bar=progress_bar,
                )
        _emit_progress_analysis(
            payload,
            write_section_title=write_section_title,
        )
        return
    if not isinstance(progress, Mapping):
        sys.stdout.write("\n(not set)\n")
        return
    _emit_progress_track(
        progress,
        visual=operation == "show",
        emit_field=emit_field,
        style=style,
        progress_bar=progress_bar,
    )
    if operation == "show":
        _emit_progress_analysis(
            payload,
            track=selected_track or str(progress.get("track") or "default"),
            write_section_title=write_section_title,
        )
    entry = str(payload.get("entry") or "").strip()
    if entry:
        emit_field("history", entry, indent=0)


def _emit_progress_items(
    payload: dict[str, Any],
    items: list[object],
    *,
    write_title: WriteTitle,
    emit_field: EmitField,
    write_section_title: WriteSectionTitle,
    style: Style,
    progress_bar: ProgressBar,
) -> None:
    kind = str(payload.get("note_kind") or "note")
    selected_track = str(payload.get("track") or "").strip()
    write_title(f"Progress for {len(items)} {kind} notes")
    for item in items:
        if not isinstance(item, Mapping):
            continue
        reference = str(item.get("reference") or "")
        identity = (
            item.get("chain_id")
            or item.get("task_short_uuid")
            or item.get("project")
            or reference
        )
        sys.stdout.write(f"\n{style(str(identity), color='identity', bold=True)}")
        if reference and reference != str(identity):
            sys.stdout.write(f"  ({reference})")
        sys.stdout.write("\n")
        tracks = item.get("tracks") or []
        if selected_track:
            progress = item.get("progress")
            if isinstance(progress, Mapping):
                _emit_progress_track(
                    progress,
                    visual=True,
                    emit_field=emit_field,
                    style=style,
                    progress_bar=progress_bar,
                )
                _emit_progress_analysis(
                    item,
                    track=selected_track,
                    write_section_title=write_section_title,
                )
            else:
                sys.stdout.write(f"  track '{selected_track}' is not set\n")
            continue
        if not isinstance(tracks, list) or not tracks:
            sys.stdout.write("  (not set)\n")
            continue
        for progress in tracks:
            if isinstance(progress, Mapping):
                _emit_progress_track(
                    progress,
                    visual=True,
                    emit_field=emit_field,
                    style=style,
                    progress_bar=progress_bar,
                )
        _emit_progress_analysis(item, write_section_title=write_section_title)


def _emit_progress_track(
    progress: Mapping[str, Any],
    *,
    visual: bool,
    emit_field: EmitField,
    style: Style,
    progress_bar: ProgressBar,
) -> None:
    if visual:
        _emit_progress_visual(progress, style=style, progress_bar=progress_bar)
        return
    emit_field("track", progress.get("track") or "default", indent=0)
    unit = str(progress.get("unit") or "").strip()
    measurement = f"{progress.get('current')}/{progress.get('target')}"
    if unit:
        measurement += f" {unit}"
    emit_field("progress", measurement, indent=0)
    percentage = progress.get("percentage")
    if percentage is not None:
        emit_field("percentage", f"{percentage}%", indent=0)
    status = str(progress.get("status") or "").strip()
    if status:
        emit_field("status", status, indent=0)
    updated = progress.get("updated")
    if updated:
        emit_field("updated", updated, indent=0)


def _emit_progress_visual(
    progress: Mapping[str, Any],
    *,
    style: Style,
    progress_bar: ProgressBar,
) -> None:
    track = str(progress.get("track") or "default")
    unit = str(progress.get("unit") or "").strip()
    measurement = f"{progress.get('current')}/{progress.get('target')}"
    if unit:
        measurement += f" {unit}"
    percentage = progress.get("percentage")
    percentage_text = f"{percentage}%" if percentage is not None else "no percentage"
    status = str(progress.get("status") or "").strip()

    sys.stdout.write(f"  {style(track, color='identity', bold=True)}\n")
    sys.stdout.write(f"  {progress_bar(percentage)}  {style(percentage_text, bold=True)}\n")
    sys.stdout.write(f"  {measurement}")
    if status:
        sys.stdout.write(f"  ·  {status}")
    sys.stdout.write("\n")
    updated = progress.get("updated")
    if updated:
        sys.stdout.write(f"  updated {updated}\n")
    sys.stdout.write("\n")


def _emit_progress_analysis(
    payload: Mapping[str, Any],
    *,
    write_section_title: WriteSectionTitle,
    track: str | None = None,
) -> None:
    trends = payload.get("trends") or []
    history = payload.get("history") or []
    selected_track = str(track or "").strip()
    if isinstance(trends, list):
        filtered = [
            item
            for item in trends
            if isinstance(item, Mapping)
            and (
                not selected_track
                or str(item.get("track") or "default").casefold() == selected_track.casefold()
            )
        ]
        if filtered:
            write_section_title("Trends", indent=2)
            for item in filtered:
                _emit_progress_trend(item)
    if isinstance(history, list) and history:
        filtered_history = [
            item
            for item in history
            if isinstance(item, Mapping)
            and (
                not selected_track
                or str(item.get("track") or "default").casefold() == selected_track.casefold()
            )
        ]
        if filtered_history:
            write_section_title("Recent history", indent=2)
            for item in filtered_history:
                _emit_progress_history_entry(item)
            sys.stdout.write("\n")


def _emit_progress_trend(trend: Mapping[str, Any]) -> None:
    track = str(trend.get("track") or "default")
    unit = str(trend.get("unit") or "").strip()
    delta = str(trend.get("delta") or "").strip()
    remaining = str(trend.get("remaining") or "").strip()
    average = str(trend.get("average_change") or "").strip()
    parts = [f"{track}: {trend.get('updates', 0)} updates"]
    if delta:
        parts.append(f"delta {delta}{(' ' + unit) if unit else ''}")
    if remaining:
        parts.append(f"remaining {remaining}{(' ' + unit) if unit else ''}")
    if average:
        parts.append(f"avg/update {average}{(' ' + unit) if unit else ''}")
    last_change = str(trend.get("last_change") or "").strip()
    if last_change:
        parts.append(f"last {last_change}{(' ' + unit) if unit else ''}")
    sys.stdout.write(f"    {' · '.join(parts)}\n")


def _emit_progress_history_entry(entry: Mapping[str, Any]) -> None:
    timestamp = str(entry.get("timestamp") or "").strip()
    track = str(entry.get("track") or "default")
    action = str(entry.get("action") or "unknown")
    summary = str(entry.get("summary") or "").strip()
    prefix = f"{timestamp}  {track}  {action}"
    if summary:
        sys.stdout.write(f"    {prefix}: {summary}\n")
    else:
        sys.stdout.write(f"    {prefix}\n")
