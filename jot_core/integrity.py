from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .frontmatter import exclusive_file_lock, read_document, write_document
from .index import index_path, migrate_index_keys, rebuild_index, save_index
from .models import AppConfig
from .taskwarrior import TaskwarriorClient


def scan_integrity(config: AppConfig, taskwarrior: TaskwarriorClient) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    for path in sorted(config.tasks_dir.glob("*.md")):
        metadata, _body = read_document(path)
        task_uuid = str(metadata.get("task_uuid") or "").strip()
        if not task_uuid:
            findings.append({"kind": "missing-task-uuid", "path": str(path)})
            continue
        try:
            task = taskwarrior.resolve_task(task_uuid)
        except Exception as exc:
            findings.append({"kind": "task-unavailable", "path": str(path), "task_uuid": task_uuid, "detail": str(exc)})
            continue
        expected = {
            "description": task.description,
            "project": task.project,
            "tags": list(task.tags),
        }
        actual = {key: metadata.get(key) for key in expected}
        if actual != expected:
            findings.append({"kind": "stale-metadata", "path": str(path), "task_uuid": task_uuid, "expected": expected, "actual": actual})

    index = {}
    path = index_path(config)
    if path.exists():
        try:
            import json
            index = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            findings.append({"kind": "invalid-index", "path": str(path), "detail": str(exc)})
    if isinstance(index, dict):
        _migrated, collisions = migrate_index_keys(index)
        for collision in collisions:
            findings.append({"kind": "index-collision", **collision})
    return {
        "schema": "jot.integrity",
        "schema_version": 1,
        "findings": findings,
        "counts": {"total": len(findings), "by_kind": _counts(findings)},
    }


def reconcile_integrity(
    config: AppConfig,
    taskwarrior: TaskwarriorClient,
    *,
    apply: bool,
) -> dict[str, Any]:
    report = scan_integrity(config, taskwarrior)
    result: dict[str, Any] = {"dry_run": not apply, "report": report, "backup_path": None, "repaired": 0}
    if not apply:
        return result
    backup_path = _backup_path(config)
    backup_path.mkdir(parents=True, exist_ok=True)
    index = index_path(config)
    if index.exists():
        shutil.copy2(index, backup_path / index.name)
    for finding in report["findings"]:
        if finding.get("kind") != "stale-metadata":
            continue
        path = Path(str(finding["path"]))
        if not path.exists():
            continue
        metadata, body = read_document(path)
        metadata.update(finding["expected"])
        backup_note = backup_path / "notes" / path.name
        backup_note.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup_note)
        with exclusive_file_lock(path):
            write_document(path, metadata, body)
        result["repaired"] += 1
    save_index(config, rebuild_index(config))
    result["backup_path"] = str(backup_path) if backup_path.exists() else None
    return result


def _counts(findings: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in findings:
        kind = str(item.get("kind") or "unknown")
        counts[kind] = counts.get(kind, 0) + 1
    return counts


def _backup_path(config: AppConfig) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    return config.root_dir / ".jot_backups" / "integrity" / stamp
