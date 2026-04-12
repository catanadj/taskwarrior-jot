from __future__ import annotations

import os
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None

from .models import AppConfig


DEFAULT_ROOT = Path("~/.task/jot").expanduser()
DEFAULT_CONFIG_NAME = "config-jot.toml"


def _expand_path(raw: str | None, fallback: Path) -> Path:
    text = str(raw or "").strip()
    if not text:
        return fallback
    return Path(text).expanduser().resolve()


def _read_config_file(path: Path) -> dict:
    if not path.exists() or tomllib is None:
        return {}
    with path.open("rb") as handle:
        data = tomllib.load(handle) or {}
    return data if isinstance(data, dict) else {}


def load_config() -> AppConfig:
    config_path = _expand_path(os.environ.get("JOT_CONFIG"), DEFAULT_ROOT / DEFAULT_CONFIG_NAME)
    data = _read_config_file(config_path)

    paths_cfg = data.get("paths") if isinstance(data.get("paths"), dict) else {}
    editor_cfg = data.get("editor") if isinstance(data.get("editor"), dict) else {}
    display_cfg = data.get("display") if isinstance(data.get("display"), dict) else {}
    nautical_cfg = data.get("nautical") if isinstance(data.get("nautical"), dict) else {}

    root_dir = _expand_path(paths_cfg.get("root"), DEFAULT_ROOT)
    tasks_dir = _expand_path(paths_cfg.get("tasks"), root_dir / "tasks")
    chains_dir = _expand_path(paths_cfg.get("chains"), root_dir / "chains")
    projects_dir = _expand_path(paths_cfg.get("projects"), root_dir / "projects")
    templates_dir = _expand_path(paths_cfg.get("templates"), root_dir / "templates")

    editor_command = str(editor_cfg.get("command") or os.environ.get("EDITOR") or "vim").strip()
    color_mode = str(display_cfg.get("color") or "auto").strip() or "auto"
    default_format = str(display_cfg.get("default_format") or "text").strip() or "text"
    nautical_enabled = bool(nautical_cfg.get("enabled", True))

    return AppConfig(
        config_path=config_path,
        root_dir=root_dir,
        tasks_dir=tasks_dir,
        chains_dir=chains_dir,
        projects_dir=projects_dir,
        templates_dir=templates_dir,
        editor_command=editor_command,
        color_mode=color_mode,
        default_format=default_format,
        nautical_enabled=nautical_enabled,
    )


def ensure_app_dirs(config: AppConfig) -> None:
    for path in (
        config.root_dir,
        config.tasks_dir,
        config.chains_dir,
        config.projects_dir,
        config.templates_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)
