#!/usr/bin/env bash
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
WORK_DIR="${TMPDIR:-/tmp}/ppt-narrator-skill-smoke-$$"
INPUT_PPTX="${WORK_DIR}/sample.pptx"
OUTPUT_DIR="${WORK_DIR}/out"

cleanup() {
  if [ "${PPT_NARRATOR_KEEP_SMOKE:-0}" != "1" ]; then
    rm -rf "${WORK_DIR}"
  fi
}
trap cleanup EXIT

mkdir -p "${WORK_DIR}"
"${PYTHON_BIN}" "${SKILL_DIR}/tests/create_sample_pptx.py" "${INPUT_PPTX}" >/dev/null
"${SKILL_DIR}/scripts/run.sh" "${INPUT_PPTX}" \
  --provider dry-run \
  --output "${OUTPUT_DIR}" \
  --overwrite

MANIFEST="${OUTPUT_DIR}/manifest.json"
PPTX="$(find "${OUTPUT_DIR}" -maxdepth 1 -name '*.auto-narrated.pptx' -print -quit)"

test -f "${MANIFEST}"
test -n "${PPTX}"
test -f "${PPTX}"

if command -v unzip >/dev/null 2>&1; then
  unzip -t "${PPTX}" >/dev/null
fi

echo "[ppt-narrator] smoke: ok"
echo "[ppt-narrator] smoke_pptx: ${PPTX}"
