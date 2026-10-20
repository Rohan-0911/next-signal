"""Thin, swappable LLM wrapper. Default: Google Gemini API (free tier).

Set GOOGLE_API_KEY (from https://aistudio.google.com/apikey) to use.
Override the model via NS_MODEL env var (default: gemini-3.8-flash).
"""
from __future__ import annotations
import json
import os
import re


FALLBACK_MODELS = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]


def complete(system: str, user: str, max_tokens: int = 4000, model: str | None = None) -> str:
    """Call the Gemini API and return the response text with backoff and model fallback."""
    import time
    # pyrefly: ignore[missing-import]
    from google import genai
    # pyrefly: ignore[missing-import]
    from google.genai import types

    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    primary_model = model or os.environ.get("NS_MODEL", "gemini-3.5-flash-lite")
    candidates = [primary_model] + [m for m in FALLBACK_MODELS if m != primary_model]

    last_err = None
    for target_model in candidates:
        for attempt in range(2):
            try:
                response = client.models.generate_content(
                    model=target_model,
                    contents=user,
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                        max_output_tokens=max_tokens,
                        temperature=0.2,          # low temperature for factual research tasks
                    ),
                )
                return response.text or ""
            except Exception as e:
                err_str = str(e)
                last_err = e
                # Quota exhausted: never retry, immediately move to next model
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "Quota" in err_str:
                    break
                # Transient 503 spike: backoff once
                if "503" in err_str or "UNAVAILABLE" in err_str:
                    print(f"[{target_model}] Spiked ({err_str[:40]}...), retrying in 2s...")
                    time.sleep(2)
                else:
                    break

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
