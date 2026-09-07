from __future__ import annotations


NAUTICAL_FIELDS = (
    "cp",
    "anchor",
    "anchor_file",
    "anchor_mode",
    "bc",
    "omit",
    "omit_file",
    "chainMax",
    "chainUntil",
    "chain",
    "chainID",
    "prevLink",
    "nextLink",
    "link",
)


def has_nautical_context(task: dict) -> bool:
    return any(str(task.get(field) or "").strip() for field in NAUTICAL_FIELDS)


def chain_id_for_task(task: dict) -> str:
    return str(task.get("chainID") or "").strip()


def nautical_summary(task: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for field in NAUTICAL_FIELDS:
        value = str(task.get(field) or "").strip()
        if value:
            out[field] = value
    return out


def nautical_snapshot(task: dict) -> dict[str, object]:
    return {
        "fields": nautical_summary(task),
        "source": "taskwarrior",
        "delegation": "nautical-query",
        "warnings": [],
    }
