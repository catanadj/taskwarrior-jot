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
    example: str
    arguments: tuple[str, ...]


COMMAND_EXAMPLES = {
    "add": "jot add --type status 42 waiting on vendor",
    "export": "jot --json export 42",
    "list": "jot list 42",
    "note": "jot note 42",
    "note-append": "jot note-append 42 \"Vendor confirmed delivery\"",
    "show": "jot show 42",
    "task-cat": "jot task-cat 42",
    "task-delete": "jot task-delete 42",
    "chain": "jot chain 42",
    "chain-append": "jot chain-append 42 \"Skip public holidays\"",
    "chain-cat": "jot chain-cat 42",
    "chain-delete": "jot chain-delete 42",
    "project": "jot project Finances.Expense",
    "project-append": "jot project-append Finances.Expense \"Policy review pending\"",
    "project-cat": "jot project-cat Finances.Expense",
    "project-delete": "jot project-delete Finances.Expense",
    "project-list": "jot project-list",
    "project-report": "jot project-report Finances.Expense --limit 10",
    "project-show": "jot project-show Finances.Expense",
    "add-to": 'jot add-to task 42 --heading "Next steps" --text "Call vendor"',
    "headings": "jot headings task 42",
    "progress add": "jot progress task 42 add 1 --track chest",
    "progress clear": "jot progress task 42 clear --track chest --yes",
    "progress set": "jot progress task 42 set 3/12 --track chest --unit sets --status active",
    "progress show": "jot progress task 42 show",
    "progress status": "jot progress task 42 status paused --track chest",
    "progress subtract": "jot progress task 42 subtract 1 --track chest",
    "section": 'jot section task 42 "Next steps"',
    "attach": "jot attach task 42 ~/documents/invoice.pdf --label invoice",
    "detach-resource": "jot detach-resource task 42 1",
    "open-resource": "jot open-resource task 42 1",
    "resources": "jot resources task 42",
    "report recent": "jot report recent --limit 10 --kind event",
    "search": "jot search vendor --kind task-note",
    "tui": "jot tui",
    "doctor": "jot doctor",
    "paths": "jot paths",
    "rebuild-index": "jot rebuild-index",
    "stats": "jot stats",
    "trash-list": "jot trash-list",
    "trash-restore": "jot trash-restore 1",
}


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
        example=COMMAND_EXAMPLES.get(name, ""),
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
