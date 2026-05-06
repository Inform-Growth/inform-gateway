#!/usr/bin/env bash
# dev.sh — run the Remote Gateway and the admin-ui Vite dev server together.
# Ctrl-C kills both. See docs/superpowers/specs/2026-05-05-admin-ui-react-port-design.md.
set -euo pipefail

cleanup() {
  echo
  echo "[dev.sh] shutting down…"
  if [[ -n "${PY_PID:-}" ]] && kill -0 "$PY_PID" 2>/dev/null; then kill "$PY_PID" || true; fi
  if [[ -n "${UI_PID:-}" ]] && kill -0 "$UI_PID" 2>/dev/null; then kill "$UI_PID" || true; fi
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

echo "[dev.sh] starting Python gateway on :8000"
python remote-gateway/core/mcp_server.py &
PY_PID=$!

if [[ ! -d remote-gateway/admin-ui/node_modules ]]; then
  echo "[dev.sh] installing admin-ui deps"
  (cd remote-gateway/admin-ui && npm install)
fi

echo "[dev.sh] starting Vite on :5173"
(cd remote-gateway/admin-ui && npm run dev) &
UI_PID=$!

echo
echo "[dev.sh] gateway:  http://localhost:8000"
echo "[dev.sh] admin-ui: http://localhost:5173/admin"
echo "[dev.sh] (Ctrl-C to stop both)"

wait "$PY_PID" "$UI_PID"
