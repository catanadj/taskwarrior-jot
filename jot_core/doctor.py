from __future__ import annotations

from dataclasses import asdict

from .config import ensure_app_dirs
from .models import AppConfig, CommandResult, DoctorCheck
from .taskwarrior import TaskwarriorClient


def run_doctor(config: AppConfig, client: TaskwarriorClient) -> CommandResult:
    checks: list[DoctorCheck] = []
    ensure_app_dirs(config)

    checks.append(
        DoctorCheck(
            name="config",
            ok=True,
            detail=f"using {config.config_path}",
        )
    )
    checks.append(
        DoctorCheck(
            name="storage",
            ok=True,
            detail=f"root={config.root_dir}",
        )
    )

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
