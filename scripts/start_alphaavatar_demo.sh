#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# AlphaAvatar Demo Starter
# ============================================================
# Usage:
#   bash scripts/start_alphaavatar_demo.sh
#
# Optional env override:
#   ENV_FILE=.env.demo CONFIG_FILE=examples/agent_configs/roles/demo.yaml bash scripts/start_alphaavatar_demo.sh
#
# Optional mode:
#   START_MODE=dev bash scripts/start_alphaavatar_demo.sh
# ============================================================

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE="${ENV_FILE:-.env.demo}"
CONFIG_FILE="${CONFIG_FILE:-examples/agent_configs/roles/demo.yaml}"
START_MODE="${START_MODE:-start}"
PYTHON_VERSION="${PYTHON_VERSION:-3.11}"

VENV_DIR="${VENV_DIR:-.venv}"
LOG_DIR="${LOG_DIR:-logs}"
DOWNLOAD_FILES="${DOWNLOAD_FILES:-false}"

mkdir -p "$LOG_DIR"

echo "============================================================"
echo "🚀 Starting AlphaAvatar Demo"
echo "============================================================"
echo "Root dir:      $ROOT_DIR"
echo "Env file:      $ENV_FILE"
echo "Config file:   $CONFIG_FILE"
echo "Start mode:    $START_MODE"
echo "Venv dir:      $VENV_DIR"
echo "Download files:$DOWNLOAD_FILES"
echo "============================================================"

if [ ! -f "$ENV_FILE" ]; then
  echo "❌ ENV file not found: $ENV_FILE"
  echo "Please create it first, for example:"
  echo "  cp .env.template .env.demo"
  exit 1
fi

if [ ! -f "$CONFIG_FILE" ]; then
  echo "❌ Config file not found: $CONFIG_FILE"
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "❌ uv is not installed."
  echo "Install uv first:"
  echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
fi

if [ ! -d "$VENV_DIR" ]; then
  echo "📦 Creating virtual environment: $VENV_DIR"
  uv venv "$VENV_DIR" --python "$PYTHON_VERSION"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

echo "📦 Syncing dependencies..."
uv sync --all-packages

if [ "$DOWNLOAD_FILES" = "true" ]; then
  echo "📥 Downloading AlphaAvatar required files..."
  ENV_FILE="$ENV_FILE" alphaavatar download-files
fi

echo "✅ Environment ready."
echo "🚀 Launching AlphaAvatar..."
echo "Command:"
echo "  ENV_FILE=$ENV_FILE alphaavatar $START_MODE $CONFIG_FILE"
echo "============================================================"

exec env ENV_FILE="$ENV_FILE" PYTHONUNBUFFERED=1 alphaavatar "$START_MODE" "$CONFIG_FILE"
