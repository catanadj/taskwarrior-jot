from __future__ import annotations

import shutil
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .frontmatter import exclusive_file_lock, read_document, write_document
from .index import rebuild_index, save_index
from .models import AppConfig
from .ops import append_op
from .schema import NOTE_SCHEMA_VERSION, inspect_note_schema, inspect_note_schemas


def migrate_notes(config: AppConfig, *, dry_run: bool = False) -> dict[str, Any]:
    inspection = inspect_note_schemas(config)
    blocked = [
        item
        for item in inspection["items"]
        if item.get("status") in {"future", "invalid"}
    ]
    planned = [item for item in inspection["items"] if item.get("status") == "legacy"]
    result: dict[str, Any] = {
        "schema_version": NOTE_SCHEMA_VERSION,
        "dry_run": bool(dry_run),
        "total": inspection["total"],
        "planned": len(planned),
        "migrated": 0,
        "blocked": len(blocked),
        "backup_path": None,
        "items": planned + blocked,
    }
    if dry_run or blocked or not planned:
        return result

    backup_root = _migration_backup_root(config)
    for item in planned:
        path = Path(str(item["path"]))
        with exclusive_file_lock(path):
            current = inspect_note_schema(path)
            if current["status"] != "legacy":
                raise RuntimeError(
                    f"note changed while migration was running: {path} ({current['status']})"
                )
            metadata, body = read_document(path)
            backup_path = backup_root / _relative_note_path(config, path)
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup_path)
            upgraded = OrderedDict([("schema_version", NOTE_SCHEMA_VERSION)])
            upgraded.update((key, value) for key, value in metadata.items() if key != "schema_version")
            write_document(path, upgraded, body)
            result["migrated"] = int(result["migrated"]) + 1

    result["backup_path"] = str(backup_root)
    append_op(
        config,
        "schema_migrate",
        schema_version=NOTE_SCHEMA_VERSION,
        migrated=result["migrated"],
        backup_path=str(backup_root),
    )
    save_index(config, rebuild_index(config))
    return result


def _migration_backup_root(config: AppConfig) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    return config.root_dir / ".jot_backups" / f"schema-v{NOTE_SCHEMA_VERSION}" / stamp


def _relative_note_path(config: AppConfig, path: Path) -> Path:
    try:
        return path.relative_to(config.root_dir)
    except ValueError:
        return Path(path.name)
