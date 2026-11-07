#!/usr/bin/env bash
# start_dev.sh — Dev startup (API + UI + optional Celery worker)
# Jobs fall back to APScheduler in-process mode when Redis is unavailable.
#
# Usage: bash start_dev.sh           # API + UI only (APScheduler backend)
#        bash start_dev.sh --celery  # API + UI + Celery worker

set -euo pipefail

# ── Virtual environment ───────────────────────────────────────────────────────
if [ ! -d ".venv311" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv311
fi
source .venv311/bin/activate

# Minimal deps check
python -c "import fastapi, uvicorn" 2>/dev/null || {
  echo "Installing core dependencies..."
  pip install fastapi "uvicorn[standard]" python-multipart python-dotenv --quiet
}

mkdir -p uploads output logs

echo ""
echo "Starting FastAPI backend on http://localhost:8000 ..."
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000 2>&1 | tee -a logs/api.log &
BACKEND_PID=$!

if [ "${1:-}" = "--celery" ]; then
  echo "Starting Celery worker (solo pool for Apple Silicon) ..."
  nohup .venv311/bin/celery -A api.worker worker --loglevel=INFO --concurrency=1 --pool=solo \
    > logs/celery_worker.log 2>&1 &
  CELERY_PID=$!
  echo "  Celery   → PID $CELERY_PID  (logs/celery_worker.log)"
fi

echo "Starting ML Test UI on http://localhost:5173 ..."

echo "Starting ML Test UI on http://localhost:5173 ..."
npm run dev --prefix ml_test_ui 2>&1 | tee -a logs/ui.log &
FRONTEND_PID=$!

echo ""
echo "  Backend    → http://localhost:8000"
echo "  API Docs   → http://localhost:8000/docs"
echo "  ML Test UI → http://localhost:5173"
echo ""
echo "Press Ctrl+C to stop both."

trap "kill $BACKEND_PID $FRONTEND_PID ${CELERY_PID:-} 2>/dev/null; exit" INT TERM
wait
