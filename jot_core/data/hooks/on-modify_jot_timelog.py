#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys


def _diagnostic(message: str) -> None:
    if os.environ.get("NAUTICAL_DIAG") == "1":
        sys.stderr.write(message)


def _taskdata_from_args(args: list[str]) -> str:
    selected = ""
    for arg in args:
        for prefix in ("data:", "data.location:"):
            if not arg.startswith(prefix):
                continue
            value = arg[len(prefix) :].strip()
            if value:
                selected = value
            else:
                _diagnostic(f"jot timelog hook warning: ignored empty data argument: {arg}\n")
            break
    return selected


def main() -> int:
    old_line = sys.stdin.readline()
    new_line = sys.stdin.readline()
    if not old_line or not new_line:
        return 0

    jot_bin = os.environ.get("JOT_BIN", "jot")
    child_env = os.environ.copy()
    taskdata = _taskdata_from_args(sys.argv[1:])
    if taskdata:
        child_env["TASKDATA"] = taskdata
    return_code = 0
    try:
        completed = subprocess.run(
            [jot_bin, "--json", "timelog", "ingest"],
            input=old_line + new_line,
            text=True,
            capture_output=True,
            check=False,
            timeout=_timeout_seconds(),
            env=child_env,
        )
        if completed.stderr:
            _diagnostic(completed.stderr)
        if completed.returncode != 0:
            _diagnostic(
                f"jot timelog hook warning: ingest failed with exit {completed.returncode}\n"
            )
            return_code = completed.returncode
    except subprocess.TimeoutExpired:
        _diagnostic("jot timelog hook warning: ingest timed out\n")
        return_code = 1
    except OSError as exc:
        _diagnostic(f"jot timelog hook warning: could not run jot: {exc}\n")
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
