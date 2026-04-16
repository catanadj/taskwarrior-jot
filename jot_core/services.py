from __future__ import annotations

from dataclasses import dataclass
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
    project_note_path,
    task_note_path,
)
from .report import list_project_notes, recent_activity
from .search import search_all
from .storage import add_to_task_heading_storage, finalize_task_note_edit
from .storage import add_to_chain_heading_storage, add_to_project_heading_storage
from .taskwarrior import TaskwarriorClient


@dataclass(slots=True)
class JotService:
    config: AppConfig
    taskwarrior: TaskwarriorClient

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        return recent_activity(self.config, limit=limit)

    def projects(self) -> list[dict[str, Any]]:
        return list_project_notes(self.config)

    def project_note_path_for_name(self, project_name: str) -> str:
        note = find_project_note(self.config, project_name)
        return str(note or project_note_path(self.config, project_name))

    def tasks(self, limit: int = 200) -> list[dict[str, Any]]:
        return self.taskwarrior.list_tasks(limit=limit, status="pending")

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

        def _note_payload(path) -> dict[str, str]:
            resolved = str(path or "")
            if not path:
                return {"path": "", "body": ""}
            _metadata, body = read_document(path)
            return {"path": resolved, "body": body.strip()}

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
            note_data = {"path": str(note), "body": body.strip()}
        else:
            note_data = {
                "path": str(project_note_path(self.config, project_name)),
                "body": "",
            }
        return {
            "project": project_name,
            "note": note_data,
        }

    def open_task_note_in_editor(self, task_ref: str) -> str:
        task = self.taskwarrior.resolve_task(task_ref)
        note = ensure_task_note(self.config, task)
        open_in_editor(note.note_path, self.config.editor_command)
        finalize_task_note_edit(self.config, task, note)
        return str(note.note_path)

    def open_chain_note_in_editor(self, task_ref: str) -> str:
        task = self.taskwarrior.resolve_task(task_ref)
        note = ensure_chain_note(self.config, task)
        open_in_editor(note.note_path, self.config.editor_command)
        return str(note.note_path)

    def open_project_note_in_editor(self, project_name: str) -> str:
        note = ensure_project_note(self.config, project_name)
        open_in_editor(note.note_path, self.config.editor_command)
        return str(note.note_path)

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
