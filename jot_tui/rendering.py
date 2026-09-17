from __future__ import annotations

from typing import Any, Callable


EmptyGuidance = Callable[[str, str], str]


def render_note_panel(
    title: str,
    note: dict[str, Any],
    *,
    empty_guidance: EmptyGuidance,
) -> str:
    path = str(note.get("path") or "").strip()
    body = str(note.get("body") or "").strip()
    if not body:
        return empty_guidance(title, path)
    lines = [title, ""]
    lines.append(f"Path: {path or '(none)'}")
    lines.append("")
    lines.append(note_excerpt(body))
    lines.append("")
    lines.append("Actions: e edit | f attach resource | g progress")
    return "\n".join(lines)


def render_events_panel(events: list[dict[str, Any]]) -> str:
    if not events:
        return "Events\n\n(none)"
    lines = ["Events", ""]
    for item in events[:12]:
        entry = str(item.get("entry") or "").strip()
        desc = str(item.get("description") or "").strip()
        lines.append(f"{entry}  {desc}".strip())
    return "\n".join(lines)


def render_workspace_resources(note_items: list[tuple[str, dict[str, Any]]]) -> str:
    lines = ["Resources", ""]
    found = False
    for label, note in note_items:
        path = str(note.get("path") or "").strip()
        resources = note.get("resources") or []
        if not path and not resources:
            continue
        lines.append(f"{label.capitalize()} note")
        if path:
            lines.append(f"Path: {path}")
        if not resources:
            lines.append("  (none)")
            lines.append("")
            continue
        found = True
        for item in resources:
            name = str(item.get("label") or item.get("target") or "").strip()
            kind = str(item.get("kind") or "resource").strip()
            status = str(item.get("status") or "").strip()
            target = str(item.get("target") or "").strip()
            suffix = f"[{kind}]"
            if status and status != "unchecked":
                suffix += f" {status}"
            lines.append(f"  {item.get('id')}. {name} {suffix}")
            if target and target != name:
                lines.append(f"     {target}")
        lines.append("")
    if not found and len(lines) == 2:
        lines.append("No resources attached yet.")
        lines.append("Press f to attach a file path or URL to the active note.")
        lines.append("After attaching, press o to open or x to detach.")
    lines.append("Actions: f attach | o open | x detach")
    return "\n".join(lines).strip()


def render_workspace_progress(note_items: list[tuple[str, dict[str, Any]]]) -> str:
    lines = ["Progress", ""]
    found = False
    for label, note in note_items:
        tracks = note.get("progress_tracks")
        if not isinstance(tracks, list):
            progress = note.get("progress")
            tracks = [progress] if isinstance(progress, dict) else []
        if not tracks:
            continue
        lines.append(f"{label.capitalize()} note")
        for progress in tracks:
            if not isinstance(progress, dict):
                continue
            found = True
            track = str(progress.get("track") or "default")
            current = str(progress.get("current") or "0")
            target = str(progress.get("target") or "0")
            unit = str(progress.get("unit") or "").strip()
            status = str(progress.get("status") or "").strip()
            percentage = progress.get("percentage")
            measurement = f"{current}/{target}"
            if unit:
                measurement += f" {unit}"
            lines.append(f"  [{track}] {measurement}")
            if percentage is not None:
                lines.append(f"    {progress_bar(str(percentage))} {percentage}%")
            if status:
                lines.append(f"    Status: {status}")
            if progress.get("updated"):
                lines.append(f"    Updated: {progress.get('updated')}")
        lines.append("")
    if not found:
        lines.append("No progress tracks yet.")
        lines.append("Press g to set a current/target measurement.")
        lines.append("Examples: pages read, workout sets, rooms finished, checklist items.")
        lines.append("")
    lines.append("Action: g set, adjust, change status, or clear")
    return "\n".join(lines).strip()


def workspace_has_resources(notes: list[dict[str, Any]]) -> bool:
    return any(bool(note.get("resources") or []) for note in notes)


def workspace_has_progress(notes: list[dict[str, Any]]) -> bool:
    for note in notes:
        tracks = note.get("progress_tracks")
        if isinstance(tracks, list) and tracks:
            return True
        if isinstance(note.get("progress"), dict):
            return True
    return False


def progress_bar(percentage: str, width: int = 24) -> str:
    try:
        value = float(percentage)
    except (TypeError, ValueError):
        value = 0.0
    clamped = max(0.0, min(100.0, value))
    filled = round((clamped / 100.0) * width)
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def note_excerpt(body: str, *, max_lines: int = 16, max_width: int = 92) -> str:
    cleaned: list[str] = []
    for raw in str(body or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            if cleaned and cleaned[-1] != "":
                cleaned.append("")
            continue
        cleaned.append(line)
        if len(cleaned) >= max_lines:
            break
    if not cleaned:
        return ""
    out: list[str] = []
    for line in cleaned[:max_lines]:
        out.append(line if len(line) <= max_width else line[: max_width - 3] + "...")
    return "\n".join(out).strip()


def pretty_label(key: str) -> str:
    return str(key).replace("_", " ").capitalize()
