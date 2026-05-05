#!/usr/bin/env bash
set -euo pipefail

# Copy the built static Vite output into the personal website repo embed path.
#
# Usage:
#   scripts/sync_website_embed.sh [target-dir]
#
# Local default target assumes these sibling clones:
#   ~/Projects/cdmx-convenience-map
#   ~/Projects/ignacio-ireta.github.io

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SOURCE_DIST="${SOURCE_DIST:-$REPO_ROOT/frontend/dist}"
TARGET_DIR="${1:-${TARGET_DIR:-$REPO_ROOT/../ignacio-ireta.github.io/projects/cdmx-map}}"

if [[ ! -f "$SOURCE_DIST/index.html" ]]; then
  echo "Missing $SOURCE_DIST/index.html" >&2
  echo "Run this first: cd frontend && npm run build" >&2
  exit 1
fi

TARGET_PARENT="$(dirname "$TARGET_DIR")"
mkdir -p "$TARGET_PARENT"
rm -rf "$TARGET_DIR"
mkdir -p "$TARGET_DIR"
cp -R "$SOURCE_DIST"/. "$TARGET_DIR"/

printf 'Synced %s -> %s\n' "$SOURCE_DIST" "$TARGET_DIR"
