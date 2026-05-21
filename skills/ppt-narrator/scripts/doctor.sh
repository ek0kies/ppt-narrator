#!/usr/bin/env bash
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
STATUS=0

check() {
  local label="$1"
  shift
  if "$@"; then
    echo "[ok] ${label}"
  else
    echo "[fail] ${label}" >&2
    STATUS=1
  fi
}

echo "[ppt-narrator] doctor: skill_dir=${SKILL_DIR}"

check "SKILL.md exists" test -f "${SKILL_DIR}/SKILL.md"
check "runtime package exists" test -d "${SKILL_DIR}/runtime/src/ppt_narrator"
check "run.py exists" test -f "${SKILL_DIR}/scripts/run.py"
check "run.sh exists" test -f "${SKILL_DIR}/scripts/run.sh"
check "python3 available" command -v "${PYTHON_BIN}"

if command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  PYTHONPATH="${SKILL_DIR}/runtime/src" "${PYTHON_BIN}" - <<'PY' || STATUS=1
import sys
if sys.version_info < (3, 9):
    raise SystemExit("python >= 3.9 is required")
from ppt_narrator.cli import build_parser
parser = build_parser()
print("[ok] runtime import and CLI parser")
PY
fi

if command -v ffprobe >/dev/null 2>&1; then
  echo "[ok] ffprobe available"
else
  echo "[warn] ffprobe not found; WAV works, MP3/M4A duration probing may fail"
fi

if command -v unzip >/dev/null 2>&1; then
  echo "[ok] unzip available"
else
  echo "[warn] unzip not found; PPTX archive verification will be skipped"
fi

if [ "${STATUS}" -ne 0 ]; then
  echo "[ppt-narrator] doctor: failed" >&2
  exit "${STATUS}"
fi

echo "[ppt-narrator] doctor: ok"
