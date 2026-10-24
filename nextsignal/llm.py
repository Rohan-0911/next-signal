"""Thin, swappable LLM wrapper. Default: Google Gemini API.

Env (put these in .env):  GOOGLE_API_KEY, optional NS_MODEL, NS_MIN_INTERVAL (seconds between calls, default 4)
"""
from __future__ import annotations
import json
import os
import re
import threading
import time

FALLBACK_MODELS = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]

# Visible health counters: a run with failed calls must never look like a clean run.
STATS = {"calls": 0, "failed": 0, "retries_429": 0}
_lock = threading.Lock()
_last_call = [0.0]


def _pace():
    """Space out requests so free-tier per-minute limits are not hit in a burst."""
    gap = float(os.environ.get("NS_MIN_INTERVAL", "4"))
    with _lock:
        wait = _last_call[0] + gap - time.time()
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.time()


def _retry_delay(err: str, default: float) -> float:
    """Gemini 429s say 'Please retry in 23.4s' or retryDelay: '23s'."""
    m = re.search(r"retry in ([\d.]+)\s*s", err, re.I) or re.search(r"retryDelay['\": ]+([\d.]+)s", err)
    return min(float(m.group(1)) + 1.5, 75.0) if m else default


def _is_quota(err: str) -> bool:
    return "429" in err or "RESOURCE_EXHAUSTED" in err or "Quota" in err


def complete(system: str, user: str, max_tokens: int = 4000, model: str | None = None) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    primary = model or os.environ.get("NS_MODEL", "gemini-3.5-flash-lite")
    candidates = [primary] + [m for m in FALLBACK_MODELS if m != primary]
    STATS["calls"] += 1

    last_err = None
    for target in candidates:
        for attempt in range(5):
            _pace()
            try:
                response = client.models.generate_content(
                    model=target, contents=user,
                    config=types.GenerateContentConfig(system_instruction=system, max_output_tokens=max_tokens, temperature=0.2),
                )
                return response.text or ""
            except Exception as e:
                err = str(e)
                last_err = e
                if _is_quota(err):
                    if "PerDay" in err or "per day" in err.lower():
                        break                                   # daily quota gone: waiting will not help, try next model
                    wait = _retry_delay(err, 15.0 * (attempt + 1))
                    STATS["retries_429"] += 1
                    print(f"[{target}] rate limited, waiting {wait:.0f}s (attempt {attempt + 1}/5)")
                    time.sleep(wait)
                    continue
                if any(x in err for x in ("503", "UNAVAILABLE", "getaddrinfo", "ConnectError", "timed out",
                                          "Timeout", "Connection", "reset", "DNS")):
                    time.sleep(2 * (attempt + 1))
                    continue
                break
    STATS["failed"] += 1
    raise last_err or RuntimeError("LLM request failed across all candidate models")


def complete_json(system: str, user: str, **kw):
    """Ask for JSON only; robustly tolerate code fences, leading/trailing prose, and trailing commas."""
    raw = complete(system + "\nReturn ONLY valid JSON, no prose.", user, **kw)
    # 1. Extract markdown code fence if present
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
    candidate = match.group(1).strip() if match else raw.strip()

    # 2. Extract outer object or array if surrounded by chatter
    start_brace = candidate.find("{")
    start_bracket = candidate.find("[")
    if start_brace != -1 and (start_bracket == -1 or start_brace < start_bracket):
        end_brace = candidate.rfind("}")
        if end_brace != -1:
            candidate = candidate[start_brace:end_brace + 1]
    elif start_bracket != -1:
        end_bracket = candidate.rfind("]")
        if end_bracket != -1:
            candidate = candidate[start_bracket:end_bracket + 1]

    # 3. Direct attempt
    try:
        return json.loads(candidate)
    except Exception:
        pass

    # 4. Remove trailing commas before } or ]
    fixed = re.sub(r",\s*([}\]])", r"\1", candidate)
    try:
        return json.loads(fixed)
    except Exception:
        pass

    # 5. Fallback clean
    clean = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    return json.loads(clean)
