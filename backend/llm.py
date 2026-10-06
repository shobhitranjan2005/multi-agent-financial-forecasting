"""Gemini client. Every LLM call in the project goes through here.

Responsibilities, in the order they matter for the research question:

1. Structured output  — a Pydantic schema in, a validated instance out.
2. Caching            — identical prompts cost nothing on re-run, so ablation
                        sweeps do not burn quota. Phase 4 variance runs MUST pass
                        a unique `nonce` or repeats hit the cache and report zero
                        variance, which is an artifact rather than a finding.
3. Cost accounting    — tokens, calls, seconds per forecast. "Is the debate worth
                        its cost?" is half the research question and cannot be
                        answered without measuring this.
4. Parse failures     — counted and reported, never silently retried away. The
                        rate is a number in the report.

Gemini structured-output constraints this module works around (see Task 3.1):
  - Gemini rejects schemas containing `Field(default=...)`. Schemas therefore use
    Optional[...] and post-process; see agents/schemas.py.
  - Deeply nested models are sometimes misread as tool calls. Schemas stay flat.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from backend.cache import get_cache
from backend.config import Config, require_gemini_key

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """Non-retryable LLM failure."""


class LLMRateLimit(RuntimeError):
    """429 / quota exhaustion — retryable with backoff."""


@dataclass
class Usage:
    """Running cost tally. Reset per forecast to get cost-per-forecast."""

    calls: int = 0
    cached_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    seconds: float = 0.0
    parse_failures: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def add(self, other: "Usage") -> None:
        self.calls += other.calls
        self.cached_calls += other.cached_calls
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.seconds += other.seconds
        self.parse_failures += other.parse_failures

    def as_dict(self) -> dict:
        return {
            "calls": self.calls,
            "cached_calls": self.cached_calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "seconds": round(self.seconds, 2),
            "parse_failures": self.parse_failures,
        }


@dataclass
class LLMResult:
    text: str
    model: str
    usage: Usage = field(default_factory=Usage)
    parsed: Optional[BaseModel] = None
    parse_error: Optional[str] = None
    from_cache: bool = False


# Module-level tally so a whole pipeline run can be costed without threading a
# counter through every function signature.
#
# The lock is load-bearing: the four specialists run as a genuine parallel fan-out
# in the LangGraph pipeline, so four threads call add() on this object. "calls +=
# 1" is a load-add-store, not an atomic operation, and a lost update here would
# under-report the token cost of exactly the configuration whose cost the research
# question is about.
_session_usage = Usage()
_usage_lock = threading.Lock()


def session_usage() -> Usage:
    return _session_usage


def reset_session_usage() -> None:
    global _session_usage
    with _usage_lock:
        _session_usage = Usage()


_client = None


def _get_client():
    """Lazy client. Importing this module must not require a key —
    schemas, tests and the data layer are all usable without one."""
    global _client
    if _client is None:
        from google import genai  # imported lazily so `import backend.llm` stays cheap

        _client = genai.Client(api_key=require_gemini_key())
    return _client


# --- client-side pacing -----------------------------------------------------
# Free-tier Gemini allows ~15 requests/minute PER MODEL. The four specialists run
# in parallel, so without pacing the quota is blown at once. One process-wide
# slot clock keeps every thread under LLM_MAX_RPM (default 12). Cache hits never
# reach here, so a resumed experiment only spends quota on genuinely new calls.
_throttle_lock = threading.Lock()
_next_slot = 0.0


def _throttle() -> None:
    global _next_slot
    interval = 60.0 / max(1.0, float(os.getenv("LLM_MAX_RPM", "12")))
    with _throttle_lock:
        now = time.monotonic()
        wait = max(0.0, _next_slot - now)
        _next_slot = max(now, _next_slot) + interval
    if wait:
        time.sleep(wait)


def _penalise(exc: Exception) -> None:
    """Honour the server's retry delay for ALL threads, not just the failing one."""
    global _next_slot
    m = re.search(r"retry in ([0-9.]+)s", str(exc), re.I) or re.search(r"retryDelay\W+(\d+)s", str(exc))
    delay = float(m.group(1)) + 1.0 if m else 15.0
    with _throttle_lock:
        _next_slot = max(_next_slot, time.monotonic() + delay)


def _is_rate_limit(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(s in text for s in ("429", "503", "resource_exhausted", "quota", "rate limit", "unavailable", "high demand"))


@retry(
    retry=retry_if_exception_type(LLMRateLimit),
    wait=wait_exponential(multiplier=2, min=4, max=60),
    stop=stop_after_attempt(6),
    reraise=True,
)
def _call_gemini(
    prompt: str,
    model: str,
    system: Optional[str],
    temperature: float,
    schema: Optional[Type[BaseModel]],
) -> tuple[str, int, int]:
    """One raw Gemini call. Returns (text, prompt_tokens, completion_tokens)."""
    from google.genai import types

    client = _get_client()
    cfg: dict[str, Any] = {"temperature": temperature}
    if system:
        cfg["system_instruction"] = system
    if schema is not None:
        # Ask for JSON conforming to the Pydantic schema. The SDK converts the
        # model class into a response schema for us.
        cfg["response_mime_type"] = "application/json"
        cfg["response_schema"] = schema

    _throttle()
    try:
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(**cfg),
        )
    except Exception as exc:  # SDK raises provider-specific errors
        if _is_rate_limit(exc):
            if "perday" in str(exc).lower():   # daily cap: retrying within the day is pointless
                raise LLMError(
                    "Daily Gemini quota exhausted. Progress is cached; rerun the same command "
                    "tomorrow (or enable billing). " + str(exc)[:200]
                ) from exc
            _penalise(exc)
            raise LLMRateLimit(str(exc)) from exc
        raise LLMError(f"{type(exc).__name__}: {exc}") from exc

    text = (resp.text or "").strip()
    pt = ct = 0
    meta = getattr(resp, "usage_metadata", None)
    if meta is not None:
        pt = getattr(meta, "prompt_token_count", 0) or 0
        ct = getattr(meta, "candidates_token_count", 0) or 0
    return text, pt, ct


def _strip_code_fence(text: str) -> str:
    """Models sometimes wrap JSON in ```json fences despite the mime type."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1] if "\n" in t else t
        if t.endswith("```"):
            t = t[: -3]
        # drop a leading 'json' language tag left behind by the split
        if t.lstrip().startswith("json\n"):
            t = t.lstrip()[5:]
    return t.strip()


def generate(
    prompt: str,
    *,
    model: Optional[str] = None,
    system: Optional[str] = None,
    temperature: float = 0.0,
    schema: Optional[Type[T]] = None,
    nonce: str = "",
    use_cache: bool = True,
) -> LLMResult:
    """Call Gemini, optionally parsing into `schema`.

    `nonce` busts the cache. Phase 4 variance runs pass a unique nonce per repeat;
    without it every repeat is a cache hit and the reported variance is zero.
    """
    model = model or Config.GEMINI_MODEL
    schema_name = schema.__name__ if schema is not None else "text"
    # System prompt and temperature change the output, so they belong in the key.
    cache_key_prompt = f"{system or ''}\n---\n{prompt}\n---\nT={temperature}\nS={schema_name}"

    started = time.time()
    was_cached = {"hit": True}  # loader() only runs on a miss, which flips this

    def loader() -> dict:
        was_cached["hit"] = False
        text, pt, ct = _call_gemini(prompt, model, system, temperature, schema)
        return {"text": text, "prompt_tokens": pt, "completion_tokens": ct}

    if use_cache:
        payload = get_cache().llm(cache_key_prompt, model, loader, nonce=nonce)
    else:
        was_cached["hit"] = False
        payload = loader()

    elapsed = time.time() - started
    from_cache = was_cached["hit"]

    usage = Usage(
        calls=1,
        cached_calls=1 if from_cache else 0,
        # A cache hit costs no tokens. Counting them would overstate the cost of
        # any re-run and make the debate look more expensive than it is.
        prompt_tokens=0 if from_cache else payload.get("prompt_tokens", 0),
        completion_tokens=0 if from_cache else payload.get("completion_tokens", 0),
        seconds=elapsed,
    )

    result = LLMResult(
        text=payload.get("text", ""),
        model=model,
        usage=usage,
        from_cache=from_cache,
    )

    if schema is not None:
        try:
            raw = json.loads(_strip_code_fence(result.text))
            result.parsed = schema.model_validate(raw)
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            # Counted, not silently retried — the failure rate is a reported metric.
            result.parse_error = f"{type(exc).__name__}: {exc}"
            usage.parse_failures = 1

    with _usage_lock:
        _session_usage.add(usage)
    return result


def generate_structured(
    prompt: str,
    schema: Type[T],
    *,
    model: Optional[str] = None,
    system: Optional[str] = None,
    temperature: float = 0.0,
    nonce: str = "",
    use_cache: bool = True,
) -> T:
    """Like `generate`, but returns the validated model or raises.

    Use where a missing report should abort the run; use `generate` where a parse
    failure should be recorded and tolerated.
    """
    res = generate(
        prompt,
        model=model,
        system=system,
        temperature=temperature,
        schema=schema,
        nonce=nonce,
        use_cache=use_cache,
    )
    if res.parsed is None:
        raise LLMError(
            f"{schema.__name__} parse failed: {res.parse_error}\n"
            f"--- raw response ---\n{res.text[:800]}"
        )
    return res.parsed  # type: ignore[return-value]


def is_configured() -> bool:
    """True if a Gemini key is present. Lets the CLI fail with a helpful message
    instead of a stack trace, and lets tests skip LLM paths cleanly."""
    key = Config.GEMINI_API_KEY
    return bool(key) and key != "your_gemini_key_here"
