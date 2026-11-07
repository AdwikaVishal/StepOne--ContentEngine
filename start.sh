#!/usr/bin/env bash
# ============================================================
# start.sh — One-command startup for the Content & Design Engine
#
# Usage:
#   bash start.sh              # start everything (API + worker + UI)
#   bash start.sh --no-worker  # skip Celery worker (sync/APScheduler mode)
#   bash start.sh --no-ui      # skip frontend dev server
#   bash start.sh --no-flower  # skip Flower monitoring dashboard
#   bash start.sh --prod       # production mode (no --reload)
#
# Prerequisites:
#   - Python 3.10+ with pip
#   - Node.js 18+ with npm
#   - Redis (optional — falls back to in-process mode without it)
#   - ffmpeg (optional — required for Reel generation)
# ============================================================

set -euo pipefail

# ── Parse flags ───────────────────────────────────────────────────────────────
START_WORKER=true
START_UI=true
START_FLOWER=true
PROD_MODE=false

for arg in "$@"; do
  case $arg in
    --no-worker) START_WORKER=false ;;
    --no-ui)     START_UI=false ;;
    --no-flower) START_FLOWER=false ;;
    --prod)      PROD_MODE=true ;;
  esac
done

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'

log()  { echo -e "${CYAN}[start.sh]${NC} $1"; }
ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
warn() { echo -e "  ${YELLOW}⚠${NC}  $1"; }
err()  { echo -e "  ${RED}✗${NC} $1"; }

echo ""
echo -e "${BLUE}╔══════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   Content & Design Engine — Startup          ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════╝${NC}"
echo ""

# ── Check .env ────────────────────────────────────────────────────────────────
if [ ! -f .env ]; then
  warn ".env not found — copying from .env.example"
  cp .env.example .env
  warn "Edit .env to configure Redis URL and other settings."
fi

# Load env vars (ignore comments and blank lines)
set -a
# shellcheck disable=SC1091
source <(grep -v '^#' .env | grep -v '^$') 2>/dev/null || true
set +a

# ── Virtual environment ───────────────────────────────────────────────────────
if [ ! -d ".venv311" ]; then
  log "Creating Python virtual environment..."
  python3 -m venv .venv311
  ok "Virtual environment created"
fi

source .venv311/bin/activate
ok "Virtual environment active ($(python --version))"

# ── PYTHONPATH ────────────────────────────────────────────────────────────────
# Ensure content_engine is importable from any working directory
# (required for Celery workers and scripts run outside the project root)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="${SCRIPT_DIR}${PYTHONPATH:+:${PYTHONPATH}}"
ok "PYTHONPATH set to ${SCRIPT_DIR}"

# ── Python dependencies ───────────────────────────────────────────────────────
log "Checking Python dependencies..."
if ! python -c "import fastapi, uvicorn, celery, redis" 2>/dev/null; then
  log "Installing from requirements.txt (this may take a few minutes)..."
  pip install -r requirements.txt --quiet --no-warn-script-location
fi
ok "Python dependencies ready"

# ── Frontend dependencies ─────────────────────────────────────────────────────
if [ "$START_UI" = true ]; then
  if [ ! -d "ml_test_ui/node_modules" ]; then
    log "Installing frontend dependencies..."
    npm install --prefix ml_test_ui --silent
  fi
  ok "Frontend dependencies ready"
fi

# ── Redis check ───────────────────────────────────────────────────────────────
REDIS_AVAILABLE=false
REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"

if command -v redis-cli &>/dev/null; then
  if redis-cli -u "$REDIS_URL" ping &>/dev/null 2>&1; then
    REDIS_AVAILABLE=true
    ok "Redis is running at $REDIS_URL"
  else
    warn "Redis not responding at $REDIS_URL"
    # Try to start it
    if command -v redis-server &>/dev/null; then
      log "Attempting to start redis-server..."
      redis-server --daemonize yes --logfile /tmp/redis-ce.log 2>/dev/null || true
      sleep 1
      if redis-cli ping &>/dev/null 2>&1; then
        REDIS_AVAILABLE=true
        ok "Redis started successfully"
      fi
    fi
    if [ "$REDIS_AVAILABLE" = false ]; then
      warn "Redis unavailable — async jobs will use in-process APScheduler fallback"
      warn "Install Redis:  macOS: brew install redis | Ubuntu: sudo apt install redis-server"
      START_WORKER=false
      START_FLOWER=false
    fi
  fi
else
  warn "redis-cli not found — running in sync/APScheduler mode"
  warn "Install Redis:  macOS: brew install redis | Ubuntu: sudo apt install redis-server"
  START_WORKER=false
  START_FLOWER=false
fi

# ── ffmpeg check ──────────────────────────────────────────────────────────────
if command -v ffmpeg &>/dev/null; then
  ok "ffmpeg available (Reel generation enabled)"
else
  warn "ffmpeg not found — Reel generation will be skipped"
  warn "Install:  macOS: brew install ffmpeg | Ubuntu: sudo apt install ffmpeg"
fi

# ── Create required directories ───────────────────────────────────────────────
mkdir -p uploads output logs models
ok "Directories ready (uploads/ output/ logs/ models/)"

# ── PID tracking for clean shutdown ──────────────────────────────────────────
PIDS=()

cleanup() {
  echo ""
  log "Shutting down all services..."
  for pid in "${PIDS[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null
      echo -e "  Stopped PID $pid"
    fi
  done
  # Clean up Celery PID files
  rm -f logs/celery_worker.pid logs/celery_beat.pid 2>/dev/null || true
  exit 0
}
trap cleanup INT TERM

# ── Start Celery worker ───────────────────────────────────────────────────────
if [ "$START_WORKER" = true ]; then
  log "Starting Celery worker..."
  CONCURRENCY="${CELERY_WORKER_CONCURRENCY:-1}"
  celery -A api.worker worker \
    --loglevel="${LOG_LEVEL:-WARNING}" \
    --concurrency="$CONCURRENCY" \
    --pool=solo \
    --max-tasks-per-child="${CELERY_WORKER_MAX_TASKS_PER_CHILD:-50}" \
    --hostname="worker@%h" \
    --logfile="logs/celery_worker.log" \
    --pidfile="logs/celery_worker.pid" \
    2>/dev/null &
  WORKER_PID=$!
  PIDS+=($WORKER_PID)
  sleep 1
  if kill -0 $WORKER_PID 2>/dev/null; then
    ok "Celery worker started (PID $WORKER_PID, concurrency=$CONCURRENCY)"
  else
    warn "Celery worker failed to start — check logs/celery_worker.log"
  fi
fi

# ── Start Flower monitoring ───────────────────────────────────────────────────
if [ "$START_FLOWER" = true ] && [ "$REDIS_AVAILABLE" = true ]; then
  FLOWER_PORT="${FLOWER_PORT:-5555}"
  log "Starting Flower monitoring dashboard..."
  celery -A api.worker flower \
    --port="$FLOWER_PORT" \
    --broker="$REDIS_URL" \
    --logfile="logs/flower.log" \
    2>/dev/null &
  FLOWER_PID=$!
  PIDS+=($FLOWER_PID)
  ok "Flower started (PID $FLOWER_PID) → http://localhost:$FLOWER_PORT"
fi

# ── Start FastAPI backend ─────────────────────────────────────────────────────
log "Starting FastAPI backend..."
API_PORT="${API_PORT:-8000}"
API_HOST="${API_HOST:-0.0.0.0}"

if [ "$PROD_MODE" = true ]; then
  uvicorn api.main:app \
    --host "$API_HOST" \
    --port "$API_PORT" \
    --workers "${API_WORKERS:-1}" \
    --log-level warning \
    2>&1 | tee -a logs/api.log &
else
  uvicorn api.main:app \
    --host "$API_HOST" \
    --port "$API_PORT" \
    --reload \
    --reload-exclude '.venv311' \
    --reload-exclude 'uploads' \
    --reload-exclude 'output' \
    --reload-exclude 'logs' \
    --reload-exclude 'models' \
    --log-level info \
    2>&1 | tee -a logs/api.log &
fi
API_PID=$!
PIDS+=($API_PID)
ok "FastAPI backend started (PID $API_PID)"

# ── Start frontend dev server ─────────────────────────────────────────────────
if [ "$START_UI" = true ]; then
  log "Starting ML Test UI (Vite dev server)..."
  npm run dev --prefix ml_test_ui 2>&1 | tee -a logs/ui.log &
  UI_PID=$!
  PIDS+=($UI_PID)
  ok "ML Test UI started (PID $UI_PID)"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   All services running                       ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${CYAN}Backend API${NC}   →  http://localhost:${API_PORT:-8000}"
echo -e "  ${CYAN}API Docs${NC}      →  http://localhost:${API_PORT:-8000}/docs"
[ "$START_UI" = true ]     && echo -e "  ${CYAN}ML Test UI${NC}    →  http://localhost:5173"
[ "$START_FLOWER" = true ] && [ "$REDIS_AVAILABLE" = true ] && \
  echo -e "  ${CYAN}Flower${NC}        →  http://localhost:${FLOWER_PORT:-5555}"
[ "$REDIS_AVAILABLE" = true ] && [ "$START_WORKER" = true ] && \
  echo -e "  ${CYAN}Job backend${NC}   →  Celery + Redis (async)"
[ "$REDIS_AVAILABLE" = false ] && \
  echo -e "  ${YELLOW}Job backend${NC}   →  APScheduler in-process (sync fallback)"
echo ""
echo -e "  Logs: ${YELLOW}logs/api.log${NC}  ${YELLOW}logs/celery_worker.log${NC}  ${YELLOW}logs/ui.log${NC}"
echo ""
echo -e "  Press ${RED}Ctrl+C${NC} to stop all services."
echo ""

wait
