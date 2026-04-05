from __future__ import annotations

from dataclasses import dataclass

from .config import load_config
from .models import AppConfig
from .taskwarrior import TaskwarriorClient


@dataclass(slots=True)
class AppContext:
    config: AppConfig
    taskwarrior: TaskwarriorClient


def build_app_context() -> AppContext:
    return AppContext(
        config=load_config(),
        taskwarrior=TaskwarriorClient(),
    )
