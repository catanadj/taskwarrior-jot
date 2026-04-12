#!/usr/bin/env bash

set -euo pipefail

PREFIX="${PREFIX:-$HOME/.local}"
BIN_DIR="$PREFIX/bin"
LIB_DIR="$PREFIX/lib/jot"
CONFIG_DIR="${JOT_HOME:-$HOME/.task/jot}"
CONFIG_PATH="$CONFIG_DIR/config-jot.toml"

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'EOF'
Usage: ./install.sh [--prefix DIR]

Installs jot without pip by copying the launcher and jot_core package into:
  <prefix>/lib/jot

and creating:
  <prefix>/bin/jot -> <prefix>/lib/jot/jot

Also installs a default config at:
  ~/.task/jot/config-jot.toml
if that file does not already exist.

Default prefix:
  ~/.local
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
rm -rf "$LIB_DIR/jot_core"

install -m 755 "$SCRIPT_DIR/jot" "$LIB_DIR/jot"
mkdir -p "$LIB_DIR/jot_core"
tar -C "$SCRIPT_DIR" \
  --exclude='jot_core/__pycache__' \
  --exclude='jot_core/*.pyc' \
  --exclude='jot_core/**/*.pyc' \
  -cf - jot_core | tar -C "$LIB_DIR" -xf -
install -m 644 "$SCRIPT_DIR/config-jot.toml" "$LIB_DIR/config-jot.toml"
ln -sfn "$LIB_DIR/jot" "$BIN_DIR/jot"

if [[ ! -e "$CONFIG_PATH" ]]; then
  install -m 644 "$SCRIPT_DIR/config-jot.toml" "$CONFIG_PATH"
  CONFIG_NOTE="Installed default config: $CONFIG_PATH"
else
  CONFIG_NOTE="Kept existing config: $CONFIG_PATH"
fi

cat <<EOF
Installed jot to:
  $LIB_DIR

Command link:
  $BIN_DIR/jot

$CONFIG_NOTE

If '$BIN_DIR' is not on your PATH, add this to your shell profile:
  export PATH="$BIN_DIR:\$PATH"
EOF
