from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import string
import subprocess
import tomllib
from dataclasses import dataclass
from typing import Mapping, Sequence

from .models import AppConfig


DEFAULT_CONFIG_NAME = "config-jot.toml"
TASKRC_DATA_RE = re.compile(r"^\s*(?:rc\.)?data\.location\s*=\s*(.*?)\s*$")
TASKRC_HOOKS_RE = re.compile(r"^\s*(?:rc\.)?hooks\.location\s*=\s*(.*?)\s*$")
CONFIG_KEYS = {
    "paths": {"root", "tasks", "chains", "projects", "templates"},
    "editor": {"command", "show_diff_on_save", "diff_color", "post_save_actions"},
    "display": {"color", "default_format"},
    "nautical": {"enabled"},
    "timewarrior": {"enabled"},
    "ops": {"max_entries", "keep_entries"},
}


@dataclass(frozen=True, slots=True)
class TaskwarriorEnvironment:
    executable: str
    rc_path: Path
    rc_source: str
    data_path: Path
    hooks_path: Path
    warnings: tuple[str, ...] = ()

    @classmethod
    def resolve(
        cls,
        argv: Sequence[str] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> TaskwarriorEnvironment:
        environ = dict(os.environ if env is None else env)
        args = [str(value) for value in (argv or ())]
        executable = shutil.which("task", path=environ.get("PATH")) or "task"
        if args and not _is_environment_override(args[0]):
            executable = args.pop(0)

        warnings: list[str] = []
        rc_override = _last_override(args, ("rc:",), warnings)
        data_override = _last_override(
            args,
            ("data:", "data.location:", "rc.data.location:", "rc.data.location="),
            warnings,
        )
        hooks_override = _last_override(
            args,
            ("hooks:", "hooks.location:", "rc.hooks.location:", "rc.hooks.location="),
            warnings,
        )

        rc_path, rc_source = _resolve_taskrc(rc_override, environ)
        query_prefix = [f"rc:{rc_path}"]
        if data_override:
            query_prefix.append(f"rc.data.location={_resolved_path(data_override, environ)}")
        taskdata = str(environ.get("TASKDATA") or "").strip()
        queried_data = ""
        queried_hooks = ""
        if not data_override:
            queried_data = _query_taskwarrior(
                executable,
                query_prefix,
                "rc.data.location",
                environ,
                warnings,
            )
        if not hooks_override:
            queried_hooks = _query_taskwarrior(
                executable,
                query_prefix,
                "rc.hooks.location",
                environ,
                warnings,
            )

        rc_data = _read_taskrc_value(rc_path, TASKRC_DATA_RE, environ)
        rc_hooks = _read_taskrc_value(rc_path, TASKRC_HOOKS_RE, environ)
        xdg_selected = rc_source == "XDG_CONFIG_HOME"
        default_data = (
            _xdg_home(environ, "XDG_DATA_HOME", ".local/share") / "task"
            if xdg_selected
            else _home(environ) / ".task"
        )
        data_path = _resolved_path(
            data_override or taskdata or queried_data or rc_data,
            environ,
            default_data,
        )
        default_hooks = (
            _xdg_home(environ, "XDG_CONFIG_HOME", ".config") / "task" / "hooks"
            if xdg_selected
            else data_path / "hooks"
        )
        hooks_path = _resolved_path(
            hooks_override or queried_hooks or rc_hooks,
            environ,
            default_hooks,
        )
        return cls(
            executable=executable,
            rc_path=rc_path,
            rc_source=rc_source,
            data_path=data_path,
            hooks_path=hooks_path,
            warnings=tuple(warnings),
        )


def _is_environment_override(value: str) -> bool:
    return value.startswith(("rc:", "rc.", "data:", "data.location:", "hooks:"))


def _last_override(args: Sequence[str], prefixes: tuple[str, ...], warnings: list[str]) -> str:
    selected = ""
    for arg in args:
        prefix = next((item for item in prefixes if arg.startswith(item)), None)
        if prefix is None:
            continue
        value = arg[len(prefix) :].strip()
        if value:
            selected = value
        else:
            warnings.append(f"ignored empty Taskwarrior argument: {arg}")
    return selected


def _home(env: Mapping[str, str]) -> Path:
    return Path(str(env.get("HOME") or Path.home())).resolve()


def _xdg_home(env: Mapping[str, str], name: str, fallback: str) -> Path:
    raw = str(env.get(name) or "").strip()
    return _resolved_path(raw, env, _home(env) / fallback)


def _resolved_path(raw: str | Path, env: Mapping[str, str], fallback: Path | None = None) -> Path:
    text = string.Template(str(raw or "")).safe_substitute(env).strip().strip('"').strip("'")
    if not text:
        if fallback is None:
            return Path()
        return fallback.resolve()
    if text == "~":
        text = str(_home(env))
    elif text.startswith("~/"):
        text = str(_home(env) / text[2:])
    return Path(text).resolve()


def _resolve_taskrc(raw_override: str, env: Mapping[str, str]) -> tuple[Path, str]:
    if raw_override:
        return _resolved_path(raw_override, env), "argv"
    taskrc = str(env.get("TASKRC") or "").strip()
    if taskrc:
        return _resolved_path(taskrc, env), "TASKRC"
    legacy = _home(env) / ".taskrc"
    if legacy.exists():
        return legacy.resolve(), "legacy"
    xdg = _xdg_home(env, "XDG_CONFIG_HOME", ".config") / "task" / "taskrc"
    return xdg.resolve(), "XDG_CONFIG_HOME"


def _query_taskwarrior(
    executable: str,
    prefix: Sequence[str],
    key: str,
    env: Mapping[str, str],
    warnings: list[str],
) -> str:
    command = [executable, *prefix, "rc.hooks=off", "rc.verbose=nothing", "_get", key]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
            env=dict(env),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        warnings.append(f"could not query Taskwarrior {key}: {exc}")
        return ""
    if completed.returncode != 0:
        detail = (completed.stderr or "").strip()
        warnings.append(f"could not query Taskwarrior {key}" + (f": {detail}" if detail else ""))
        return ""
    return (completed.stdout or "").strip()


def _read_taskrc_value(path: Path, pattern: re.Pattern[str], env: Mapping[str, str]) -> str:
    if not path.exists():
        return ""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    selected = ""
    for line in lines:
        text = line.split("#", 1)[0].strip()
        match = pattern.match(text)
        if match:
            selected = string.Template(match.group(1).strip()).safe_substitute(env)
    return selected


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
    return TaskwarriorEnvironment.resolve().data_path


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
