#!/usr/bin/env bash
# start_worker.sh — Start Celery worker standalone
#
# Usage:
#   bash start_worker.sh           # foreground (logs to stdout)
#   bash start_worker.sh --detach  # background (logs to logs/celery_worker.log)
#   bash start_worker.sh --beat    # also start Beat scheduler for periodic tasks

set -euo pipefail

DETACH=false
WITH_BEAT=false

for arg in "$@"; do
  case $arg in
    --detach) DETACH=true ;;
    --beat)   WITH_BEAT=true ;;
  esac
done

# Load .env
if [ -f .env ]; then
  set -a
  source <(grep -v '^#' .env | grep -v '^$') 2>/dev/null || true
  set +a
fi

# Activate venv
[ -d ".venv311" ] && source .venv311/bin/activate

# Ensure content_engine is importable from any working directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="${SCRIPT_DIR}${PYTHONPATH:+:${PYTHONPATH}}"

REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"
CONCURRENCY="${CELERY_WORKER_CONCURRENCY:-1}"
MAX_TASKS="${CELERY_WORKER_MAX_TASKS_PER_CHILD:-50}"

echo "Starting Celery worker..."
echo "  Broker:      $REDIS_URL"
echo "  Concurrency: $CONCURRENCY"
echo "  Max tasks:   $MAX_TASKS per child"

mkdir -p logs

if [ "$DETACH" = true ]; then
  celery -A api.worker worker \
    --loglevel="$LOG_LEVEL" \
    --concurrency="$CONCURRENCY" \
    --max-tasks-per-child="$MAX_TASKS" \
    --hostname="worker@%h" \
    --detach \
    --logfile="logs/celery_worker.log" \
    --pidfile="logs/celery_worker.pid"
  echo "Worker started in background. Logs: logs/celery_worker.log"
else
  celery -A api.worker worker \
    --loglevel="$LOG_LEVEL" \
    --concurrency="$CONCURRENCY" \
    --max-tasks-per-child="$MAX_TASKS" \
    --hostname="worker@%h"
fi

# Optionally start Beat scheduler
if [ "$WITH_BEAT" = true ]; then
  echo "Starting Celery Beat scheduler..."
  celery -A api.worker beat \
    --loglevel="$LOG_LEVEL" \
    --schedule="logs/celerybeat-schedule" \
    --pidfile="logs/celery_beat.pid" &
  echo "Beat scheduler started (PID $!)"
fi
