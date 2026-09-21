"""Shell completion script generation for the Jot command tree."""

from __future__ import annotations

import argparse
import shlex


SUPPORTED_SHELLS = ("bash", "zsh", "fish")


def render_completion(shell: str, parser: argparse.ArgumentParser) -> str:
    """Render a dependency-free completion script for a supported shell."""
    normalized = str(shell).strip().casefold()
    if normalized not in SUPPORTED_SHELLS:
        choices = ", ".join(SUPPORTED_SHELLS)
        raise ValueError(f"unsupported shell '{shell}'; expected one of: {choices}")
    commands, options = _completion_tokens(parser)
    if normalized == "bash":
        return _render_bash(commands, options)
    if normalized == "zsh":
        return _render_zsh(commands, options)
    return _render_fish(commands, options)


def _completion_tokens(parser: argparse.ArgumentParser) -> tuple[tuple[str, ...], tuple[str, ...]]:
    commands: set[str] = set()
    options: set[str] = set()

    def visit(current: argparse.ArgumentParser) -> None:
        for action in current._actions:
            options.update(action.option_strings)
            if not isinstance(action, argparse._SubParsersAction):
                continue
            for name, child in action.choices.items():
                commands.add(str(name))
                visit(child)

    visit(parser)
    return tuple(sorted(commands)), tuple(sorted(options))


def _shell_words(values: tuple[str, ...]) -> str:
    return " ".join(shlex.quote(value) for value in values)


def _render_bash(commands: tuple[str, ...], options: tuple[str, ...]) -> str:
    return "\n".join(
        (
            "# Jot completion for Bash. Source this file or eval its output.",
            f"_jot_commands=({_shell_words(commands)})",
            f"_jot_options=({_shell_words(options)})",
            "_jot_completions() {",
            "  local cur=\"${COMP_WORDS[COMP_CWORD]}\"",
            "  COMPREPLY=( $(compgen -W \"${_jot_commands[*]} ${_jot_options[*]}\" -- \"$cur\") )",
            "}",
            "complete -F _jot_completions jot",
            "",
        )
    )


def _render_zsh(commands: tuple[str, ...], options: tuple[str, ...]) -> str:
    return "\n".join(
        (
            "# Jot completion for Zsh. Source this file or add it to your fpath.",
            f"_jot_commands=({_shell_words(commands)})",
            f"_jot_options=({_shell_words(options)})",
            "_jot() {",
            "  _describe 'command' _jot_commands",
            "  _describe 'option' _jot_options",
            "}",
            "compdef _jot jot",
            "",
        )
    )


def _render_fish(commands: tuple[str, ...], options: tuple[str, ...]) -> str:
    command_words = " ".join(commands)
    option_lines = "\n".join(
        f"complete -c jot -f -a {shlex.quote(option)}" for option in options
    )
    return "\n".join(
        (
            "# Jot completion for Fish. Save as ~/.config/fish/completions/jot.fish.",
            f"complete -c jot -f -n '__fish_use_subcommand' -a {shlex.quote(command_words)}",
            option_lines,
            "",
        )
    )
