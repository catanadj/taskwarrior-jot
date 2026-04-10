from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import tempfile

from .editor import resolve_editor_executable, split_editor_command
from .config import ensure_app_dirs
from .index import read_index_status
from .models import AppConfig, CommandResult, DoctorCheck
from .ops import ops_log_path, read_ops
from .taskwarrior import TaskwarriorClient


def run_doctor(config: AppConfig, client: TaskwarriorClient) -> CommandResult:
    checks: list[DoctorCheck] = []
    checks.append(_config_check(config))

    try:
        ensure_app_dirs(config)
        checks.append(DoctorCheck(name="storage", ok=True, detail=f"root={config.root_dir}"))
    except Exception as exc:
        checks.append(DoctorCheck(name="storage", ok=False, detail=str(exc)))

    for name, path in (
        ("root_dir", config.root_dir),
        ("tasks_dir", config.tasks_dir),
        ("chains_dir", config.chains_dir),
        ("projects_dir", config.projects_dir),
        ("templates_dir", config.templates_dir),
    ):
        checks.append(_directory_check(name, path))

    checks.append(_editor_check(config.editor_command))
    checks.append(_ops_check(config))
    checks.append(_index_check(config))

    task_ok = client.is_available()
    task_detail = "task binary found" if task_ok else "task binary not found in PATH"
    if task_ok:
        try:
            version = client.version()
            task_detail = f"task {version}"
        except Exception as exc:
            task_ok = False
            task_detail = str(exc)
    checks.append(DoctorCheck(name="taskwarrior", ok=task_ok, detail=task_detail))

    return CommandResult(
        command="doctor",
        payload={"checks": [asdict(check) for check in checks]},
    )


def run_doctor_config_error(message: str, client: TaskwarriorClient | None = None) -> CommandResult:
    task_client = client or TaskwarriorClient()
    checks = [
        DoctorCheck(name="config", ok=False, detail=message),
        DoctorCheck(name="storage", ok=False, detail="not checked because config failed to load"),
        DoctorCheck(name="editor", ok=False, detail="not checked because config failed to load"),
        DoctorCheck(name="ops", ok=False, detail="not checked because config failed to load"),
        DoctorCheck(name="index", ok=False, detail="not checked because config failed to load"),
    ]

    task_ok = task_client.is_available()
    task_detail = "task binary found" if task_ok else "task binary not found in PATH"
    if task_ok:
        try:
            task_detail = f"task {task_client.version()}"
        except Exception as exc:
            task_ok = False
            task_detail = str(exc)
    checks.append(DoctorCheck(name="taskwarrior", ok=task_ok, detail=task_detail))

    return CommandResult(
        command="doctor",
        payload={"checks": [asdict(check) for check in checks]},
    )


def _config_check(config: AppConfig) -> DoctorCheck:
    if config.config_path.exists():
        return DoctorCheck(name="config", ok=True, detail=f"using {config.config_path}")
    return DoctorCheck(name="config", ok=True, detail=f"default config (missing file at {config.config_path})")


def _directory_check(name: str, path: Path) -> DoctorCheck:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path, prefix=".jot-doctor-", delete=True):
            pass
        return DoctorCheck(name=name, ok=True, detail=str(path))
    except Exception as exc:
        return DoctorCheck(name=name, ok=False, detail=f"{path}: {exc}")


def _editor_check(editor_command: str) -> DoctorCheck:
    try:
        cmd = split_editor_command(editor_command)
    except Exception as exc:
        return DoctorCheck(name="editor", ok=False, detail=str(exc))
    resolved = resolve_editor_executable(editor_command)
    if not resolved:
        return DoctorCheck(name="editor", ok=False, detail=f"{cmd[0]} not found")
    return DoctorCheck(name="editor", ok=True, detail=f"{' '.join(cmd)} -> {resolved}")


def _ops_check(config: AppConfig) -> DoctorCheck:
    path = ops_log_path(config)
    try:
        items = read_ops(config)
        detail = f"{path} ({len(items)} entries)"
        if not path.exists():
            detail = f"{path} (missing)"
        return DoctorCheck(name="ops", ok=True, detail=detail)
    except Exception as exc:
        return DoctorCheck(name="ops", ok=False, detail=f"{path}: {exc}")


def _index_check(config: AppConfig) -> DoctorCheck:
    status = read_index_status(config)
    path = config.root_dir / "index.json"
    if not status["exists"]:
        return DoctorCheck(name="index", ok=True, detail=f"{path} (missing; will rebuild on demand)")
    if not status["valid"]:
        return DoctorCheck(name="index", ok=False, detail=f"{path} (invalid)")
    note_counts = {
        "tasks": len(list(config.tasks_dir.glob("*.md"))),
        "chains": len(list(config.chains_dir.glob("*.md"))),
        "projects": len(list(config.projects_dir.glob("**/index.md"))),
    }
    ops_items = read_ops(config)
    latest_op_ts = max(
        (str(item.get("ts") or "").strip() for item in ops_items if str(item.get("ts") or "").strip()),
        default=None,
    )
    counts = status.get("counts") or {}
    stale = any(counts.get(key) != value for key, value in note_counts.items())
    updated = status.get("updated")
    if latest_op_ts and (not updated or latest_op_ts > updated):
        stale = True
    counts = status.get("counts") or {}
    detail = (
        f"{path} (updated={status.get('updated')}, stale={stale}, "
        f"tasks={counts.get('tasks')}, chains={counts.get('chains')}, projects={counts.get('projects')})"
    )
    return DoctorCheck(name="index", ok=not bool(stale), detail=detail)
