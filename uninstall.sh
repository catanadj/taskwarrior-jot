#!/usr/bin/env bash

set -euo pipefail

PREFIX="${PREFIX:-$HOME/.local}"
BIN_DIR="$PREFIX/bin"
LIB_DIR="$PREFIX/lib/jot"
REMOVE_TIMELOG_HOOK="no"

resolve_taskdata_dir() {
  if [[ -n "${TASKDATA:-}" ]]; then
    printf '%s\n' "$TASKDATA"
    return
  fi
  local taskrc="${TASKRC:-$HOME/.taskrc}"
  if [[ -f "$taskrc" ]]; then
    local line value
    while IFS= read -r line; do
      line="${line%%#*}"
      line="${line#"${line%%[![:space:]]*}"}"
      line="${line%"${line##*[![:space:]]}"}"
      case "$line" in
        data.location=*|data.location\ =*|rc.data.location=*|rc.data.location\ =*)
          value="${line#*=}"
          value="${value#"${value%%[![:space:]]*}"}"
          value="${value%"${value##*[![:space:]]}"}"
          value="${value%\"}"; value="${value#\"}"
          value="${value%\'}"; value="${value#\'}"
          if [[ -n "$value" ]]; then
            printf '%s\n' "$value"
            return
          fi
          ;;
      esac
    done < "$taskrc"
  fi
  printf '%s\n' "$HOME/.task"
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

TASKDATA_DIR="$(resolve_taskdata_dir)"
TASKDATA_DIR="${TASKDATA_DIR/#\~/$HOME}"
TIMELOG_HOOK_SRC="$LIB_DIR/hooks/on-modify_jot_timelog.py"
TIMELOG_HOOK_DST="$TASKDATA_DIR/hooks/on-modify_jot_timelog.py"
if [[ "$REMOVE_TIMELOG_HOOK" == "yes" && -e "$TIMELOG_HOOK_DST" ]]; then
  if [[ -f "$TIMELOG_HOOK_SRC" ]] && cmp -s "$TIMELOG_HOOK_SRC" "$TIMELOG_HOOK_DST"; then
    rm -f "$TIMELOG_HOOK_DST"
    echo "Removed Jot Taskwarrior hook: $TIMELOG_HOOK_DST"
  else
    echo "Kept Taskwarrior hook because it does not match this Jot installation: $TIMELOG_HOOK_DST"
  fi
fi

rm -rf "$LIB_DIR/jot_core" "$LIB_DIR/jot_tui" "$LIB_DIR/hooks" "$LIB_DIR/templates"
rm -f "$LIB_DIR/jot" "$LIB_DIR/config-jot.toml"
rmdir "$LIB_DIR" 2>/dev/null || true

cat <<EOF
Removed:
  $BIN_DIR/jot
  $LIB_DIR
EOF
