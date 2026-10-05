"""Runtime checks for the optional Textual and Rich interface."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version as package_version
from typing import Any


RICH_API_REQUIRED_BY_TEXTUAL = "clear_meta_and_links"


@dataclass(frozen=True, slots=True)
class TuiDependencyStatus:
    available: bool
    compatible: bool
    detail: str

    @property
    def ready(self) -> bool:
        return self.available and self.compatible


def tui_dependency_status() -> TuiDependencyStatus:
    """Return whether the installed optional TUI dependencies can render safely."""
    try:
        import_module("textual")
    except ModuleNotFoundError as exc:
        if exc.name == "textual":
            return TuiDependencyStatus(
                available=False,
                compatible=True,
                detail=f"optional Textual/Rich dependencies missing; install with {_install_hint()} to use `jot tui`",
            )
        if exc.name and exc.name.split(".", 1)[0] == "rich":
            return TuiDependencyStatus(
                available=False,
                compatible=False,
                detail=f"Textual is installed but Rich is missing; install with {_install_hint()}",
            )
        return TuiDependencyStatus(False, False, f"Textual could not load its dependencies: {exc}")
    except Exception as exc:
        return TuiDependencyStatus(False, False, f"Textual could not be imported: {exc}")

    try:
        style: Any = import_module("rich.style").Style
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.split(".", 1)[0] == "rich":
            return TuiDependencyStatus(
                False,
                False,
                f"Textual is installed but Rich is missing; install with {_install_hint()}",
            )
        return TuiDependencyStatus(
            False,
            False,
            f"Rich could not be imported: {exc}; install compatible Textual and Rich versions",
        )
    except Exception as exc:
        return TuiDependencyStatus(False, False, f"Rich could not be imported ({exc}); install with {_install_hint()}")

    textual_version = _installed_version("textual")
    rich_version = _installed_version("rich")
    versions = f"Textual {textual_version}, Rich {rich_version}"
    if not callable(getattr(style, RICH_API_REQUIRED_BY_TEXTUAL, None)):
        return TuiDependencyStatus(
            False,
            False,
            f"incompatible TUI dependencies ({versions}); update with {_install_hint()}",
        )
    return TuiDependencyStatus(True, True, f"{versions}; required Rich rendering API available")


def _installed_version(distribution: str) -> str:
    try:
        return package_version(distribution)
    except PackageNotFoundError:
        return "unknown version"


def _install_hint() -> str:
    return "`python3 -m pip install --upgrade 'textual>=0.50.1' 'rich>=13.3.5'`"


def main() -> int:
    """Print a concise status for installer use."""
    status = tui_dependency_status()
    print(status.detail)
    return 0 if status.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
