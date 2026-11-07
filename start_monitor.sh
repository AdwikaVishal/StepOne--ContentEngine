#!/usr/bin/env bash
# start_monitor.sh — Start Flower Celery monitoring dashboard
#
# Usage: bash start_monitor.sh
# Dashboard: http://localhost:5555

set -euo pipefail

# Load .env
if [ -f .env ]; then
  set -a
  source <(grep -v '^#' .env | grep -v '^$') 2>/dev/null || true
  set +a
fi

[ -d ".venv311" ] && source .venv311/bin/activate

REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"
FLOWER_PORT="${FLOWER_PORT:-5555}"
FLOWER_USER="${FLOWER_USER:-admin}"
FLOWER_PASSWORD="${FLOWER_PASSWORD:-admin}"

echo "Starting Flower monitoring dashboard..."
echo "  URL:    http://localhost:$FLOWER_PORT"
echo "  Broker: $REDIS_URL"

mkdir -p logs

celery -A api.worker flower \
  --port="$FLOWER_PORT" \
  --broker="$REDIS_URL" \
  --basic_auth="${FLOWER_USER}:${FLOWER_PASSWORD}" \
  --logfile="logs/flower.log" \
  --loglevel=info
