#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
bash start.sh setup
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8
exec .venv/bin/python -m decision_brain.harness "$@"
