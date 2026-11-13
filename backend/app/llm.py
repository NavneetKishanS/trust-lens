"""One way to call Claude, with three providers and a call log.

    result = llm.call(purpose="summary.generate", prompt_file="summary_patient.md",
                      variables={"facts": facts_json}, output_model=Summary, effort="medium",
                      stub=lambda: Summary(...))
    if not result.ok:  -> route to needs_review, never treat as OK

Providers (LLM_PROVIDER):
  stub       deterministic: returns stub() (default; the demo must always work)
  anthropic  Claude API, claude-opus-5-5, server-side refusal fallbacks enabled
  bedrock    Amazon Bedrock Mantle client in eu-central-1, anthropic.claude-opus-5-5

Opus 5.5 notes: thinking is always on (never send thinking={"type": "disabled"}); depth is
output_config.effort; no assistant prefill; no forced tool_choice. Structured output via messages.parse.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Generic, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from . import config
from .audit import now_iso
from .db import DB, get_db

T = TypeVar("T", bound=BaseModel)

MODEL_IDS = {"anthropic": "claude-opus-5-5", "bedrock": "anthropic.claude-opus-5-5", "stub": "stub"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"


@dataclass
class LLMResult(Generic[T]):
    parsed: T | None
    ok: bool
    meta: dict = field(default_factory=dict)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_prompt(prompt_file: str | Path) -> tuple[str, str]:
    """Return (template, prompt_hash). The hash is over the template file, so it is stable and reviewable."""
    path = Path(prompt_file)
    if not path.is_absolute():
        path = config.PROMPTS_DIR / path
    template = path.read_text()
    return template, sha256(template)


def render(template: str, variables: dict[str, Any]) -> str:
    """Replace {{name}} placeholders. Non-strings are JSON-encoded (sorted, so the input hash is stable)."""
    out = template
    for key, value in variables.items():
        text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
        out = out.replace("{{" + key + "}}", text)
    return out


_client: Any = None


def provider() -> str:
    return config.LLM_PROVIDER if config.LLM_PROVIDER in MODEL_IDS else "stub"


def _get_client():
    global _client
    if _client is None:
        if provider() == "bedrock":
            _client = anthropic.AnthropicBedrockMantle(aws_region=config.AWS_REGION)
        else:
            _client = anthropic.Anthropic()
    return _client


def _parse(prompt: str, output_model: type[T], effort: str, max_tokens: int):
    client = _get_client()
    common = dict(
        model=MODEL_IDS[provider()],
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
        output_format=output_model,
        output_config={"effort": effort},
    )
    if provider() == "anthropic":
        # Server-side refusal fallbacks: on a policy decline the API reruns the request on a fallback model.
        return client.beta.messages.parse(**common, betas=[FALLBACK_BETA], fallbacks="default")
    return client.messages.parse(**common)  # Bedrock: no server-side fallbacks; a refusal becomes needs_review


def call(
    purpose: str,
    prompt_file: str | Path,
    variables: dict[str, Any],
    output_model: type[T],
    stub: Callable[[], T],
    effort: str = "low",
    max_tokens: int = 16000,
    db: DB | None = None,
) -> LLMResult[T]:
    template, prompt_hash = load_prompt(prompt_file)
    prompt = render(template, variables)
    meta: dict[str, Any] = {
        "call_id": f"LLM-{uuid.uuid4().hex[:12]}", "purpose": purpose, "model": MODEL_IDS[provider()],
        "prompt_hash": prompt_hash, "input_hash": sha256(prompt), "stop_reason": None, "ok": False, "error": None,
    }
    started = time.monotonic()
    parsed: T | None = None
    try:
        if provider() == "stub":
            parsed = stub()
            meta.update(stop_reason="end_turn", ok=True)
        else:
            response = _parse(prompt, output_model, effort, max_tokens)
            meta["stop_reason"] = response.stop_reason
            meta["model"] = response.model
            if response.stop_reason == "refusal":
                category = getattr(response.stop_details, "category", None) if response.stop_details else None
                meta["error"] = f"refusal ({category})"
            elif response.stop_reason == "max_tokens":
                meta["error"] = "output truncated at max_tokens"
            elif response.parsed_output is None:
                meta["error"] = "no parsed output"
            else:
                parsed = response.parsed_output
                meta["ok"] = True
    except anthropic.RateLimitError as exc:
        meta["error"] = f"rate limited: {exc.message}"
    except anthropic.APIStatusError as exc:
        meta["error"] = f"API error {exc.status_code}: {exc.message}"
    except anthropic.APIConnectionError as exc:
        meta["error"] = f"connection error: {exc}"
    except ValidationError as exc:
        meta["error"] = f"output failed validation: {exc.error_count()} errors"
    except Exception as exc:  # never crash a request because the LLM failed; caller routes to needs_review
        meta["error"] = f"{type(exc).__name__}: {exc}"
    meta["latency_ms"] = int((time.monotonic() - started) * 1000)
    _log(meta, db)
    return LLMResult(parsed=parsed if meta["ok"] else None, ok=meta["ok"], meta=meta)


def _log(meta: dict, db: DB | None) -> None:
    try:
        (db or get_db()).insert_rows("gov.llm_calls", [{
            "call_id": meta["call_id"], "purpose": meta["purpose"], "model": meta["model"],
            "prompt_hash": meta["prompt_hash"], "input_hash": meta["input_hash"], "stop_reason": meta["stop_reason"],
            "latency_ms": meta["latency_ms"], "ok": meta["ok"], "error": (meta["error"] or "")[:2000] or None,
            "created_at": now_iso(),
        }])
    except Exception:
        pass  # logging must never break the call path
