#!/usr/bin/env bash
# Pre-commit hook for the cohort-explorer app.
# Runs frontend TypeScript compile + backend Python import check on staged files.
# Bypass with `git commit --no-verify` if you know what you're doing.

set -euo pipefail

REPO=$(git rev-parse --show-toplevel)
CE="$REPO/src/cohort-explorer"

CHANGED=$(git diff --cached --name-only --diff-filter=ACM || true)

touches() { echo "$CHANGED" | grep -q "^$1" 2>/dev/null; }

FE=0
BE=0
touches "src/cohort-explorer/frontend/" && FE=1 || true
touches "src/cohort-explorer/app/" && BE=1 || true

if [ "$FE" = 0 ] && [ "$BE" = 0 ]; then
  exit 0
fi

fail=0

if [ "$FE" = 1 ]; then
  echo "[pre-commit] frontend: tsc --noEmit"
  if [ ! -d "$CE/frontend/node_modules" ]; then
    echo "[pre-commit] FAIL: frontend/node_modules missing. Run: (cd $CE/frontend && npm ci)" >&2
    fail=1
  elif ! (cd "$CE/frontend" && npx --no-install tsc --noEmit); then
    echo "[pre-commit] FAIL: TypeScript errors above." >&2
    fail=1
  fi
fi

if [ "$BE" = 1 ]; then
  echo "[pre-commit] backend: python3 -c 'from main import app'"
  if ! python3 -c "import fastapi" 2>/dev/null; then
    echo "[pre-commit] FAIL: fastapi not importable. Run: pip install -r $CE/app/requirements.txt" >&2
    fail=1
  elif ! (cd "$CE/app" && python3 -c "from main import app" 2>&1); then
    echo "[pre-commit] FAIL: Backend import failed. See traceback above." >&2
    fail=1
  fi
fi

if [ "$fail" = 1 ]; then
  echo "[pre-commit] Commit blocked. Fix errors above or use --no-verify to bypass." >&2
  exit 1
fi

echo "[pre-commit] OK"
exit 0
