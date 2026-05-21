#!/usr/bin/env bash
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${SKILL_DIR}/.venv"
REQ_FILE="${SKILL_DIR}/requirements.txt"

echo "[ppt-narrator] install: skill_dir=${SKILL_DIR}"

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "[ppt-narrator] error: python3 is required" >&2
  exit 10
fi

"${PYTHON_BIN}" - <<'PY'
import sys
if sys.version_info < (3, 9):
    raise SystemExit("python >= 3.9 is required")
print(f"[ppt-narrator] python: {sys.version.split()[0]}")
PY

if [ -f "${REQ_FILE}" ] && grep -Ev '^\s*(#|$)' "${REQ_FILE}" >/dev/null; then
  if [ ! -x "${VENV_DIR}/bin/python" ]; then
    "${PYTHON_BIN}" -m venv "${VENV_DIR}"
  fi
  "${VENV_DIR}/bin/python" -m pip install -r "${REQ_FILE}"
else
  echo "[ppt-narrator] requirements: none"
fi

PYTHONPATH="${SKILL_DIR}/runtime/src" "${PYTHON_BIN}" - <<'PY'
import ppt_narrator
print(f"[ppt-narrator] runtime import: {ppt_narrator.__name__}")
PY

echo "[ppt-narrator] install: ok"
