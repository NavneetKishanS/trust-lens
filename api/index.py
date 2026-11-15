"""Vercel entry point for the TrustLens API (backup demo deployment).

Runs against the bundled DuckDB snapshot (data/trustlens.duckdb), copied to /tmp on cold start because the
function filesystem is read-only. LLM runs in stub mode, so no secrets are needed. Writes (audit events, reviews)
live only until the function instance is recycled.
"""
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP_DB = Path("/tmp/trustlens.duckdb")

if not TMP_DB.exists():
    shutil.copyfile(ROOT / "data" / "trustlens.duckdb", TMP_DB)
    wal = ROOT / "data" / "trustlens.duckdb.wal"
    if wal.exists():
        shutil.copyfile(wal, Path(str(TMP_DB) + ".wal"))

os.environ["DUCKDB_PATH"] = str(TMP_DB)
os.environ["EXASOL_DSN"] = ""
os.environ.setdefault("LLM_PROVIDER", "stub")
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from app.main import app  # noqa: E402

# The app only allows http://localhost:3000; the hosted frontend lives on another origin.
app.user_middleware = [m for m in app.user_middleware if m.cls is not CORSMiddleware]
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
                   expose_headers=["X-TrustLens-Stub"])
