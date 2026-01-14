#!/usr/bin/env bash
set -euo pipefail

# Linux-only workflow (assumes GNU find/cp behavior).

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUBMODULE_DIR="${ROOT_DIR}/idr-metadata"
STUDIES_DIR="${ROOT_DIR}/examples/studies"
OUTPUT_DIR="${ROOT_DIR}/ro-crates"

if [[ ! -d "${SUBMODULE_DIR}" ]]; then
  echo "Missing submodule at ${SUBMODULE_DIR}" >&2
  echo "Run: git submodule update --init --recursive" >&2
  exit 1
fi

mkdir -p "${STUDIES_DIR}"
find "${SUBMODULE_DIR}" -name 'idr*-study.txt' -exec cp -v {} "${STUDIES_DIR}/" \;

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required. Install from https://docs.astral.sh/uv/ and retry." >&2
  exit 1
fi

uv run -- python "${ROOT_DIR}/scripts/batch_generate.py" \
  --input-dir "${STUDIES_DIR}" \
  --output-dir "${OUTPUT_DIR}"
