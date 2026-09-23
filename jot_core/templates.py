from __future__ import annotations

import re
import sys
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from .frontmatter import FrontMatter, read_document


TOKEN_RE = re.compile(r"{{\s*([a-zA-Z0-9_]+)\s*}}|{\s*([a-zA-Z0-9_]+)\s*}")
ESCAPED_TOKEN_RE = re.compile(r"\\({{\s*[a-zA-Z0-9_]+\s*}}|{\s*[a-zA-Z0-9_]+\s*})")


@dataclass(frozen=True, slots=True)
class TextExpansion:
    text: str
    unknown_tokens: tuple[str, ...] = ()


def expand_text(text: str, context: dict[str, str]) -> TextExpansion:
    escaped: list[str] = []

    def protect(match: re.Match[str]) -> str:
        escaped.append(match.group(1))
        return f"\x00JOT_ESCAPED_{len(escaped) - 1}\x00"

    source = ESCAPED_TOKEN_RE.sub(protect, str(text or ""))
    unknown: list[str] = []

    def replace(match: re.Match[str]) -> str:
        key = match.group(1) or match.group(2)
        if key not in context:
            if key not in unknown:
                unknown.append(key)
            return match.group(0)
        return str(context[key])

    rendered = TOKEN_RE.sub(replace, source)
    for index, token in enumerate(escaped):
        rendered = rendered.replace(f"\x00JOT_ESCAPED_{index}\x00", token)
    return TextExpansion(rendered, tuple(unknown))


def bundled_templates_dir() -> Path:
    return Path(__file__).resolve().parent / "data" / "templates"


def apply_template(
    templates_dir: Path,
    *,
    kind: str,
    context: dict[str, str],
    default_metadata: OrderedDict[str, object],
    default_body: str,
) -> tuple[OrderedDict[str, object], str]:
    unknown: set[str] = set()
    template_path = templates_dir / f"{kind}.md"
    if not template_path.exists():
        template_path = bundled_templates_dir() / f"{kind}.md"
    if not template_path.exists():
        body = _render_text(default_body, context, unknown)
        _warn_unknown_templates(unknown)
        return default_metadata, body

    try:
        template_metadata, template_body = read_document(template_path)
    except Exception:
        body = _render_text(default_body, context, unknown)
        _warn_unknown_templates(unknown)
        return default_metadata, body

    metadata = _render_metadata(template_metadata, context, unknown)
    # Keep template-defined keys but always enforce jot identity/timestamps.
    for key, value in default_metadata.items():
        metadata[key] = value

    body = _render_text(template_body, context, unknown).rstrip()
    if not body:
        body = _render_text(default_body, context, unknown)
    _warn_unknown_templates(unknown)
    return metadata, body


def _render_metadata(
    metadata: FrontMatter,
    context: dict[str, str],
    unknown: set[str],
) -> OrderedDict[str, object]:
    rendered: OrderedDict[str, object] = OrderedDict()
    for key, value in metadata.items():
        if isinstance(value, list):
            rendered[key] = [_render_text(str(item), context, unknown) for item in value]
        elif isinstance(value, str):
            rendered[key] = _render_text(value, context, unknown)
        else:
            rendered[key] = value
    return rendered


def _render_text(text: str, context: dict[str, str], unknown: set[str]) -> str:
    expansion = expand_text(text, context)
    unknown.update(expansion.unknown_tokens)
    return expansion.text


def _warn_unknown_templates(tokens: set[str]) -> None:
    if tokens:
        labels = ", ".join("{" + token + "}" for token in sorted(tokens))
        sys.stderr.write(f"[jot] unknown placeholders in note template left unchanged: {labels}\n")
