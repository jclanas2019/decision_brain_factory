#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export BRAIN_REGISTRY="${BRAIN_REGISTRY:-registry/production}"
if [[ -z "${BRAIN_ID:-}" ]]; then
  BRAIN_ID="$(.venv/bin/python -c 'import json;print(json.load(open("config/gates/interop_gate.json"))["brain_id"])')"
  export BRAIN_ID
fi
exec .venv/bin/python -m uvicorn decision_brain.service:create_app --factory --host 127.0.0.1 --port "${BRAIN_PORT:-8000}" --workers 1 --limit-concurrency 32 --timeout-keep-alive 5 --timeout-graceful-shutdown 20 --no-access-log
