from __future__ import annotations

import sys

from jot_core.app import build_app_context
from jot_core.command_help import build_command_catalog
from jot_core.command_prefix import AmbiguousCommandPrefix, expand_command_prefixes
from jot_core.config import ensure_app_dirs
from jot_core.output import configure_output, warn
from jot_core.services import JotService
from jot_core import cli as core_cli


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        return _run_command_browser()

    try:
        expanded = expand_command_prefixes(core_cli.build_parser(), args)
    except AmbiguousCommandPrefix:
        return core_cli.main(args)
    if expanded and expanded[0] == "tui":
        return _run_tui()
    return core_cli.main(args)


def _run_command_browser() -> int:
    try:
        from .command_browser import run_command_browser

        return run_command_browser(build_command_catalog(core_cli.build_parser()))
    except RuntimeError:
        return core_cli.main([])


def _run_tui() -> int:
    try:
        from .app import run_tui

        ctx = build_app_context()
        ensure_app_dirs(ctx.config)
        configure_output(color_mode=ctx.config.color_mode)
        return run_tui(JotService(config=ctx.config, taskwarrior=ctx.taskwarrior))
    except Exception as exc:
        warn(f"failed to load TUI: {exc}")
        return 1
