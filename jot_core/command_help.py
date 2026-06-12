from __future__ import annotations

import argparse
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CommandHelp:
    name: str
    category: str
    summary: str
    description: str
    usage: str
    arguments: tuple[str, ...]


def build_command_catalog(parser: argparse.ArgumentParser) -> list[CommandHelp]:
    commands: list[CommandHelp] = []
    _collect_commands(parser, (), commands)
    return sorted(commands, key=lambda item: (_category_order(item.category), item.name))


def _collect_commands(
    parser: argparse.ArgumentParser,
    path: tuple[str, ...],
    commands: list[CommandHelp],
) -> None:
    subparsers = _subparser_action(parser)
    if subparsers is None:
        if path:
            commands.append(_command_help(parser, path))
        return

    for name, child in subparsers.choices.items():
        _collect_commands(child, (*path, name), commands)


def _command_help(parser: argparse.ArgumentParser, path: tuple[str, ...]) -> CommandHelp:
    name = " ".join(path)
    summary = _command_summary(parser)
    description = str(parser.description or summary).strip()
    return CommandHelp(
        name=name,
        category=_command_category(path),
        summary=summary,
        description=description,
        usage=_clean_usage(parser.format_usage()),
        arguments=tuple(_argument_lines(parser)),
    )


def _subparser_action(parser: argparse.ArgumentParser) -> argparse._SubParsersAction | None:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    return None


def _command_summary(parser: argparse.ArgumentParser) -> str:
    subparsers = _subparser_action(parser)
    if subparsers is not None:
        return str(parser.description or "").strip()
    return str(parser.description or "").strip().rstrip(".")


def _argument_lines(parser: argparse.ArgumentParser) -> list[str]:
    lines: list[str] = []
    for action in parser._actions:
        if action.help == argparse.SUPPRESS or isinstance(action, argparse._SubParsersAction):
            continue
        if action.dest == "help":
            continue
        if action.option_strings:
            label = ", ".join(action.option_strings)
            if action.nargs not in (0, None):
                label += f" {str(action.metavar or action.dest).upper()}"
        else:
            label = str(action.metavar or action.dest)
        help_text = str(action.help or "").strip()
        lines.append(f"{label}: {help_text}" if help_text else label)
    return lines


def _clean_usage(value: str) -> str:
    usage = " ".join(str(value or "").strip().split())
    return usage.removeprefix("usage: ")


def _command_category(path: tuple[str, ...]) -> str:
    name = path[0]
    if name in {"note", "note-append", "task-cat", "task-delete", "show", "list", "export", "add"}:
        return "Tasks"
    if name in {"chain", "chain-append", "chain-cat", "chain-delete"}:
        return "Chains"
    if name.startswith("project"):
        return "Projects"
    if name in {"attach", "resources", "open-resource", "detach-resource"}:
        return "Resources"
    if name in {"add-to", "headings", "section", "progress"}:
        return "Notes"
    if name in {"search", "report"}:
        return "Search & Reports"
    if name == "tui":
        return "Interface"
    return "Maintenance"


def _category_order(category: str) -> int:
    categories = (
        "Tasks",
        "Chains",
        "Projects",
        "Notes",
        "Resources",
        "Search & Reports",
        "Interface",
        "Maintenance",
    )
    try:
        return categories.index(category)
    except ValueError:
        return len(categories)
