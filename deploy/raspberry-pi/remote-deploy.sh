#!/usr/bin/env bash
set -euo pipefail

# Sync this repository to a Raspberry Pi over SSH and deploy via Docker Compose or native systemd.
# Usage:
#   ./deploy/raspberry-pi/remote-deploy.sh <user@pi-host> [--mode docker|native] [--with-paddle|--tesseract-only] [--port 8085] [--dir ~/telugu-digitizer]

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <user@pi-host> [--mode docker|native] [--with-paddle|--tesseract-only] [--port 8085] [--dir ~/telugu-digitizer]" >&2
  exit 2
fi

TARGET="$1"
shift

MODE="native"
PADDLE_FLAG="--with-paddle"
REMOTE_DIR="~/telugu-digitizer"
API_PORT="${API_PORT:-8085}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      MODE="${2:?Missing value for --mode}"
      shift 2
      ;;
    --with-paddle|--tesseract-only)
      PADDLE_FLAG="$1"
      shift
      ;;
    --port)
      API_PORT="${2:?Missing value for --port}"
      shift 2
      ;;
    --dir)
      REMOTE_DIR="${2:?Missing value for --dir}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

if [[ -d frontend && ! -f frontend/dist/index.html ]]; then
  echo "==> Building frontend/dist locally first..."
  (cd frontend && npm ci && npm run build)
fi

echo "==> Syncing codebase to ${TARGET}:${REMOTE_DIR}..."
rsync -az --delete \
  --exclude '.git/' \
  --exclude '.venv/' \
  --exclude '.tools/' \
  --exclude '.pytest_cache/' \
  --exclude '__pycache__/' \
  --exclude 'frontend/node_modules/' \
  --exclude 'workspace/' \
  --exclude 'artifacts/' \
  --exclude 'data/originals/' \
  --exclude 'data/pages/' \
  --exclude 'deploy/.env.lahari' \
  --exclude 'deploy/raspberry-pi/cloudflared-config.yml' \
  ./ "${TARGET}:${REMOTE_DIR}/"

SSH_TTY_FLAG=()
if [[ -t 0 ]]; then
  SSH_TTY_FLAG=(-t)
fi

if [[ "$MODE" == "native" ]]; then
  echo "==> Running native Raspberry Pi installer (${PADDLE_FLAG}, API_PORT=${API_PORT})..."
  ssh "${SSH_TTY_FLAG[@]}" "$TARGET" "cd ${REMOTE_DIR} && chmod +x deploy/raspberry-pi/install.sh && API_PORT='${API_PORT}' ./deploy/raspberry-pi/install.sh ${PADDLE_FLAG}"
elif [[ "$MODE" == "docker" ]]; then
  echo "==> Synced to ${TARGET}:${REMOTE_DIR}."
  ssh "${SSH_TTY_FLAG[@]}" "$TARGET" "cd ${REMOTE_DIR} && if [[ ! -f deploy/.env.lahari ]]; then cp deploy/.env.lahari.example deploy/.env.lahari && echo 'Created deploy/.env.lahari from template — edit passwords/token first, then run docker compose -f deploy/compose.lahari.yml --env-file deploy/.env.lahari --profile tunnel up -d --build'; else docker compose -f deploy/compose.lahari.yml --env-file deploy/.env.lahari up -d --build; fi"
else
  echo "Invalid --mode '$MODE' (expected docker or native)." >&2
  exit 2
fi
