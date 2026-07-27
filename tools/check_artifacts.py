from __future__ import annotations

from pathlib import Path
import sys
import tarfile
import zipfile


REQUIRED_SUFFIXES = (
    "jot_core/data/config-jot.toml",
    "jot_core/data/templates/task-note.md",
    "jot_core/data/templates/chain-note.md",
    "jot_core/data/templates/project-note.md",
    "jot_core/data/hooks/on-modify_jot_timelog.py",
)
REQUIRED_SOURCE_FILES = (
    "config-jot.toml",
    "templates/task-note.md",
    "templates/chain-note.md",
    "templates/project-note.md",
    "hooks/on-modify_jot_timelog.py",
)


def main(argv: list[str] | None = None) -> int:
    dist_dir = Path((argv or sys.argv[1:] or ["dist"])[0])
    artifacts = sorted(path for path in dist_dir.iterdir() if path.is_file())
    wheels = [path for path in artifacts if path.suffix == ".whl"]
    sdists = [path for path in artifacts if path.name.endswith(".tar.gz")]
    errors: list[str] = []

    if len(wheels) != 1:
        errors.append(f"expected exactly one wheel in {dist_dir}, found {len(wheels)}")
    else:
        errors.extend(_missing_wheel_files(wheels[0]))
    if len(sdists) != 1:
        errors.append(f"expected exactly one source archive in {dist_dir}, found {len(sdists)}")
    else:
        errors.extend(_missing_sdist_files(sdists[0]))

    if errors:
        for error in errors:
            print(f"artifact check: {error}", file=sys.stderr)
        return 1
    print(f"artifact check: validated {wheels[0].name} and {sdists[0].name}")
    return 0


def _missing_wheel_files(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
    return [
        f"{path.name} is missing {suffix}"
        for suffix in REQUIRED_SUFFIXES
        if not any(name.endswith(suffix) for name in names)
    ]


def _missing_sdist_files(path: Path) -> list[str]:
    with tarfile.open(path, "r:gz") as archive:
        names = archive.getnames()
    return [
        f"{path.name} is missing {suffix}"
        for suffix in REQUIRED_SOURCE_FILES
        if not any(name.endswith(suffix) for name in names)
    ]


if __name__ == "__main__":
    raise SystemExit(main())
