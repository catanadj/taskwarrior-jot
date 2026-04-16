from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

from .models import ResolvedTask, TaskRef


UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{12}$"
)
SHORT_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}$")
INTEGER_RE = re.compile(r"^[0-9]+$")


@dataclass(slots=True)
class TaskwarriorClient:
    task_bin: str = "task"
    taskdata: str = ""

    def is_available(self) -> bool:
        return shutil.which(self.task_bin) is not None

    def version(self) -> str:
        proc = self._run(["--version"])
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or "could not determine Taskwarrior version")
        return proc.stdout.strip()

    def resolve_task(self, raw_ref: str) -> ResolvedTask:
        ref = TaskRef(raw=raw_ref)
        tasks = self._export_for_ref(raw_ref)
        if not tasks:
            raise RuntimeError(f"no task found for '{raw_ref}'")
        if len(tasks) > 1:
            samples = ", ".join(
                str(item.get("uuid") or "").split("-")[0]
                for item in tasks[:3]
                if isinstance(item, dict)
            )
            detail = f"task reference '{raw_ref}' is ambiguous"
            if samples:
                detail += f" ({samples})"
            raise RuntimeError(detail)
        task = tasks[0]

        uuid = str(task.get("uuid") or "").strip()
        if not uuid:
            raise RuntimeError(f"task '{raw_ref}' did not include a uuid")
        short_uuid = uuid.split("-")[0]

        tags = task.get("tags")
        tag_list = [str(tag) for tag in tags] if isinstance(tags, list) else []

        return ResolvedTask(
            ref=ref,
            task_uuid=uuid,
            task_short_uuid=short_uuid,
            description=str(task.get("description") or ""),
            project=str(task.get("project") or ""),
            tags=tag_list,
            task=task,
        )

    def add_annotation(self, task_uuid: str, text: str) -> None:
        proc = self._run(
            [
                "rc.hooks=off",
                "rc.verbose=nothing",
                "rc.confirmation=off",
                task_uuid,
                "annotate",
                text,
            ]
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or "task annotate failed")

    def annotations_for_task(self, task: ResolvedTask) -> list[dict[str, Any]]:
        raw_items = task.task.get("annotations")
        if not isinstance(raw_items, list):
            return []
        items: list[dict[str, Any]] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            items.append(
                {
                    "entry": str(item.get("entry") or "").strip() or None,
                    "description": str(item.get("description") or "").strip(),
                }
            )
        return items

    def list_tasks(self, *, limit: int = 200, status: str = "pending") -> list[dict[str, Any]]:
        if limit <= 0:
            raise RuntimeError("limit must be greater than zero")
        tokens = [f"status:{status}", f"limit:{limit}"]
        rows = self._run_export(tokens)
        items: list[dict[str, Any]] = []
        for task in rows:
            uuid = str(task.get("uuid") or "").strip()
            if not uuid:
                continue
            items.append(
                {
                    "uuid": uuid,
                    "short_uuid": uuid.split("-")[0],
                    "description": str(task.get("description") or "").strip(),
                    "project": str(task.get("project") or "").strip(),
                    "tags": [str(tag) for tag in task.get("tags") or []] if isinstance(task.get("tags"), list) else [],
                    "chain_id": str(task.get("chainID") or "").strip(),
                    "status": str(task.get("status") or "").strip(),
                    "due": str(task.get("due") or "").strip() or None,
                }
            )
        return items

    def resolve_first_for_filter(self, filter_token: str) -> ResolvedTask:
        token = str(filter_token or "").strip()
        if not token:
            raise RuntimeError("filter is empty")
        tasks = self._run_export([token])
        if not tasks:
            raise RuntimeError(f"no task found for '{token}'")
        task = tasks[0]
        uuid = str(task.get("uuid") or "").strip()
        if not uuid:
            raise RuntimeError(f"task for '{token}' did not include a uuid")
        tags = task.get("tags")
        tag_list = [str(tag) for tag in tags] if isinstance(tags, list) else []
        return ResolvedTask(
            ref=TaskRef(raw=token),
            task_uuid=uuid,
            task_short_uuid=uuid.split("-")[0],
            description=str(task.get("description") or ""),
            project=str(task.get("project") or ""),
            tags=tag_list,
            task=task,
        )

    def _export_for_ref(self, raw_ref: str) -> list[dict]:
        ref = raw_ref.strip()
        if not ref:
            raise RuntimeError("task reference is empty")

        if INTEGER_RE.fullmatch(ref):
            tokens = [ref]
        elif UUID_RE.fullmatch(ref) or SHORT_UUID_RE.fullmatch(ref):
            tokens = [f"uuid:{ref}"]
        else:
            raise RuntimeError(f"unsupported task reference '{raw_ref}'")

        return self._run_export(tokens)

    def _run_export(self, tokens: list[str]) -> list[dict]:
        proc = self._run(
            [
                "rc.hooks=off",
                "rc.verbose=nothing",
                "rc.color=off",
                "rc.json.array=1",
                *tokens,
                "export",
            ]
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or "task export failed")
        body = (proc.stdout or "").strip()
        if not body:
            return []
        data = json.loads(body)
        if not isinstance(data, list):
            raise RuntimeError("task export returned non-array JSON")
        return [item for item in data if isinstance(item, dict)]

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        cmd = [self.task_bin, *self._command_prefix(), *args]
        return subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
        )

    def _command_prefix(self) -> list[str]:
        taskdata = self.taskdata or str(os.environ.get("TASKDATA") or "").strip()
        if taskdata:
            return [f"rc.data.location={taskdata}"]
        return []
