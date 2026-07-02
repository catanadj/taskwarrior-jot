#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys


def main() -> int:
    old_line = sys.stdin.readline()
    new_line = sys.stdin.readline()
    if not old_line or not new_line:
        return 0

    jot_bin = os.environ.get("JOT_BIN", "jot")
    completed = subprocess.run(
        [jot_bin, "--json", "timelog", "ingest"],
        input=old_line + new_line,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.stderr:
        sys.stderr.write(completed.stderr)
    if completed.returncode != 0:
        sys.stderr.write(f"jot timelog hook warning: ingest failed with exit {completed.returncode}\n")
        if os.environ.get("JOT_TIMELOG_STRICT") == "1":
            return completed.returncode

    sys.stdout.write(new_line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
