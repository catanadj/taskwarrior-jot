#!/usr/bin/env python3
"""Check that release-facing version metadata agrees."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


PACKAGE_VERSION_RE = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']\s*$', re.MULTILINE)
BOOTSTRAP_VERSION_RE = re.compile(
    r'^VERSION="\$\{JOT_VERSION:-v([^"}]+)\}"\s*$', re.MULTILINE
)
RELEASE_REF_RE = re.compile(r"^v(.+)$")


def _read_version(path: Path, pattern: re.Pattern[str], label: str) -> str:
    text = path.read_text(encoding="utf-8")
    match = pattern.search(text)
    if match is None:
        raise ValueError(f"could not find {label} in {path}")
    return match.group(1)


def validate_metadata(
    package_file: Path, bootstrap_file: Path, ref_name: str | None = None
) -> list[str]:
    """Return human-readable metadata mismatches."""
    errors: list[str] = []
    try:
        package_version = _read_version(
            package_file, PACKAGE_VERSION_RE, "package version"
        )
    except (OSError, ValueError) as exc:
        errors.append(str(exc))
        package_version = ""

    try:
        bootstrap_version = _read_version(
            bootstrap_file, BOOTSTRAP_VERSION_RE, "bootstrap version"
        )
    except (OSError, ValueError) as exc:
        errors.append(str(exc))
        bootstrap_version = ""

    if package_version and bootstrap_version and package_version != bootstrap_version:
        errors.append(
            "bootstrap default version "
            f"{bootstrap_version!r} does not match package version {package_version!r}"
        )

    if ref_name:
        release_match = RELEASE_REF_RE.fullmatch(ref_name)
        if release_match and package_version:
            release_version = release_match.group(1)
            if release_version != package_version:
                errors.append(
                    f"release ref {ref_name!r} does not match package version "
                    f"{package_version!r}"
                )

    return errors


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--package-file", type=Path, default=Path("jot_core/__init__.py")
    )
    parser.add_argument("--bootstrap-file", type=Path, default=Path("bootstrap.sh"))
    parser.add_argument(
        "--ref",
        default=None,
        help="branch or tag name; vX.Y.Z refs are checked against the package version",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        errors = validate_metadata(args.package_file, args.bootstrap_file, args.ref)
    except OSError as exc:
        print(f"release metadata check failed: {exc}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(f"release metadata check failed: {error}", file=sys.stderr)
        return 1
    print("release metadata is consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
