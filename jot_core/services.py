from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .editor import open_in_editor
from .frontmatter import read_document
from .models import AppConfig
from .nautical import nautical_summary
from .notes import (
    ensure_chain_note,
    ensure_project_note,
    chain_note_path,
    ensure_task_note,
    find_chain_note,
    find_project_note,
    find_task_note,
    list_note_resources,
    project_note_path,
    task_note_path,
)
from .report import list_notes, list_project_notes, normalize_note_kinds, recent_activity
from .progress import (
    format_progress_tracks_summary,
    parse_progress_pair,
    parse_progress_value,
    read_note_progress,
)
from .resources import open_resource_target
from .search import search_all
from .storage import (
    add_to_chain_heading_storage,
    add_to_project_heading_storage,
    attach_chain_resource_storage,
    attach_project_resource_storage,
    attach_task_resource_storage,
    delete_chain_note_storage,
    delete_project_note_storage,
    delete_task_note_storage,
    detach_chain_resource_storage,
    detach_project_resource_storage,
    detach_task_resource_storage,
    finalize_chain_note_edit,
    finalize_project_note_edit,
    finalize_task_note_edit,
    add_to_task_heading_storage,
    mutate_project_progress_storage,
    mutate_task_progress_storage,
)
from .taskwarrior import TaskwarriorClient


@dataclass(slots=True)
class JotService:
    config: AppConfig
    taskwarrior: TaskwarriorClient

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        return recent_activity(self.config, limit=limit)

    def projects(self) -> list[dict[str, Any]]:
        return list_project_notes(self.config)

    def notes(self, *, kind: str = "", project: str = "") -> list[dict[str, Any]]:
        kinds = normalize_note_kinds([kind]) if str(kind or "").strip() else None
        return list_notes(self.config, kinds=kinds, project=project or None)

    def project_tree_rows(self, limit: int = 1000) -> list[dict[str, Any]]:
        items = self.taskwarrior.list_tasks(limit=limit, status="pending")
        counts: dict[str, int] = {}
        for item in items:
            project = str(item.get("project") or "").strip()
            if not project:
                continue
            counts[project] = counts.get(project, 0) + 1

        notes = {
            str(item.get("project") or "").strip(): item
            for item in list_project_notes(self.config)
            if str(item.get("project") or "").strip()
        }

        nodes: dict[str, dict[str, Any]] = {}
        for project, count in counts.items():
            parts = [part for part in project.split(".") if part]
            prefix = ""
            for depth, part in enumerate(parts):
                prefix = part if not prefix else f"{prefix}.{part}"
                node = nodes.setdefault(
                    prefix,
                    {
                        "project": prefix,
                        "depth": depth,
                        "count": 0,
                        "is_exact": False,
                        "has_note": False,
                        "updated": None,
                    },
                )
                node["count"] += count
                node["is_exact"] = node["is_exact"] or prefix == project
                note = notes.get(prefix)
                if note:
                    node["has_note"] = True
                    node["updated"] = note.get("updated") or node["updated"]
                    node["progress"] = _progress_summary_for_path(note.get("path"))

        rows = list(nodes.values())
        rows.sort(key=lambda item: (str(item.get("project") or "").lower(), int(item.get("depth") or 0)))
        for item in rows:
            depth = int(item.get("depth") or 0)
            project = str(item.get("project") or "")
            label = project.split(".")[-1] if project else ""
            item["label"] = f"{'  ' * depth}{label}"
            item["selectable"] = bool(item.get("is_exact") or item.get("has_note"))
            item["note"] = "yes" if item.get("has_note") else "-"
            item["progress"] = str(item.get("progress") or "").strip() or "-"
            item["updated"] = str(item.get("updated") or "").strip()
        return rows

    def project_note_path_for_name(self, project_name: str) -> str:
        note = find_project_note(self.config, project_name)
        return str(note or project_note_path(self.config, project_name))

    def task_note_path_for_task_ref(self, task_ref: str) -> str:
        task = self.taskwarrior.resolve_task(task_ref)
        note = find_task_note(self.config, task)
        return str(note or task_note_path(self.config, task))

    def chain_note_path_for_task_ref(self, task_ref: str) -> str:
        task = self.taskwarrior.resolve_task(task_ref)
        note = find_chain_note(self.config, task)
        chain_path = chain_note_path(self.config, task.task.get("chainID") or "", task.description or "")
        return str(note or chain_path)

    def tasks(self, limit: int = 200) -> list[dict[str, Any]]:
        items = self.taskwarrior.list_tasks(limit=limit, status="pending")
        for item in items:
            short_uuid = str(item.get("short_uuid") or "").strip()
            project = str(item.get("project") or "").strip()
            chain_id = str(item.get("chain_id") or "").strip()
            task_notes = sorted(self.config.tasks_dir.glob(f"{short_uuid}--*.md")) if short_uuid else []
            chain_notes = sorted(self.config.chains_dir.glob(f"{chain_id}--*.md")) if chain_id else []
            has_task_note = bool(task_notes)
            has_chain_note = bool(chain_notes)
            has_project_note = bool(project and find_project_note(self.config, project))
            item["has_task_note"] = has_task_note
            item["has_chain_note"] = has_chain_note
            item["has_project_note"] = has_project_note
            item["has_notes"] = has_task_note or has_chain_note or has_project_note
            summaries = []
            if task_notes:
                summary = _progress_summary_for_path(task_notes[0], prefix="T")
                if summary:
                    summaries.append(summary)
            if chain_notes:
                summary = _progress_summary_for_path(chain_notes[0], prefix="C")
                if summary:
                    summaries.append(summary)
            item["progress"] = " | ".join(summaries) or "-"
        return items

    def search(self, query: str) -> dict[str, list[dict[str, Any]]]:
        return search_all(self.config, query)

    def task_summary(self, task_ref: str) -> dict[str, Any]:
        task = self.taskwarrior.resolve_task(task_ref)
        task_note = find_task_note(self.config, task)
        chain_note = find_chain_note(self.config, task)
        project_note = find_project_note(self.config, task.project)

        chain_id = str(task.task.get("chainID") or "").strip()
        return {
            "task": {
                "uuid": task.task_uuid,
                "short_uuid": task.task_short_uuid,
                "description": task.description,
                "project": task.project,
                "tags": list(task.tags),
            },
            "notes": {
                "task": str(task_note or task_note_path(self.config, task)),
                "chain": str(chain_note or chain_note_path(self.config, chain_id, task.description or chain_id))
                if chain_id
                else "",
                "project": str(project_note or project_note_path(self.config, task.project)) if task.project else "",
            },
            "events": self.taskwarrior.annotations_for_task(task),
            "nautical": nautical_summary(task.task),
        }

    def task_workspace(self, task_ref: str) -> dict[str, Any]:
        task = self.taskwarrior.resolve_task(task_ref)
        task_note = find_task_note(self.config, task)
        chain_note = find_chain_note(self.config, task)
        project_note = find_project_note(self.config, task.project)

        def _note_payload(path) -> dict[str, Any]:
            resolved = str(path or "")
            if not path or not Path(path).exists():
                return {"path": resolved, "body": "", "resources": [], "progress": None, "progress_tracks": []}
            _metadata, body = read_document(path)
            progress_result = read_note_progress(path)
            return {
                "path": resolved,
                "body": body.strip(),
                "resources": list_note_resources(path).resources,
                "progress": progress_result.progress,
                "progress_tracks": list(progress_result.tracks),
            }

        return {
            "task": {
                "uuid": task.task_uuid,
                "short_uuid": task.task_short_uuid,
                "description": task.description,
                "project": task.project,
                "tags": list(task.tags),
            },
            "nautical": nautical_summary(task.task),
            "notes": {
                "task": _note_payload(task_note or task_note_path(self.config, task)),
                "chain": _note_payload(chain_note),
                "project": _note_payload(project_note),
            },
            "events": self.taskwarrior.annotations_for_task(task),
        }

    def project_workspace(self, project_name: str) -> dict[str, Any]:
        note = find_project_note(self.config, project_name)
        if note:
            _metadata, body = read_document(note)
            progress_result = read_note_progress(note)
            note_data = {
                "path": str(note),
                "body": body.strip(),
                "resources": list_note_resources(note).resources,
                "progress": progress_result.progress,
                "progress_tracks": list(progress_result.tracks),
            }
        else:
            note_data = {
                "path": str(project_note_path(self.config, project_name)),
                "body": "",
                "resources": [],
                "progress": None,
                "progress_tracks": [],
            }
        return {
            "project": project_name,
            "note": note_data,
        }

    def open_task_note_in_editor(self, task_ref: str) -> str:
        task = self.taskwarrior.resolve_task(task_ref)
        note = ensure_task_note(self.config, task)
        self._open_note_in_editor(note.note_path)
        finalize_task_note_edit(self.config, task, note)
        return str(note.note_path)

    def open_chain_note_in_editor(self, task_ref: str) -> str:
        task = self.taskwarrior.resolve_task(task_ref)
        note = ensure_chain_note(self.config, task)
        self._open_note_in_editor(note.note_path)
        finalize_chain_note_edit(self.config, task, note)
        return str(note.note_path)

    def open_project_note_in_editor(self, project_name: str) -> str:
        note = ensure_project_note(self.config, project_name)
        self._open_note_in_editor(note.note_path)
        finalize_project_note_edit(self.config, project_name, note)
        return str(note.note_path)

    def complete_task(self, task_ref: str) -> dict[str, Any]:
        task = self.taskwarrior.resolve_task(task_ref)
        self.taskwarrior.complete_task(task.task_uuid)
        return {
            "task_uuid": task.task_uuid,
            "task_short_uuid": task.task_short_uuid,
            "description": task.description,
        }

    def _open_note_in_editor(self, path) -> None:
        open_in_editor(
            path,
            self.config.editor_command,
            show_diff=self.config.editor_show_diff_on_save,
            color_mode=self.config.editor_diff_color,
        )

    def task_ref_for_chain_id(self, chain_id: str) -> str:
        task = self.taskwarrior.resolve_first_for_filter(f"chainID:{chain_id}")
        return task.task_short_uuid

    def add_to_task_heading(
        self,
        task_ref: str,
        *,
        heading: str,
        text: str,
        create_heading: bool = False,
        exact: bool = False,
    ) -> dict[str, Any]:
        task = self.taskwarrior.resolve_task(task_ref)
        result = add_to_task_heading_storage(
            self.config,
            task,
            heading=heading,
            text=text,
            create_heading=create_heading,
            exact=exact,
        )
        return {
            "task_short_uuid": task.task_short_uuid,
            **result,
        }

    def add_to_chain_heading(
        self,
        task_ref: str,
        *,
        heading: str,
        text: str,
        create_heading: bool = False,
        exact: bool = False,
    ) -> dict[str, Any]:
        task = self.taskwarrior.resolve_task(task_ref)
        result = add_to_chain_heading_storage(
            self.config,
            task,
            heading=heading,
            text=text,
            create_heading=create_heading,
            exact=exact,
        )
        return {
            "task_short_uuid": task.task_short_uuid,
            **result,
        }

    def add_to_project_heading(
        self,
        project_name: str,
        *,
        heading: str,
        text: str,
        create_heading: bool = False,
        exact: bool = False,
    ) -> dict[str, Any]:
        result = add_to_project_heading_storage(
            self.config,
            project_name,
            heading=heading,
            text=text,
            create_heading=create_heading,
            exact=exact,
        )
        return result

    def delete_task_note(self, task_ref: str) -> dict[str, Any]:
        task = self.taskwarrior.resolve_task(task_ref)
        return delete_task_note_storage(self.config, task)

    def delete_chain_note(self, task_ref: str) -> dict[str, Any]:
        task = self.taskwarrior.resolve_task(task_ref)
        return delete_chain_note_storage(self.config, task)

    def delete_project_note(self, project_name: str) -> dict[str, Any]:
        return delete_project_note_storage(self.config, project_name)

    def attach_resource(
        self,
        kind: str,
        *,
        task_ref: str = "",
        project_name: str = "",
        target: str,
        label: str | None = None,
    ) -> dict[str, Any]:
        if kind == "task":
            task = self.taskwarrior.resolve_task(task_ref)
            return attach_task_resource_storage(self.config, task, target=target, label=label)
        if kind == "chain":
            task = self.taskwarrior.resolve_task(task_ref)
            return attach_chain_resource_storage(self.config, task, target=target, label=label)
        if kind == "project":
            return attach_project_resource_storage(self.config, project_name, target=target, label=label)
        raise RuntimeError(f"unknown resource target kind: {kind}")

    def detach_resource(
        self,
        kind: str,
        *,
        task_ref: str = "",
        project_name: str = "",
        note_path: str,
        resource_id: int,
    ) -> dict[str, Any]:
        path = Path(note_path)
        if kind == "task":
            task = self.taskwarrior.resolve_task(task_ref)
            return detach_task_resource_storage(self.config, task, note_path=path, resource_id=resource_id)
        if kind == "chain":
            task = self.taskwarrior.resolve_task(task_ref)
            return detach_chain_resource_storage(self.config, task, note_path=path, resource_id=resource_id)
        if kind == "project":
            return detach_project_resource_storage(
                self.config,
                project_name,
                note_path=path,
                resource_id=resource_id,
            )
        raise RuntimeError(f"unknown resource target kind: {kind}")

    def open_resource(self, target: str) -> list[str]:
        return open_resource_target(target)

    def note_resources(self, note_path: str) -> list[dict[str, Any]]:
        path = Path(note_path)
        if not path.exists():
            return []
        return list_note_resources(path).resources

    def progress_track_names(
        self,
        kind: str,
        *,
        task_ref: str = "",
        project_name: str = "",
    ) -> list[str]:
        if kind in {"task", "chain"}:
            task = self.taskwarrior.resolve_task(task_ref)
            note = (
                find_task_note(self.config, task)
                if kind == "task"
                else find_chain_note(self.config, task)
            )
        elif kind == "project":
            note = find_project_note(self.config, project_name)
        else:
            raise RuntimeError(f"unknown progress target kind: {kind}")
        if note is None or not note.exists():
            return []
        return [
            str(item.get("track") or "default")
            for item in read_note_progress(note).tracks
        ]

    def update_progress(
        self,
        kind: str,
        *,
        task_ref: str = "",
        project_name: str = "",
        operation: str,
        value: str = "",
        unit: str | None = None,
        status: str | None = None,
        track: str = "default",
        confirm_clear: bool = False,
    ) -> dict[str, Any]:
        current = target = amount = None
        normalized_operation = str(operation or "").strip().lower()
        if normalized_operation == "set":
            current, target = parse_progress_pair(value)
        elif normalized_operation in {"add", "subtract"}:
            amount = parse_progress_value(value)
        elif normalized_operation == "status":
            status = str(value or status or "").strip()
        elif normalized_operation == "clear":
            if not confirm_clear:
                raise RuntimeError("progress clear requires confirmation")
        else:
            raise RuntimeError(f"unknown progress operation: {operation}")

        if kind in {"task", "chain"}:
            task = self.taskwarrior.resolve_task(task_ref)
            return mutate_task_progress_storage(
                self.config,
                task,
                note_kind=kind,
                operation=normalized_operation,
                current=current,
                target=target,
                amount=amount,
                unit=unit,
                status=status,
                track=track,
            )
        if kind == "project":
            return mutate_project_progress_storage(
                self.config,
                project_name,
                operation=normalized_operation,
                current=current,
                target=target,
                amount=amount,
                unit=unit,
                status=status,
                track=track,
            )
        raise RuntimeError(f"unknown progress target kind: {kind}")


def _progress_summary_for_path(path: object, *, prefix: str = "") -> str:
    note_path = Path(str(path or ""))
    if not str(path or "").strip() or not note_path.exists():
        return ""
    try:
        tracks = read_note_progress(note_path).tracks
    except RuntimeError:
        return f"{prefix} invalid".strip()
    return format_progress_tracks_summary(tracks, prefix=prefix)
