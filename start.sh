#!/usr/bin/env bash
# Start TrustLens locally with one command: API (port 8000) + UI (port 3000). Ctrl+C stops both.
#
#   ./start.sh          use the real data if it is loaded (data/trustlens.duckdb or EXASOL_DSN), else a local demo DB
#   ./start.sh --demo   always use the local demo DB (data/trustlens_demo.duckdb, synthetic, safe to delete)
#   ./start.sh --reset  delete the local demo DB first and rebuild it
#
# Real data: load it once as described in README.md (app.load --reset + data/seed_signal.py), then run ./start.sh.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"

MODE="auto"
for arg in "$@"; do
  case "$arg" in
    --demo) MODE="demo" ;;
    --reset) MODE="demo"; rm -f "$ROOT/data/trustlens_demo.duckdb" "$ROOT/data/trustlens_demo.duckdb.wal" ;;
    -h|--help) sed -n 2,8p "$0"; exit 0 ;;
    *) echo "unknown option: $arg"; exit 1 ;;
  esac
done

# --- Python: repo-root .venv (README) or backend/.venv; create one if neither exists --------------------------
if [ -x "$ROOT/.venv/bin/python" ]; then PY="$ROOT/.venv/bin/python"
elif [ -x "$ROOT/backend/.venv/bin/python" ]; then PY="$ROOT/backend/.venv/bin/python"
else
  echo "[start] creating .venv and installing backend requirements ..."
  python3 -m venv "$ROOT/.venv"
  PY="$ROOT/.venv/bin/python"
  "$PY" -m pip install -q -r "$ROOT/backend/requirements.txt"
fi
"$PY" -c "import fastapi, duckdb, sqlglot, dotenv" 2>/dev/null || "$PY" -m pip install -q -r "$ROOT/backend/requirements.txt"

# --- Node deps -------------------------------------------------------------------------------------------------
if [ ! -d "$ROOT/frontend/node_modules" ]; then
  echo "[start] installing frontend packages (first run only) ..."
  (cd "$ROOT/frontend" && npm install --no-audit --no-fund)
fi

# --- Ports must be free (DuckDB also allows only one process per file) -----------------------------------------
for port in 8000 3000; do
  if lsof -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "[start] port $port is already in use. Stop the other server first (e.g. pkill -f uvicorn; pkill -f 'next dev')."
    exit 1
  fi
done

# --- Pick the database -----------------------------------------------------------------------------------------
if [ -z "${EXASOL_DSN:-}" ] && [ "$MODE" = "auto" ]; then
  if [ "$("$PY" "$ROOT/scripts/dev_setup.py" 2>/dev/null | tail -1)" != "real" ]; then MODE="demo"; fi
fi
if [ "$MODE" = "demo" ]; then
  export DUCKDB_PATH="$ROOT/data/trustlens_demo.duckdb"
  echo "[start] no real data loaded: using the local demo database ($DUCKDB_PATH)"
fi

"$PY" "$ROOT/scripts/dev_setup.py" prepare

# --- Run both; stop both on exit --------------------------------------------------------------------------------
cleanup() { trap - EXIT INT TERM; echo; echo "[start] stopping ..."; kill 0 2>/dev/null || true; }
trap cleanup EXIT INT TERM

(cd "$ROOT/backend" && "$PY" -m uvicorn app.main:app --port 8000 --log-level warning) &
(cd "$ROOT/frontend" && NEXT_PUBLIC_API_BASE="http://localhost:8000" npx next dev -p 3000) &

for _ in $(seq 1 60); do curl -s localhost:8000/health >/dev/null 2>&1 && break; sleep 0.5; done
echo
echo "  TrustLens Research Studio  →  http://localhost:3000"
echo "  API (Swagger)              →  http://localhost:8000/docs"
echo "  Ctrl+C stops both."
echo
wait
