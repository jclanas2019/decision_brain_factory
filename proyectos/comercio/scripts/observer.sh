#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8
exec .venv/bin/python -m uvicorn decision_brain.observer:create_app --factory --host 127.0.0.1 --port "${BRAIN_OBSERVER_PORT:-9100}" --workers 1 --no-access-log "$@"
