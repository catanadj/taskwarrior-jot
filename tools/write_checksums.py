"""Write a deterministic SHA-256 manifest for Jot distribution artifacts."""

from __future__ import annotations

import hashlib
from pathlib import Path
import os
import sys
import tempfile


ARTIFACT_SUFFIXES = (".whl", ".tar.gz")
MANIFEST_NAME = "SHA256SUMS"


def write_checksums(dist_dir: Path) -> Path:
    artifacts = sorted(
        path
        for path in dist_dir.iterdir()
        if path.is_file() and path.name.endswith(ARTIFACT_SUFFIXES)
    )
    if not artifacts:
        raise ValueError(f"no distribution artifacts found in {dist_dir}")

    lines = []
    for artifact in artifacts:
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        lines.append(f"{digest}  {artifact.name}")

    manifest = dist_dir / MANIFEST_NAME
    fd, temporary_name = tempfile.mkstemp(prefix=f".{MANIFEST_NAME}.", dir=dist_dir)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as handle:
            handle.write("\n".join(lines) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, manifest)
    except BaseException:
        os.unlink(temporary_name)
        raise
    return manifest


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    dist_dir = Path(arguments[0] if arguments else "dist")
    try:
        manifest = write_checksums(dist_dir)
    except (OSError, ValueError) as exc:
        print(f"checksum generation: {exc}", file=sys.stderr)
        return 1
    print(f"checksum generation: wrote {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
