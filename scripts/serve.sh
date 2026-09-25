#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
exec .venv/bin/python -m uvicorn decision_brain.service:create_app --factory --host 127.0.0.1 --port "${BRAIN_PORT:-8000}" --workers 1 --limit-concurrency 32 --timeout-keep-alive 5 --timeout-graceful-shutdown 20 --no-access-log
