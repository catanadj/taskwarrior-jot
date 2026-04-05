from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Any


FrontMatter = OrderedDict[str, Any]


def read_document(path: Path) -> tuple[FrontMatter, str]:
    text = path.read_text(encoding="utf-8")
    return parse_document(text)


def write_document(path: Path, metadata: FrontMatter, body: str) -> None:
    path.write_text(render_document(metadata, body), encoding="utf-8")


def parse_document(text: str) -> tuple[FrontMatter, str]:
    lines = str(text or "").splitlines()
    if len(lines) < 3 or lines[0].strip() != "---":
        return OrderedDict(), str(text or "")

    metadata: FrontMatter = OrderedDict()
    idx = 1
    current_key: str | None = None
    current_list: list[str] = []

    while idx < len(lines):
        line = lines[idx]
        idx += 1
        if line.strip() == "---":
            break
        if current_key and line.startswith("  - "):
            current_list.append(line[4:].strip())
            continue
        if current_key is not None:
            metadata[current_key] = list(current_list)
            current_key = None
            current_list = []
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if value:
            metadata[key] = _parse_scalar(value)
        else:
            current_key = key
            current_list = []

    if current_key is not None:
        metadata[current_key] = list(current_list)

    body_lines = lines[idx:]
    body = "\n".join(body_lines)
    if str(text or "").endswith("\n"):
        body += "\n"
    return metadata, body


def render_document(metadata: FrontMatter, body: str) -> str:
    lines = ["---"]
    for key, value in metadata.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {item}")
        else:
            lines.append(f"{key}: {_render_scalar(value)}")
    lines.append("---")
    lines.append("")
    normalized_body = str(body or "")
    if normalized_body.startswith("\n"):
        normalized_body = normalized_body[1:]
    lines.append(normalized_body.rstrip("\n"))
    return "\n".join(lines).rstrip("\n") + "\n"


def update_metadata(path: Path, updates: dict[str, Any]) -> None:
    metadata, body = read_document(path)
    for key, value in updates.items():
        metadata[key] = value
    write_document(path, metadata, body)


def _parse_scalar(value: str) -> Any:
    if value == "null":
        return None
    return value


def _render_scalar(value: Any) -> str:
    if value is None:
        return "null"
    return str(value)
