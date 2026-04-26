from __future__ import annotations

import re
from collections import OrderedDict
from pathlib import Path
from typing import Any

from .frontmatter import FrontMatter, read_document


TOKEN_RE = re.compile(r"{{\s*([a-zA-Z0-9_]+)\s*}}|{\s*([a-zA-Z0-9_]+)\s*}")


def apply_template(
    templates_dir: Path,
    *,
    kind: str,
    context: dict[str, str],
    default_metadata: OrderedDict[str, object],
    default_body: str,
) -> tuple[OrderedDict[str, object], str]:
    template_path = templates_dir / f"{kind}.md"
    if not template_path.exists():
        return default_metadata, _render_text(default_body, context)

    try:
        template_metadata, template_body = read_document(template_path)
    except Exception:
        return default_metadata, _render_text(default_body, context)

    metadata = _render_metadata(template_metadata, context)
    # Keep template-defined keys but always enforce jot identity/timestamps.
    for key, value in default_metadata.items():
        metadata[key] = value

    body = _render_text(template_body, context).rstrip()
    if not body:
        body = _render_text(default_body, context)
    return metadata, body


def _render_metadata(metadata: FrontMatter, context: dict[str, str]) -> OrderedDict[str, object]:
    rendered: OrderedDict[str, object] = OrderedDict()
    for key, value in metadata.items():
        if isinstance(value, list):
            rendered[key] = [_render_text(str(item), context) for item in value]
        elif isinstance(value, str):
            rendered[key] = _render_text(value, context)
        else:
            rendered[key] = value
    return rendered


def _render_text(text: str, context: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1) or match.group(2)
        return str(context.get(key, ""))

    return TOKEN_RE.sub(replace, str(text or ""))
