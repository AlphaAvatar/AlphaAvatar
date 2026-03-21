#!/usr/bin/env bash

set -euo pipefail

PIDS=()

cleanup() {
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT INT TERM


wait_for_port() {
  local port=$1
  local name=$2

  echo "Waiting for $name on port $port..."

  for i in {1..60}; do
    if (echo > /dev/tcp/127.0.0.1/"$port") >/dev/null 2>&1; then
      echo "$name is ready."
      return 0
    fi
    sleep 1
  done

  echo "Timeout waiting for $name"
  exit 1
}


wait_for_log() {
  local file=$1
  local pattern=$2
  local name=$3

  echo "Waiting for $name to be ready..."

  for i in {1..120}; do
    if grep -q "$pattern" "$file" 2>/dev/null; then
      echo "$name is ready."
      return 0
    fi
    sleep 1
  done

  echo "Timeout waiting for $name"
  echo "Last log lines:"
  tail -n 50 "$file" 2>/dev/null || true
  exit 1
}


# ---- Start WhatsApp Core ----
echo "[1/2] Starting WhatsApp Core..."

uv run alphaavatar-whatsapp-core &
CORE_PID=$!
PIDS+=($CORE_PID)

wait_for_port 18789 "WhatsApp Core WS"


# ---- Start Baileys Driver ----
echo "[2/2] Starting Baileys Driver..."

cd avatar-channels/avatar-channels-whatsapp/drivers/baileys

LOG_FILE="/tmp/baileys.log"
rm -f "$LOG_FILE"

CORE_WS_URL="ws://127.0.0.1:18789" pnpm dev 2>&1 | tee "$LOG_FILE" &
BAILEYS_PID=$!
PIDS+=($BAILEYS_PID)

wait_for_log "$LOG_FILE" "Own LID session created successfully" "Baileys Driver"

echo
echo "=============================================="
echo "✅ All services started."
echo "✅ Room: ${WHATSAPP_ROOM:-wa_mvp}"
echo "✅ Send a WhatsApp message to test."
echo "=============================================="
echo

tail -f "$LOG_FILE" &
PIDS+=($!)

wait
