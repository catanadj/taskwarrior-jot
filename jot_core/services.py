from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .editor import open_in_editor
from .models import AppConfig
from .nautical import nautical_summary
from .notes import (
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

    def open_task_note_in_editor(self, task_ref: str) -> str:
        task = self.taskwarrior.resolve_task(task_ref)
        note = ensure_task_note(self.config, task)
        open_in_editor(note.note_path, self.config.editor_command)
        finalize_task_note_edit(self.config, task, note)
        return str(note.note_path)

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
