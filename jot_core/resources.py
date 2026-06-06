from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess


MARKDOWN_LINK_RE = re.compile(r"^\[([^\]]+)\]\(([^)]+)\)$")
SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


@dataclass(slots=True)
class ResourceItem:
    id: int
    label: str
    target: str
    kind: str
    status: str
    line: int
    raw: str

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "target": self.target,
            "kind": self.kind,
            "status": self.status,
            "line": self.line,
            "raw": self.raw,
        }


def format_resource_line(target: str, label: str | None = None) -> str:
    normalized_target = str(target or "").strip()
    if not normalized_target:
        raise RuntimeError("resource target is empty")
    normalized_label = str(label or "").strip()
    if normalized_label:
        return f"- [{normalized_label}]({normalized_target})"
    return f"- {normalized_target}"


def parse_resource_bullets(lines: list[tuple[int, str]]) -> list[ResourceItem]:
    resources: list[ResourceItem] = []
    for line_index, line in lines:
        stripped = line.strip()
        if not stripped.startswith(("- ", "* ")):
            continue
        raw = stripped[2:].strip()
        if not raw:
            continue
        label = ""
        target = raw
        match = MARKDOWN_LINK_RE.fullmatch(raw)
        if match:
            label = match.group(1).strip()
            target = match.group(2).strip()
        else:
            label = _default_label(target)
        resources.append(
            ResourceItem(
                id=len(resources) + 1,
                label=label,
                target=target,
                kind=_resource_kind(target),
                status=_resource_status(target),
                line=line_index + 1,
                raw=raw,
            )
        )
    return resources


def open_resource_target(target: str) -> list[str]:
    normalized = str(target or "").strip()
    if not normalized:
        raise RuntimeError("resource target is empty")

    opener = os.environ.get("JOT_OPENER", "").strip()
    if opener:
        command = [*shlex.split(opener), normalized]
    else:
        executable = _default_opener()
        command = [executable, normalized]

    try:
        completed = subprocess.run(command, check=False)
    except OSError as exc:
        raise RuntimeError(f"failed to open resource: {exc}") from exc
    if completed.returncode != 0:
        raise RuntimeError(f"resource opener exited with status {completed.returncode}")
    return command


def _default_label(target: str) -> str:
    value = str(target or "").strip()
    if not value:
        return ""
    if SCHEME_RE.match(value):
        return value
    name = Path(value).name
    return name or value


def _resource_kind(target: str) -> str:
    value = str(target or "").strip()
    lower = value.lower()
    if lower.startswith(("http://", "https://")):
        return "url"
    if lower.startswith("mailto:"):
        return "email"
    if lower.startswith("file://"):
        return "file"
    if SCHEME_RE.match(value):
        return "external"
    return "file"


def _resource_status(target: str) -> str:
    value = str(target or "").strip()
    if not value:
        return "missing"
    kind = _resource_kind(value)
    if kind != "file":
        return "unchecked"
    path_text = value[7:] if value.lower().startswith("file://") else value
    path = Path(path_text).expanduser()
    return "exists" if path.exists() else "missing"


def _default_opener() -> str:
    for candidate in ("xdg-open", "open"):
        executable = shutil.which(candidate)
        if executable:
            return executable
    raise RuntimeError("no resource opener found; set JOT_OPENER")
