from __future__ import annotations

from dataclasses import asdict
import importlib.util
from pathlib import Path
import shutil
import tempfile

from .editor import resolve_editor_executable, split_editor_command
from .config import ensure_app_dirs
from .frontmatter import find_stale_lock_dirs, repair_stale_lock_dirs
from .index import read_index_status, rebuild_index, save_index
from .migrations import migrate_notes
from .models import AppConfig, CommandResult, DoctorCheck
from .ops import ops_log_path, read_ops
from .schema import inspect_note_schemas
from .taskwarrior import TaskwarriorClient


def run_doctor(config: AppConfig, client: TaskwarriorClient, *, repair: bool = False) -> CommandResult:
    checks: list[DoctorCheck] = []
    repairs: list[dict[str, object]] = []
    checks.append(_config_check(config))

    try:
        ensure_app_dirs(config)
        checks.append(DoctorCheck(name="storage", ok=True, detail=f"root={config.root_dir}"))
        if repair:
            repairs.extend(_repair_local_state(config))
    except Exception as exc:
        checks.append(DoctorCheck(name="storage", ok=False, detail=str(exc)))

    for name, path in (
        ("root_dir", config.root_dir),
        ("trash_dir", config.trash_dir),
        ("tasks_dir", config.tasks_dir),
        ("chains_dir", config.chains_dir),
        ("projects_dir", config.projects_dir),
        ("templates_dir", config.templates_dir),
    ):
        checks.append(_directory_check(name, path))

    checks.append(_editor_check(config.editor_command))
    checks.append(_tui_check())
    checks.append(_timewarrior_check(config))
    checks.append(_locks_check(config))
    checks.append(_schema_check(config))
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
        payload={"checks": [asdict(check) for check in checks], "repairs": repairs},
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


def _tui_check() -> DoctorCheck:
    if importlib.util.find_spec("textual") is None:
        return DoctorCheck(
            name="tui",
            ok=True,
            detail="optional dependency missing; CLI available, install textual to use `jot tui`",
        )
    return DoctorCheck(name="tui", ok=True, detail="textual available")


def _timewarrior_check(config: AppConfig) -> DoctorCheck:
    if not config.timewarrior_enabled:
        return DoctorCheck(name="timewarrior", ok=True, detail="integration disabled")
    resolved = shutil.which("timew")
    if not resolved:
        return DoctorCheck(name="timewarrior", ok=False, detail="integration enabled; timew not found in PATH")
    return DoctorCheck(name="timewarrior", ok=True, detail=f"integration enabled; timew -> {resolved}")


def _locks_check(config: AppConfig) -> DoctorCheck:
    stale = find_stale_lock_dirs(config.root_dir)
    if stale:
        return DoctorCheck(
            name="locks",
            ok=False,
            detail=f"{len(stale)} stale fallback lock(s); run `jot doctor --repair`",
        )
    return DoctorCheck(name="locks", ok=True, detail="no stale fallback locks")


def _schema_check(config: AppConfig) -> DoctorCheck:
    inspection = inspect_note_schemas(config)
    counts = inspection["counts"]
    ok = not any(counts.get(key, 0) for key in ("legacy", "future", "invalid"))
    detail = (
        f"v{inspection['schema_version']} "
        f"(current={counts.get('current', 0)}, legacy={counts.get('legacy', 0)}, "
        f"future={counts.get('future', 0)}, invalid={counts.get('invalid', 0)})"
    )
    if counts.get("legacy"):
        detail += "; run `jot migrate --dry-run`"
    return DoctorCheck(name="note_schema", ok=ok, detail=detail)


def _repair_local_state(config: AppConfig) -> list[dict[str, object]]:
    repaired_locks = repair_stale_lock_dirs(config.root_dir)
    repairs: list[dict[str, object]] = [
        {
            "action": "stale-locks",
            "detail": f"removed {len(repaired_locks)} stale fallback lock(s)",
            "count": len(repaired_locks),
        }
    ]
    migration = migrate_notes(config, dry_run=False)
    if migration.get("blocked"):
        detail = f"blocked by {migration['blocked']} invalid or future note(s)"
    else:
        detail = f"migrated {migration['migrated']} note(s)"
    repairs.append({"action": "note-schema", "detail": detail, **migration})
    save_index(config, rebuild_index(config))
    repairs.append({"action": "index", "detail": "rebuilt index.json"})
    return repairs


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
