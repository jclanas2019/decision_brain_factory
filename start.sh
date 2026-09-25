#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8 PYTHONUNBUFFERED=1
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
# The project is isolated from an activated Conda/virtualenv or unrelated modules.
unset PYTHONPATH PYTHONHOME
export PYTHONPATH="$PWD/src" BRAIN_PROJECT_ROOT="$PWD"
python_cmd=""
for candidate in .venv/bin/python python3.12 python3.13 python3; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys;sys.exit(not ((3,12)<=sys.version_info[:2]<(3,14)))' >/dev/null 2>&1; then
    python_cmd="$candidate"
    break
  fi
done
if [[ -z "$python_cmd" ]]; then
  echo 'No se encontró Python 3.12 o 3.13. Instala Python 3.12 y vuelve a ejecutar bash start.sh.' >&2
  exit 2
fi
case "${1:-}" in
  new|list|validate) exec "$python_cmd" -m decision_brain.factory "$@" ;;
  --help|-h) exec "$python_cmd" -m decision_brain.launch --help ;;
esac
echo "Decision Brain 0.9.0 | $PWD"
"$python_cmd" scripts/bootstrap.py
case "${1:-}" in
  setup) exit 0 ;;
  gateway) shift; exec bash scripts/gateway.sh "$@" ;;
  observer) shift; exec bash scripts/observer.sh "$@" ;;
  operate) shift; exec .venv/bin/python -m decision_brain.operations "$@" ;;
  observe-demo) shift; exec .venv/bin/python -m decision_brain.gates_demo --serve "$@" ;;
  gates-demo) shift; exec .venv/bin/python -m decision_brain.gates_demo "$@" ;;
  harness) shift; exec .venv/bin/python -m decision_brain.harness "$@" ;;
  check) shift; exec .venv/bin/python -m decision_brain.launch --check-only "$@" ;;
  demo|train|generate|predict|--config) exec .venv/bin/python -m decision_brain.brain "$@" ;;
esac
exec .venv/bin/python -m decision_brain.launch "$@"
