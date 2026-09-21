#!/usr/bin/env bash

# Download a tagged Jot source archive and delegate installation to install.sh.
set -euo pipefail

REPOSITORY="${JOT_REPOSITORY:-https://github.com/catanadj/taskwarrior-jot}"
VERSION="${JOT_VERSION:-v1.0.2}"
ARCHIVE_URL="${JOT_ARCHIVE_URL:-}"
CHECKSUM="${JOT_SHA256:-}"
CHECKSUM_URL="${JOT_CHECKSUM_URL:-}"
PREFIX="${PREFIX:-$HOME/.local}"
TASKDATA_PATH="${TASKDATA:-$HOME/.task}"
INSTALL_TIMELOG_HOOK="no"
REPLACE_TIMELOG_HOOK="no"
DRY_RUN="no"
KEEP_CHECKOUT="no"

usage() {
  cat <<'EOF'
Usage: bootstrap.sh [options]

Download and install a Jot release.

Options:
  --version REF         Release tag or branch (default: v1.0.2)
  --prefix DIR          Installation prefix (default: ~/.local)
  --taskdata PATH       Taskwarrior data directory (default: TASKDATA or ~/.task)
  --archive-url URL     Archive URL override, useful for mirrors and testing
  --sha256 DIGEST       Expected SHA-256 digest for the archive
  --checksum-url URL    URL of a checksum file whose first field is the digest
  --with-timelog-hook   Install Jot's Taskwarrior timelog hook
  --no-timelog-hook     Do not install the timelog hook
  --replace-timelog-hook
                        Replace a different existing timelog hook
  --dry-run             Download and validate without installing
  --keep-checkout       Keep the temporary release checkout for inspection
  -h, --help            Show this help
EOF
}

die() {
  printf 'jot bootstrap: %s\n' "$1" >&2
  exit 2
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

while (($#)); do
  case "$1" in
    --version)
      (($# >= 2)) || die "--version requires a release tag or branch"
      VERSION="$2"
      shift 2
      ;;
    --prefix)
      (($# >= 2)) || die "--prefix requires a directory"
      PREFIX="$2"
      shift 2
      ;;
    --taskdata)
      (($# >= 2)) || die "--taskdata requires a directory"
      TASKDATA_PATH="$2"
      shift 2
      ;;
    --archive-url)
      (($# >= 2)) || die "--archive-url requires a URL"
      ARCHIVE_URL="$2"
      shift 2
      ;;
    --sha256)
      (($# >= 2)) || die "--sha256 requires a digest"
      CHECKSUM="$2"
      shift 2
      ;;
    --checksum-url)
      (($# >= 2)) || die "--checksum-url requires a URL"
      CHECKSUM_URL="$2"
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
    --dry-run)
      DRY_RUN="yes"
      shift
      ;;
    --keep-checkout)
      KEEP_CHECKOUT="yes"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

require_command curl
require_command tar
require_command python3

if [[ -z "$ARCHIVE_URL" ]]; then
  ARCHIVE_URL="$REPOSITORY/archive/refs/tags/$VERSION.tar.gz"
fi

CHECKOUT="$(mktemp -d "${TMPDIR:-/tmp}/jot-bootstrap.XXXXXX")"
cleanup() {
  if [[ "$KEEP_CHECKOUT" == "yes" ]]; then
    printf 'Kept release checkout: %s\n' "$CHECKOUT"
  else
    rm -rf "$CHECKOUT"
  fi
}
trap cleanup EXIT

ARCHIVE="$CHECKOUT/release.tar.gz"
printf 'Downloading Jot %s\n' "$VERSION"
printf '  %s\n' "$ARCHIVE_URL"
curl --fail --silent --show-error --location "$ARCHIVE_URL" --output "$ARCHIVE"

if [[ -n "$CHECKSUM_URL" ]]; then
  CHECKSUM_FILE="$CHECKOUT/release.sha256"
  curl --fail --silent --show-error --location "$CHECKSUM_URL" --output "$CHECKSUM_FILE"
  CHECKSUM="$(awk 'NF { print $1; exit }' "$CHECKSUM_FILE")"
fi

if [[ -n "$CHECKSUM" ]]; then
  if [[ ! "$CHECKSUM" =~ ^[[:xdigit:]]{64}$ ]]; then
    die "invalid SHA-256 digest"
  fi
  ACTUAL_CHECKSUM="$(python3 - "$ARCHIVE" <<'PY'
import hashlib
import sys

digest = hashlib.sha256()
with open(sys.argv[1], "rb") as archive:
    for block in iter(lambda: archive.read(1024 * 1024), b""):
        digest.update(block)
print(digest.hexdigest())
PY
)"
  if [[ "${CHECKSUM,,}" != "$ACTUAL_CHECKSUM" ]]; then
    die "archive checksum mismatch"
  fi
  printf 'Archive checksum verified: %s\n' "$ACTUAL_CHECKSUM"
else
  printf 'warning: archive checksum was not verified\n' >&2
fi

ARCHIVE_LIST="$CHECKOUT/archive.list"
tar -tzf "$ARCHIVE" > "$ARCHIVE_LIST"
ARCHIVE_ROOT="$(awk -F/ 'NF { print $1; exit }' "$ARCHIVE_LIST")"
[[ -n "$ARCHIVE_ROOT" ]] || die "release archive is empty"
tar -xzf "$ARCHIVE" -C "$CHECKOUT"
SOURCE_DIR="$CHECKOUT/$ARCHIVE_ROOT"
[[ -f "$SOURCE_DIR/install.sh" ]] || die "release archive has no install.sh"
[[ -f "$SOURCE_DIR/jot" ]] || die "release archive has no jot launcher"

if [[ "$DRY_RUN" == "yes" ]]; then
  printf 'Validated release source: %s\n' "$SOURCE_DIR"
  printf 'No files were installed (--dry-run).\n'
  exit 0
fi

INSTALL_ARGS=(--prefix "$PREFIX")
if [[ "$INSTALL_TIMELOG_HOOK" == "yes" ]]; then
  INSTALL_ARGS+=(--with-timelog-hook)
else
  INSTALL_ARGS+=(--no-timelog-hook)
fi
if [[ "$REPLACE_TIMELOG_HOOK" == "yes" ]]; then
  INSTALL_ARGS+=(--replace-timelog-hook)
fi

printf 'Installing Jot to %s\n' "$PREFIX"
TASKDATA="$TASKDATA_PATH" PREFIX="$PREFIX" bash "$SOURCE_DIR/install.sh" "${INSTALL_ARGS[@]}"

LAUNCHER="$PREFIX/bin/jot"
[[ -x "$LAUNCHER" ]] || die "installation did not create an executable launcher: $LAUNCHER"
VERSION_OUTPUT="$($LAUNCHER --version)"
printf 'Installation verified: %s\n' "$VERSION_OUTPUT"
if ! DOCTOR_OUTPUT="$($LAUNCHER doctor --installation-only --json)"; then
  printf '%s\n' "$DOCTOR_OUTPUT" >&2
  die "installation Doctor failed"
fi
printf 'Installation Doctor passed\n'
