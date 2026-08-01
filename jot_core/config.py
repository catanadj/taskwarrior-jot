from __future__ import annotations

import os
from pathlib import Path
import re
import tomllib

from .models import AppConfig


DEFAULT_TASKDATA = Path("~/.task").expanduser()
DEFAULT_CONFIG_NAME = "config-jot.toml"
TASKRC_DATA_RE = re.compile(r"^\s*(?:rc\.)?data\.location\s*=\s*(.*?)\s*$")
CONFIG_KEYS = {
    "paths": {"root", "tasks", "chains", "projects", "templates"},
    "editor": {"command", "show_diff_on_save", "diff_color", "post_save_actions"},
    "display": {"color", "default_format"},
    "nautical": {"enabled"},
    "timewarrior": {"enabled"},
    "ops": {"max_entries", "keep_entries"},
}


def _expand_path(raw: str | None, fallback: Path) -> Path:
    text = str(raw or "").strip()
    if not text:
        return fallback
    return Path(text).expanduser().resolve()


def _read_config_file(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        data = tomllib.load(handle) or {}
    return data if isinstance(data, dict) else {}


def _config_bool(value: object, default: bool, *, key: str) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().casefold()
    if text in {"1", "yes", "true", "on"}:
        return True
    if text in {"0", "no", "false", "off"}:
        return False
    raise RuntimeError(f"invalid {key} value '{value}'; expected a boolean")


def _config_choice(value: object, default: str, *, key: str, allowed: set[str]) -> str:
    normalized = str(default if value is None else value).strip().casefold()
    if normalized not in allowed:
        choices = ", ".join(sorted(allowed))
        raise RuntimeError(f"invalid {key} value '{value}'; expected one of: {choices}")
    return normalized


def _config_int(value: object, default: int, *, key: str, minimum: int = 0) -> int:
    if value is None:
        return default
    try:
        parsed = int(str(value).strip())
    except ValueError as exc:
        raise RuntimeError(f"invalid {key} value '{value}'; expected an integer") from exc
    if parsed < minimum:
        raise RuntimeError(f"invalid {key} value '{value}'; expected at least {minimum}")
    return parsed


def _taskdata_root() -> Path:
    taskdata = str(os.environ.get("TASKDATA") or "").strip()
    if taskdata:
        return Path(taskdata).expanduser().resolve()

    taskrc = Path(str(os.environ.get("TASKRC") or "~/.taskrc")).expanduser()
    if taskrc.exists():
        try:
            for line in taskrc.read_text(encoding="utf-8").splitlines():
                text = line.split("#", 1)[0].strip()
                if not text:
                    continue
                match = TASKRC_DATA_RE.match(text)
                if match:
                    raw = match.group(1).strip().strip('"').strip("'")
                    if raw:
                        return Path(raw).expanduser().resolve()
        except OSError:
            pass

    return DEFAULT_TASKDATA.resolve()


def load_config() -> AppConfig:
    default_root = _expand_path(os.environ.get("JOT_HOME"), _taskdata_root() / "jot")
    config_path = _expand_path(os.environ.get("JOT_CONFIG"), default_root / DEFAULT_CONFIG_NAME)
    data = _read_config_file(config_path)
    _validate_config_shape(data)

    paths_cfg = data.get("paths") if isinstance(data.get("paths"), dict) else {}
    editor_cfg = data.get("editor") if isinstance(data.get("editor"), dict) else {}
    display_cfg = data.get("display") if isinstance(data.get("display"), dict) else {}
    nautical_cfg = data.get("nautical") if isinstance(data.get("nautical"), dict) else {}
    timewarrior_cfg = data.get("timewarrior") if isinstance(data.get("timewarrior"), dict) else {}
    ops_cfg = data.get("ops") if isinstance(data.get("ops"), dict) else {}

    root_dir = _expand_path(paths_cfg.get("root"), default_root)
    trash_dir = root_dir / ".jot_trash"
    tasks_dir = _expand_path(paths_cfg.get("tasks"), root_dir / "tasks")
    chains_dir = _expand_path(paths_cfg.get("chains"), root_dir / "chains")
    projects_dir = _expand_path(paths_cfg.get("projects"), root_dir / "projects")
    templates_dir = _expand_path(paths_cfg.get("templates"), root_dir / "templates")

    editor_command = str(editor_cfg.get("command") or os.environ.get("EDITOR") or "vim").strip()
    editor_show_diff_on_save = _config_bool(
        editor_cfg.get("show_diff_on_save"), True, key="editor.show_diff_on_save"
    )
    editor_diff_color = _config_choice(
        editor_cfg.get("diff_color"),
        "auto",
        key="editor.diff_color",
        allowed={"auto", "always", "never"},
    )
    editor_post_save_actions = _config_bool(
        editor_cfg.get("post_save_actions"), True, key="editor.post_save_actions"
    )
    color_mode = _config_choice(
        display_cfg.get("color"),
        "auto",
        key="display.color",
        allowed={"auto", "always", "never"},
    )
    default_format = _config_choice(
        display_cfg.get("default_format"),
        "text",
        key="display.default_format",
        allowed={"json", "text"},
    )
    nautical_enabled = _config_bool(nautical_cfg.get("enabled"), True, key="nautical.enabled")
    timewarrior_enabled = _config_bool(
        timewarrior_cfg.get("enabled"), True, key="timewarrior.enabled"
    )
    ops_max_entries = _config_int(ops_cfg.get("max_entries"), 10000, key="ops.max_entries")
    ops_keep_entries = _config_int(ops_cfg.get("keep_entries"), 5000, key="ops.keep_entries")
    if ops_max_entries and ops_keep_entries > ops_max_entries:
        raise RuntimeError("ops.keep_entries cannot exceed ops.max_entries")

    return AppConfig(
        config_path=config_path,
        root_dir=root_dir,
        trash_dir=trash_dir,
        tasks_dir=tasks_dir,
        chains_dir=chains_dir,
        projects_dir=projects_dir,
        templates_dir=templates_dir,
        editor_command=editor_command,
        editor_show_diff_on_save=editor_show_diff_on_save,
        editor_diff_color=editor_diff_color,
        editor_post_save_actions=editor_post_save_actions,
        color_mode=color_mode,
        default_format=default_format,
        nautical_enabled=nautical_enabled,
        timewarrior_enabled=timewarrior_enabled,
        ops_max_entries=ops_max_entries,
        ops_keep_entries=ops_keep_entries,
    )


def ensure_app_dirs(config: AppConfig) -> None:
    for path in (
        config.root_dir,
        config.trash_dir,
        config.tasks_dir,
        config.chains_dir,
        config.projects_dir,
        config.templates_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)


def _validate_config_shape(data: dict) -> None:
    unknown_sections = sorted(set(data) - set(CONFIG_KEYS))
    if unknown_sections:
        names = ", ".join(unknown_sections)
        raise RuntimeError(f"unknown config section(s): {names}")
    for section, allowed_keys in CONFIG_KEYS.items():
        if section not in data:
            continue
        value = data[section]
        if not isinstance(value, dict):
            raise RuntimeError(f"config section '{section}' must be a table")
        unknown_keys = sorted(set(value) - allowed_keys)
        if unknown_keys:
            names = ", ".join(f"{section}.{key}" for key in unknown_keys)
            raise RuntimeError(f"unknown config key(s): {names}")
