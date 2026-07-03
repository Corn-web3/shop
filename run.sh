#!/usr/bin/env bash
# One-command launcher for SSB Listing Studio.
#   ./run.sh              start on :8077
#   ./run.sh 9000         start on a custom port
#   PORT=9000 ./run.sh    same, via env
set -euo pipefail
cd "$(dirname "$0")"

PORT="${1:-${PORT:-8077}}"

# Prefer the project venv; fall back to system python3.
if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
else
  PY="python3"
fi

echo "SSB Listing Studio → http://localhost:${PORT}/  (docs: /docs)"
exec "$PY" -m uvicorn app.main:app --port "$PORT" --reload
