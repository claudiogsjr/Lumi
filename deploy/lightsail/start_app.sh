#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/guardian-weather-watch}"
PORT="${PORT:-8080}"

cd "$APP_DIR"

if [ ! -x ".venv/bin/gunicorn" ]; then
  echo "Ambiente Python nao preparado. Execute deploy/lightsail/build_release.sh antes de iniciar." >&2
  exit 1
fi

if [ ! -f "frontend/dist/index.html" ]; then
  echo "Frontend nao buildado. Execute deploy/lightsail/build_release.sh antes de iniciar." >&2
  exit 1
fi

source .venv/bin/activate

exec .venv/bin/gunicorn \
  --workers 1 \
  --threads 4 \
  --timeout 180 \
  --bind "0.0.0.0:${PORT}" \
  --access-logfile - \
  --error-logfile - \
  --log-level warning \
  App:app
