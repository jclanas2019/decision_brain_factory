#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8
ssl_args=()
if [[ -n "${BRAIN_TLS_CERT:-}" || -n "${BRAIN_TLS_KEY:-}" ]]; then
  : "${BRAIN_TLS_CERT:?Define BRAIN_TLS_CERT}" "${BRAIN_TLS_KEY:?Define BRAIN_TLS_KEY}"
  ssl_args=(--ssl-certfile "$BRAIN_TLS_CERT" --ssl-keyfile "$BRAIN_TLS_KEY")
fi
if .venv/bin/python -c 'import json,os,sys; c=json.load(open(os.environ.get("BRAIN_GATEWAY_CONFIG","config/gates/gateway.json")));sys.exit(0 if c.get("require_tls",c["environment"]=="production") else 1)' && [[ ${#ssl_args[@]} -eq 0 ]]; then
  echo 'Este gateway exige TLS: define BRAIN_TLS_CERT y BRAIN_TLS_KEY.' >&2
  exit 2
fi
exec .venv/bin/python -m uvicorn decision_brain.gateway:create_app --factory --host "${BRAIN_GATEWAY_HOST:-127.0.0.1}" --port "${BRAIN_GATEWAY_PORT:-8443}" --workers 1 --limit-concurrency 64 --no-access-log "${ssl_args[@]}" "$@"
