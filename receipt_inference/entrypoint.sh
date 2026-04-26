#!/bin/sh

set -eu

LLAMA_SERVER_BIN="${LLAMA_SERVER_BIN:-/usr/local/bin/llama-server}"
LLAMA_HOST="${LLAMA_HOST:-127.0.0.1}"
LLAMA_PORT="${LLAMA_PORT:-8080}"
LLAMA_THREADS="${LLAMA_THREADS:-2}"
LLAMA_CONTEXT_SIZE="${LLAMA_CONTEXT_SIZE:-8192}"
LLAMA_BATCH_SIZE="${LLAMA_BATCH_SIZE:-1024}"
LLAMA_PARALLEL="${LLAMA_PARALLEL:-1}"
LLAMA_MODEL_ALIAS="${LLAMA_MODEL_ALIAS:-Qwen2.5-3B-Instruct-Q5_K_M}"
QWEN_MODEL_PATH="${QWEN_MODEL_PATH:-/models/qwen/qwen2.5-3b-instruct-q5_k_m.gguf}"
RECEIPT_INFERENCE_HOST="${RECEIPT_INFERENCE_HOST:-0.0.0.0}"
RECEIPT_INFERENCE_PORT="${RECEIPT_INFERENCE_PORT:-8010}"
GRANIAN_WORKERS="${GRANIAN_WORKERS:-1}"
GRANIAN_RUNTIME_THREADS="${GRANIAN_RUNTIME_THREADS:-1}"
GRANIAN_BLOCKING_THREADS="${GRANIAN_BLOCKING_THREADS:-1}"

cleanup() {
  if [ -n "${LLAMA_PID:-}" ] && kill -0 "$LLAMA_PID" 2>/dev/null; then
    kill "$LLAMA_PID" 2>/dev/null || true
    wait "$LLAMA_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

if [ ! -x "$LLAMA_SERVER_BIN" ]; then
  echo "llama-server binary not found at $LLAMA_SERVER_BIN" >&2
  exit 1
fi

if [ ! -f "$QWEN_MODEL_PATH" ]; then
  echo "Qwen model file not found at $QWEN_MODEL_PATH" >&2
  exit 1
fi

"$LLAMA_SERVER_BIN" \
  --host "$LLAMA_HOST" \
  --port "$LLAMA_PORT" \
  --threads "$LLAMA_THREADS" \
  --ctx-size "$LLAMA_CONTEXT_SIZE" \
  --batch-size "$LLAMA_BATCH_SIZE" \
  --parallel "$LLAMA_PARALLEL" \
  --alias "$LLAMA_MODEL_ALIAS" \
  --model "$QWEN_MODEL_PATH" \
  >/tmp/llama-server.log 2>&1 &
LLAMA_PID=$!

python - <<'PY'
import json
import os
import sys
import time
import urllib.error
import urllib.request

base_url = os.getenv('LLAMA_SERVER_URL', 'http://127.0.0.1:8080/v1').rstrip('/')
timeout_s = 120
deadline = time.monotonic() + timeout_s

while time.monotonic() < deadline:
    try:
        with urllib.request.urlopen(f'{base_url}/models', timeout=5) as response:
            payload = json.load(response)
        if isinstance(payload, dict) and isinstance(payload.get('data'), list):
            sys.exit(0)
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
        time.sleep(1)

print('Timed out waiting for llama-server readiness', file=sys.stderr)
sys.exit(1)
PY

exec granian \
  --interface asgi \
  receipt_inference.app:app \
  --host "$RECEIPT_INFERENCE_HOST" \
  --port "$RECEIPT_INFERENCE_PORT" \
  --workers "$GRANIAN_WORKERS" \
  --runtime-threads "$GRANIAN_RUNTIME_THREADS" \
  --blocking-threads "$GRANIAN_BLOCKING_THREADS"
