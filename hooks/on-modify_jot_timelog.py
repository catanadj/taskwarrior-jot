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
    return_code = 0
    try:
        completed = subprocess.run(
            [jot_bin, "--json", "timelog", "ingest"],
            input=old_line + new_line,
            text=True,
            capture_output=True,
            check=False,
            timeout=_timeout_seconds(),
        )
        if completed.stderr:
            sys.stderr.write(completed.stderr)
        if completed.returncode != 0:
            sys.stderr.write(f"jot timelog hook warning: ingest failed with exit {completed.returncode}\n")
            return_code = completed.returncode
    except subprocess.TimeoutExpired:
        sys.stderr.write("jot timelog hook warning: ingest timed out\n")
        return_code = 1
    except OSError as exc:
        sys.stderr.write(f"jot timelog hook warning: could not run jot: {exc}\n")
        return_code = 1

    sys.stdout.write(new_line)
    if return_code and os.environ.get("JOT_TIMELOG_STRICT") == "1":
        return return_code
    return 0


def _timeout_seconds() -> float:
    raw = str(os.environ.get("JOT_TIMELOG_TIMEOUT") or "10").strip()
    try:
        value = float(raw)
    except ValueError:
        return 10.0
    return value if value > 0 else 10.0


if __name__ == "__main__":
    raise SystemExit(main())
