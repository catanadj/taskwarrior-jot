#!/usr/bin/env bash

set -euo pipefail

PREFIX="${PREFIX:-$HOME/.local}"
BIN_DIR="$PREFIX/bin"
LIB_DIR="$PREFIX/lib/jot"
REMOVE_TIMELOG_HOOK="no"

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "error: jot requires Python 3.11 or newer" >&2
  exit 1
fi

resolve_taskwarrior_environment() {
  PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}" python3 - <<'PY'
import sys

from jot_core.config import TaskwarriorEnvironment

resolved = TaskwarriorEnvironment.resolve()
print(resolved.data_path)
print(resolved.hooks_path)
for warning in resolved.warnings:
    print(f"warning: {warning}", file=sys.stderr)
PY
}

usage() {
  cat <<'EOF'
Usage: ./uninstall.sh [--prefix DIR] [--remove-timelog-hook]

Removes the non-pip jot installation created by install.sh. Jot data and
configuration are preserved. Taskwarrior hooks are preserved unless explicitly
requested and still match the installed Jot hook.
EOF
}

while (($#)); do
  case "$1" in
    --prefix)
      if (($# < 2)); then
        echo "error: --prefix requires a directory" >&2
        exit 2
      fi
      PREFIX="$2"
      BIN_DIR="$PREFIX/bin"
      LIB_DIR="$PREFIX/lib/jot"
      shift 2
      ;;
    --remove-timelog-hook)
      REMOVE_TIMELOG_HOOK="yes"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -L "$BIN_DIR/jot" ]]; then
  if [[ "$(readlink "$BIN_DIR/jot")" == "$LIB_DIR/jot" ]]; then
    rm -f "$BIN_DIR/jot"
  else
    echo "Kept unrelated symlink: $BIN_DIR/jot"
  fi
elif [[ -e "$BIN_DIR/jot" ]]; then
  echo "Kept non-Jot file: $BIN_DIR/jot"
fi

mapfile -t TASK_ENVIRONMENT < <(resolve_taskwarrior_environment)
if [[ "${#TASK_ENVIRONMENT[@]}" -lt 2 ]]; then
  echo "error: could not resolve the Taskwarrior environment" >&2
  exit 1
fi
TASKDATA_DIR="${TASK_ENVIRONMENT[0]}"
TASK_HOOKS_DIR="${TASK_ENVIRONMENT[1]}"
TIMELOG_HOOK_SRC="$LIB_DIR/current/hooks/on-modify_jot_timelog.py"
if [[ ! -f "$TIMELOG_HOOK_SRC" ]]; then
  TIMELOG_HOOK_SRC="$LIB_DIR/hooks/on-modify_jot_timelog.py"
fi
TIMELOG_HOOK_DST="$TASK_HOOKS_DIR/on-modify_jot_timelog.py"
if [[ "$REMOVE_TIMELOG_HOOK" == "yes" && -e "$TIMELOG_HOOK_DST" ]]; then
  if [[ -f "$TIMELOG_HOOK_SRC" ]] && cmp -s "$TIMELOG_HOOK_SRC" "$TIMELOG_HOOK_DST"; then
    rm -f "$TIMELOG_HOOK_DST"
    echo "Removed Jot Taskwarrior hook: $TIMELOG_HOOK_DST"
  else
    echo "Kept Taskwarrior hook because it does not match this Jot installation: $TIMELOG_HOOK_DST"
  fi
fi

rm -rf "$LIB_DIR"

cat <<EOF
Removed:
  $BIN_DIR/jot
  $LIB_DIR
EOF
