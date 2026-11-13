"""Settings read from the environment (and a repo-root .env if present)."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")


def env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return value if value not in (None, "") else default


EXASOL_DSN = env("EXASOL_DSN")
EXASOL_USER = env("EXASOL_USER", "sys")
EXASOL_PASSWORD = env("EXASOL_PASSWORD")
DUCKDB_PATH = env("DUCKDB_PATH", str(REPO_ROOT / "data" / "trustlens.duckdb"))

LLM_PROVIDER = env("LLM_PROVIDER", "stub").lower()
AWS_REGION = env("AWS_REGION", "eu-central-1")
# Bedrock: "runtime" = classic bedrock-runtime client (works in the AWS Workshop Studio sandbox, needs an inference
# profile ID such as us.anthropic.claude-opus-5-5); "mantle" = the newer Messages-API endpoint (anthropic.claude-opus-5-5).
BEDROCK_CLIENT = env("BEDROCK_CLIENT", "runtime").lower()
BEDROCK_MODEL_ID = env("BEDROCK_MODEL_ID",
                       "anthropic.claude-opus-5-5" if BEDROCK_CLIENT == "mantle" else "us.anthropic.claude-opus-5-5")

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
