#!/usr/bin/env bash
(
  set -euo pipefail

  REPO=/srv/ai-workspaces/jma-dev
  PY="$REPO/.venv/bin/python"

  if [ "$(id -un)" != "hermes" ]; then
      echo "FAIL: validator must run as hermes" >&2
      exit 77
  fi

  if [ ! -d "$REPO/.git" ]; then
      echo "FAIL: canonical repository missing: $REPO" >&2
      exit 77
  fi

  if [ ! -x "$PY" ]; then
      echo "FAIL: JMA development venv missing: $PY" >&2
      exit 77
  fi

  cd "$REPO"

  echo "============================================================"
  echo "JMA CANONICAL CANDIDATE VALIDATOR"
  echo "============================================================"

  echo
  echo "=== pytest ==="
  "$PY" -m pytest -q

  echo
  echo "=== configuration surface audit ==="
  "$PY" -m tools.configuration_surface_audit

  echo
  echo "=== JellyHA dependency audit ==="
  "$PY" -m tools.jellyha_dependency_audit

  echo
  echo "=== repository packaging audit ==="
  "$PY" -m tools.repository_packaging_audit

  echo
  echo "=== git diff --check ==="
  git diff --check

  echo
  echo "JMA_VALIDATION=PASS"
)
