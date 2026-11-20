#!/usr/bin/env bash
# Starts the Axiom dashboard on localhost.
#   ./start.sh            -> http://127.0.0.1:8000
#   ./start.sh 8080       -> http://127.0.0.1:8080
# The chat assistant reads LLM_API_KEY and LLM_MODEL from .env in this folder.
set -euo pipefail

cd "$(dirname "$0")"
PORT="${1:-8000}"
URL="http://127.0.0.1:${PORT}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is needed but was not found. Install it from https://www.python.org/downloads/ and try again."
  exit 1
fi

# Build the dashboard data the first time, or if the data folder was removed.
if [ ! -f "data/processed/kpis.json" ] || [ ! -f "dashboard/index.html" ]; then
  if [ ! -d "data/raw/full_export" ]; then
    echo "No data found: expected data/raw/full_export with the four Excel exports."
    exit 1
  fi
  echo "Building the dashboard data from the Excel exports (first run only)..."
  if ! python3 -c "import pandas, openpyxl" >/dev/null 2>&1; then
    echo "Installing the data libraries (pandas, openpyxl)..."
    python3 -m pip install --quiet pandas openpyxl
  fi
  python3 -m pipeline.run --input data/raw/full_export
fi

# Certificates for the chat assistant's secure connection (macOS Python installs sometimes lack them).
if ! python3 -c "import certifi" >/dev/null 2>&1; then
  echo "Installing the certificate bundle for the chat assistant..."
  python3 -m pip install --quiet certifi || echo "Could not install certifi; the chat may fail with a certificate error."
fi

if [ -f ".env" ] && grep -q '^LLM_API_KEY=.\+' .env; then
  echo "Chat assistant: LLM configured from .env"
else
  echo "Chat assistant: not configured (add LLM_API_KEY and LLM_MODEL to .env). Leadership questions still work."
fi

# Free the port if an earlier copy of the server is still running.
if command -v lsof >/dev/null 2>&1; then
  OLD_PID="$(lsof -ti tcp:"${PORT}" -sTCP:LISTEN || true)"
  if [ -n "${OLD_PID}" ]; then
    echo "Stopping the previous server on port ${PORT}..."
    kill ${OLD_PID} || true
    sleep 1
  fi
fi

echo "Starting the dashboard at ${URL}"
echo "Press Ctrl+C to stop."

# Open the browser once the server is up.
( sleep 2; if command -v open >/dev/null 2>&1; then open "${URL}"; elif command -v xdg-open >/dev/null 2>&1; then xdg-open "${URL}"; fi ) >/dev/null 2>&1 &

exec python3 -m api.server --port "${PORT}"
