#!/usr/bin/env bash
# Install the cohort-explorer pre-commit hook into .git/hooks/pre-commit.
# Idempotent — safe to run multiple times.

set -euo pipefail

REPO=$(git rev-parse --show-toplevel)
HOOK_SRC="$REPO/src/cohort-explorer/scripts/pre-commit.sh"
HOOK_DST="$REPO/.git/hooks/pre-commit"

if [ ! -f "$HOOK_SRC" ]; then
  echo "ERROR: hook source not found at $HOOK_SRC" >&2
  exit 1
fi

chmod +x "$HOOK_SRC"

if [ -e "$HOOK_DST" ] || [ -L "$HOOK_DST" ]; then
  if [ -L "$HOOK_DST" ] && [ "$(readlink "$HOOK_DST")" = "$HOOK_SRC" ]; then
    echo "pre-commit hook already installed."
    exit 0
  fi
  echo "Backing up existing hook to $HOOK_DST.bak"
  mv "$HOOK_DST" "$HOOK_DST.bak"
fi

ln -s "$HOOK_SRC" "$HOOK_DST"
echo "Installed pre-commit hook: $HOOK_DST -> $HOOK_SRC"
echo "Bypass any single commit with: git commit --no-verify"
