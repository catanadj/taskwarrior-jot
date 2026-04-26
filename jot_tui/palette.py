from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re


NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True, slots=True)
class PaletteEntry:
    id: str
    label: str
    detail: str
    enabled: bool = True


def filter_palette_entries(entries: list[PaletteEntry], query: str) -> list[PaletteEntry]:
    normalized = _normalize(query)
    scored: list[tuple[float, int, PaletteEntry]] = []
    for index, entry in enumerate(entries):
        if not entry.enabled:
            continue
        haystack = _normalize(" ".join((entry.id, entry.label, entry.detail)))
        if normalized:
            if normalized not in haystack and haystack not in normalized:
                ratio = SequenceMatcher(None, normalized, haystack).ratio()
                if ratio < 0.22:
                    continue
            ratio = SequenceMatcher(None, normalized, haystack).ratio()
            prefix_bonus = 0.0
            if haystack.startswith(normalized):
                prefix_bonus = 0.25
            elif normalized in haystack:
                prefix_bonus = 0.15
            score = ratio + prefix_bonus
        else:
            score = 0.0
        scored.append((score, index, entry))
    scored.sort(key=lambda item: (-item[0], item[1], item[2].label.lower()))
    return [entry for _score, _index, entry in scored]


def _normalize(value: str) -> str:
    text = NORMALIZE_RE.sub(" ", str(value or "").lower()).strip()
    return re.sub(r"\s+", " ", text)
