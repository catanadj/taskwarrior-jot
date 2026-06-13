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

        nested_offset, has_nested_command = _expand_fixed_positionals(
            current_parser,
            expanded,
            command_index + 1,
        )
        if not has_nested_command:
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


def _expand_fixed_positionals(
    parser: argparse.ArgumentParser,
    argv: list[str],
    start_index: int,
) -> tuple[int, bool]:
    count = 0
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return count, True
        if action.option_strings or action.dest == "help":
            continue
        if action.nargs is None:
            action_count = 1
        elif isinstance(action.nargs, int):
            action_count = action.nargs
        else:
            return count, False
        if action.choices and action_count == 1 and start_index + count < len(argv):
            value = argv[start_index + count]
            choices = tuple(str(choice) for choice in action.choices)
            resolved = _resolve_prefix(value, choices)
            if resolved is not None:
                argv[start_index + count] = resolved
        count += action_count
    return count, False


def _subparser_action(parser: argparse.ArgumentParser) -> argparse._SubParsersAction | None:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    return None
