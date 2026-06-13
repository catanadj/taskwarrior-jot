from __future__ import annotations

import argparse
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AmbiguousCommandPrefix(ValueError):
    prefix: str
    matches: tuple[str, ...]

    def __str__(self) -> str:
        return f"ambiguous command '{self.prefix}': {', '.join(self.matches)}"


def expand_command_prefixes(parser: argparse.ArgumentParser, argv: list[str]) -> list[str]:
    """Expand minimum-unique command prefixes without changing argument values."""
    expanded = list(argv)
    command_index = _first_command_index(expanded)
    if command_index is None:
        return expanded

    current_parser = parser
    while command_index < len(expanded):
        subparsers = _subparser_action(current_parser)
        if subparsers is None:
            break

        command = _resolve_prefix(expanded[command_index], tuple(subparsers.choices))
        if command is None:
            break
        expanded[command_index] = command
        current_parser = subparsers.choices[command]

        nested_offset = _fixed_positionals_before_subparser(current_parser)
        if nested_offset is None:
            break
        command_index += 1 + nested_offset

    return expanded


def _resolve_prefix(value: str, choices: tuple[str, ...]) -> str | None:
    if value in choices:
        return value
    matches = tuple(sorted(choice for choice in choices if _is_prefix(value, choice)))
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise AmbiguousCommandPrefix(value, matches)
    return None


def _is_prefix(value: str, choice: str) -> bool:
    if "-" not in value:
        return choice.startswith(value)
    value_parts = value.split("-")
    choice_parts = choice.split("-")
    return len(value_parts) == len(choice_parts) and all(
        choice_part.startswith(value_part)
        for value_part, choice_part in zip(value_parts, choice_parts)
    )


def _first_command_index(argv: list[str]) -> int | None:
    for index, value in enumerate(argv):
        if value == "--":
            return index + 1 if index + 1 < len(argv) else None
        if not value.startswith("-"):
            return index
    return None


def _fixed_positionals_before_subparser(parser: argparse.ArgumentParser) -> int | None:
    count = 0
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return count
        if action.option_strings or action.dest == "help":
            continue
        if action.nargs is None:
            count += 1
            continue
        if isinstance(action.nargs, int):
            count += action.nargs
            continue
        return None
    return None


def _subparser_action(parser: argparse.ArgumentParser) -> argparse._SubParsersAction | None:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    return None
