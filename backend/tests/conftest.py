import os
import sys
from pathlib import Path

os.environ["LLM_PROVIDER"] = "stub"
os.environ["EXASOL_DSN"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from app import db as dbmod  # noqa: E402
from app.schema import ensure_gov_schema  # noqa: E402


@pytest.fixture()
def db():
    mem = dbmod.DuckDB(":memory:")
    dbmod.set_db(mem)
    ensure_gov_schema(mem)
    yield mem
    dbmod.set_db(None)
