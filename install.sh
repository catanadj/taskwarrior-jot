#!/usr/bin/env bash

set -euo pipefail

PREFIX="${PREFIX:-$HOME/.local}"
BIN_DIR="$PREFIX/bin"
LIB_DIR="$PREFIX/lib/jot"

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

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
          value="${value%\"}"
          value="${value#\"}"
          value="${value%\'}"
          value="${value#\'}"
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

TASKDATA_DIR="$(resolve_taskdata_dir)"
TASKDATA_DIR="${TASKDATA_DIR/#\~/$HOME}"
CONFIG_DIR="${JOT_HOME:-$TASKDATA_DIR/jot}"
CONFIG_PATH="$CONFIG_DIR/config-jot.toml"
TEMPLATES_DIR="$CONFIG_DIR/templates"

usage() {
  cat <<'EOF'
Usage: ./install.sh [--prefix DIR]

Installs jot without pip by copying the launcher and jot_core package into:
  <prefix>/lib/jot

and creating:
  <prefix>/bin/jot -> <prefix>/lib/jot/jot

Also installs a default config at:
  <task-data-dir>/jot/config-jot.toml
if that file does not already exist.

Default prefix:
  ~/.local

Task data directory is resolved from TASKDATA, then TASKRC/~/.taskrc
data.location, then ~/.task. Set JOT_HOME to override the jot data directory.
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

mkdir -p "$BIN_DIR"
mkdir -p "$LIB_DIR"
mkdir -p "$CONFIG_DIR"
mkdir -p "$TEMPLATES_DIR"
rm -rf "$LIB_DIR/jot_core"
rm -rf "$LIB_DIR/jot_tui"
rm -rf "$LIB_DIR/templates"

install -m 755 "$SCRIPT_DIR/jot" "$LIB_DIR/jot"
mkdir -p "$LIB_DIR/jot_core"
tar -C "$SCRIPT_DIR" \
  --exclude='jot_core/__pycache__' \
  --exclude='jot_core/*.pyc' \
  --exclude='jot_core/**/*.pyc' \
  --exclude='jot_tui/__pycache__' \
  --exclude='jot_tui/*.pyc' \
  --exclude='jot_tui/**/*.pyc' \
  -cf - jot_core jot_tui | tar -C "$LIB_DIR" -xf -
install -m 644 "$SCRIPT_DIR/config-jot.toml" "$LIB_DIR/config-jot.toml"
mkdir -p "$LIB_DIR/templates"
cp -R "$SCRIPT_DIR/templates/." "$LIB_DIR/templates/"
ln -sfn "$LIB_DIR/jot" "$BIN_DIR/jot"

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

[display]
color = "auto"
default_format = "text"

[nautical]
enabled = true
EOF
  CONFIG_NOTE="Installed default config: $CONFIG_PATH"
else
  CONFIG_NOTE="Kept existing config: $CONFIG_PATH"
fi

installed_templates=0
kept_templates=0
for name in task-note.md chain-note.md project-note.md; do
  src="$SCRIPT_DIR/templates/$name"
  dst="$TEMPLATES_DIR/$name"
  if [[ ! -e "$dst" ]]; then
    install -m 644 "$src" "$dst"
    installed_templates=$((installed_templates + 1))
  else
    kept_templates=$((kept_templates + 1))
  fi
done

cat <<EOF
Installed jot to:
  $LIB_DIR

Command link:
  $BIN_DIR/jot

$CONFIG_NOTE
Templates installed: $installed_templates
Templates kept: $kept_templates

If '$BIN_DIR' is not on your PATH, add this to your shell profile:
  export PATH="$BIN_DIR:\$PATH"
EOF
