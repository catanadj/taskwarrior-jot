#!/usr/bin/env bash

set -euo pipefail

PREFIX="${PREFIX:-$HOME/.local}"
BIN_DIR="$PREFIX/bin"
LIB_DIR="$PREFIX/lib/jot"
INSTALL_TIMELOG_HOOK="ask"
REPLACE_TIMELOG_HOOK="no"

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="$SCRIPT_DIR/jot_core/data"

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

mapfile -t TASK_ENVIRONMENT < <(resolve_taskwarrior_environment)
if [[ "${#TASK_ENVIRONMENT[@]}" -lt 2 ]]; then
  echo "error: could not resolve the Taskwarrior environment" >&2
  exit 1
fi
TASKDATA_DIR="${TASK_ENVIRONMENT[0]}"
TASK_HOOKS_DIR="${TASK_ENVIRONMENT[1]}"
CONFIG_DIR="${JOT_HOME:-$TASKDATA_DIR/jot}"
CONFIG_PATH="$CONFIG_DIR/config-jot.toml"
TEMPLATES_DIR="$CONFIG_DIR/templates"

usage() {
  cat <<'EOF'
Usage: ./install.sh [--prefix DIR] [--with-timelog-hook|--no-timelog-hook]
                  [--replace-timelog-hook]

Installs jot without pip by copying the launcher and jot_core package into:
  <prefix>/lib/jot

and creating:
  <prefix>/bin/jot -> <prefix>/lib/jot/jot

Also installs a default config at:
  <task-data-dir>/jot/config-jot.toml
if that file does not already exist.

Default prefix:
  ~/.local

Task data and hooks directories are resolved from the effective Taskwarrior
environment, including TASKDATA, TASKRC, XDG paths, and taskrc settings.
Set JOT_HOME to override the jot data directory.

Timelog hook:
  --with-timelog-hook  copy the Jot time expenditure hook into Taskwarrior hooks
  --no-timelog-hook    do not prompt; leave the hook packaged but disabled
  --replace-timelog-hook
                       replace a different existing hook at the same path
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
    --with-timelog-hook)
      INSTALL_TIMELOG_HOOK="yes"
      shift
      ;;
    --no-timelog-hook)
      INSTALL_TIMELOG_HOOK="no"
      shift
      ;;
    --replace-timelog-hook)
      REPLACE_TIMELOG_HOOK="yes"
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

should_install_timelog_hook() {
  case "$INSTALL_TIMELOG_HOOK" in
    yes)
      return 0
      ;;
    no)
      return 1
      ;;
  esac

  if [[ ! -t 0 ]]; then
    return 1
  fi

  local answer
  printf 'Install Taskwarrior time expenditure hook? [y/N] '
  read -r answer
  case "$answer" in
    y|Y|yes|YES|Yes)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

mkdir -p "$BIN_DIR"
mkdir -p "$CONFIG_DIR"
mkdir -p "$TEMPLATES_DIR"

for required in \
  "$SCRIPT_DIR/jot" \
  "$DATA_DIR/config-jot.toml" \
  "$DATA_DIR/hooks/on-modify_jot_timelog.py" \
  "$DATA_DIR/templates/task-note.md" \
  "$DATA_DIR/templates/chain-note.md" \
  "$DATA_DIR/templates/project-note.md"; do
  if [[ ! -f "$required" ]]; then
    echo "error: required installation file is missing: $required" >&2
    exit 1
  fi
done

STAGE_DIR="$(mktemp -d "$PREFIX/.jot-install.XXXXXX")"
RUNTIME_DIR=""
ACTIVATION_TMP=""
cleanup_install() {
  rm -rf "$STAGE_DIR"
  if [[ -n "$ACTIVATION_TMP" ]]; then
    rm -f "$ACTIVATION_TMP"
  fi
  if [[ -n "$RUNTIME_DIR" && -e "$RUNTIME_DIR/.jot-installing" ]]; then
    if [[ ! -L "$LIB_DIR/current" || "$(readlink -f "$LIB_DIR/current")" != "$(readlink -f "$RUNTIME_DIR")" ]]; then
      rm -rf "$RUNTIME_DIR"
    fi
  fi
}
trap cleanup_install EXIT HUP INT TERM

install -m 755 "$SCRIPT_DIR/jot" "$STAGE_DIR/jot"
tar -C "$SCRIPT_DIR" \
  --exclude='jot_core/__pycache__' \
  --exclude='jot_core/*.pyc' \
  --exclude='jot_core/**/*.pyc' \
  --exclude='jot_tui/__pycache__' \
  --exclude='jot_tui/*.pyc' \
  --exclude='jot_tui/**/*.pyc' \
  -cf - jot_core jot_tui | tar -C "$STAGE_DIR" -xf -
install -m 644 "$DATA_DIR/config-jot.toml" "$STAGE_DIR/config-jot.toml"
mkdir -p "$STAGE_DIR/templates"
cp -R "$DATA_DIR/templates/." "$STAGE_DIR/templates/"
mkdir -p "$STAGE_DIR/hooks"
install -m 755 "$DATA_DIR/hooks/on-modify_jot_timelog.py" "$STAGE_DIR/hooks/on-modify_jot_timelog.py"

RUNTIME_ROOT="$LIB_DIR/runtimes"
mkdir -p "$RUNTIME_ROOT"
for marker in "$RUNTIME_ROOT"/.runtime.*/.jot-installing; do
  if [[ -e "$marker" ]]; then
    candidate="${marker%/.jot-installing}"
    if [[ ! -L "$LIB_DIR/current" || "$(readlink -f "$LIB_DIR/current")" != "$(readlink -f "$candidate")" ]]; then
      rm -rf "$candidate"
    fi
  fi
done
RUNTIME_DIR="$(mktemp -d "$RUNTIME_ROOT/.runtime.XXXXXX")"
touch "$RUNTIME_DIR/.jot-installing"
cp -R "$STAGE_DIR/." "$RUNTIME_DIR/"

if ! "$RUNTIME_DIR/jot" --version >/dev/null; then
  echo "error: staged runtime failed verification" >&2
  exit 1
fi
rm -f "$RUNTIME_DIR/.jot-installing"

if [[ -e "$LIB_DIR/jot" && ! -L "$LIB_DIR/jot" ]]; then
  LEGACY_RUNTIME="$(mktemp -d "$RUNTIME_ROOT/.runtime-legacy.XXXXXX")"
  touch "$LEGACY_RUNTIME/.jot-installing"
  for component in jot jot_core jot_tui hooks templates config-jot.toml; do
    if [[ -e "$LIB_DIR/$component" ]]; then
      mv "$LIB_DIR/$component" "$LEGACY_RUNTIME/$component"
    fi
  done
  rm -f "$LEGACY_RUNTIME/.jot-installing"
fi

activate_link() {
  local target="$1"
  local link="$2"
  local temporary="${link}.new.$$"
  ACTIVATION_TMP="$temporary"
  rm -f "$temporary"
  ln -s "$target" "$temporary"
  mv -Tf "$temporary" "$link"
  ACTIVATION_TMP=""
}

activate_link "current/jot" "$LIB_DIR/jot"
for component in jot_core jot_tui hooks templates; do
  activate_link "current/$component" "$LIB_DIR/$component"
done
activate_link "$LIB_DIR/jot" "$BIN_DIR/jot"
activate_link "$RUNTIME_DIR" "$LIB_DIR/current"
ACTIVE_DIR="$LIB_DIR/current"

TIMELOG_HOOK_SRC="$ACTIVE_DIR/hooks/on-modify_jot_timelog.py"
TIMELOG_HOOK_DIR="$TASK_HOOKS_DIR"
TIMELOG_HOOK_DST="$TIMELOG_HOOK_DIR/on-modify_jot_timelog.py"
if should_install_timelog_hook; then
  mkdir -p "$TIMELOG_HOOK_DIR"
  if [[ -e "$TIMELOG_HOOK_DST" && ! -f "$TIMELOG_HOOK_DST" ]]; then
    TIMELOG_HOOK_NOTE="Kept non-regular existing Taskwarrior hook path: $TIMELOG_HOOK_DST"
  elif [[ -e "$TIMELOG_HOOK_DST" ]] && ! cmp -s "$TIMELOG_HOOK_SRC" "$TIMELOG_HOOK_DST"; then
    if [[ "$REPLACE_TIMELOG_HOOK" != "yes" ]]; then
      TIMELOG_HOOK_NOTE="Kept existing Taskwarrior hook (use --replace-timelog-hook to replace): $TIMELOG_HOOK_DST"
    else
      install -m 755 "$TIMELOG_HOOK_SRC" "$TIMELOG_HOOK_DST"
      TIMELOG_HOOK_NOTE="Replaced Taskwarrior timelog hook: $TIMELOG_HOOK_DST"
    fi
  else
    install -m 755 "$TIMELOG_HOOK_SRC" "$TIMELOG_HOOK_DST"
    TIMELOG_HOOK_NOTE="Installed Taskwarrior timelog hook: $TIMELOG_HOOK_DST"
  fi
else
  TIMELOG_HOOK_NOTE="Timelog hook not enabled. To enable later: install -m 755 \"$TIMELOG_HOOK_SRC\" \"$TIMELOG_HOOK_DST\""
fi

if [[ ! -e "$CONFIG_PATH" ]]; then
  cat > "$CONFIG_PATH" <<EOF
[paths]
root = "$CONFIG_DIR"
tasks = "$CONFIG_DIR/tasks"
chains = "$CONFIG_DIR/chains"
projects = "$CONFIG_DIR/projects"
templates = "$CONFIG_DIR/templates"

[editor]
command = ""
show_diff_on_save = true
diff_color = "auto"
post_save_actions = true

[display]
color = "auto"
default_format = "text"

[nautical]
enabled = true

[timewarrior]
enabled = true
EOF
  CONFIG_NOTE="Installed default config: $CONFIG_PATH"
else
  CONFIG_NOTE="Kept existing config: $CONFIG_PATH"
fi

installed_templates=0
kept_templates=0
for name in task-note.md chain-note.md project-note.md; do
  src="$DATA_DIR/templates/$name"
  dst="$TEMPLATES_DIR/$name"
  if [[ ! -e "$dst" ]]; then
    install -m 644 "$src" "$dst"
    installed_templates=$((installed_templates + 1))
  else
    kept_templates=$((kept_templates + 1))
  fi
done

if python3 -c 'import textual' >/dev/null 2>&1; then
  TUI_NOTE="TUI available: textual is installed"
else
  TUI_NOTE="TUI unavailable: install the optional 'textual' Python package to use 'jot tui'"
fi

cat <<EOF
Installed jot to:
  $LIB_DIR

Command link:
  $BIN_DIR/jot

Task data directory:
  $TASKDATA_DIR

Task hooks directory:
  $TASK_HOOKS_DIR

$CONFIG_NOTE
Templates installed: $installed_templates
Templates kept: $kept_templates
Hook examples:
  $LIB_DIR/hooks
$TIMELOG_HOOK_NOTE
$TUI_NOTE

If '$BIN_DIR' is not on your PATH, add this to your shell profile:
  export PATH="$BIN_DIR:\$PATH"
EOF
