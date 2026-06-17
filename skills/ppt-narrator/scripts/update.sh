#!/usr/bin/env bash
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [ "${PPT_NARRATOR_SKIP_DOCTOR:-0}" != "1" ]; then
  "${SKILL_DIR}/scripts/doctor.sh" >/dev/null
fi

PYTHONPATH="${SKILL_DIR}/runtime/src" exec "${PYTHON_BIN}" "${SKILL_DIR}/scripts/update.py" "$@"
