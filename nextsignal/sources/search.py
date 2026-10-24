"""Search layer. Set TAVILY_API_KEY to use Tavily (recommended); otherwise falls back to DuckDuckGo.

* Search results are cached on disk (24h) so repeat runs cost no credits and a demo can survive a bad network.
* Tavily can return the page text itself (`include_raw_content`). We store that text in the document cache, so
  pages that return 403 to scripts (company IR sites) can still be read and their quotes verified.
* Source discovery is generic: per-company queries are templated by document type, never hard-coded to a company.
"""
from __future__ import annotations
import hashlib
import json
import os
import pathlib
import time

from .fetch import _key as _doc_cache_path

CACHE = pathlib.Path(".cache/search")
CACHE.mkdir(parents=True, exist_ok=True)

DOC_QUERIES = {
    "results": "{c} quarterly results financial screener consolidated summary",
    "presentation": "{c} investor presentation quarterly results volume growth",
    "transcript": "{c} earnings call transcript management commentary",
    "annual_report": "{c} annual report trade receivables financial notes",
    "filing": "{c} BSE NSE financial announcement filing",
    "industry": "{c} industry volume growth category FMCG market data",
    "news": "{c} distributors channel quick commerce growth analysis",
}


def _cache_get(query: str, n: int, ttl_h: float = 24):
    p = CACHE / (hashlib.sha1(f"{query}|{n}".encode()).hexdigest() + ".json")
    if p.exists() and (time.time() - p.stat().st_mtime) < ttl_h * 3600:
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _cache_put(query: str, n: int, res: list[dict]):
    p = CACHE / (hashlib.sha1(f"{query}|{n}".encode()).hexdigest() + ".json")
    p.write_text(json.dumps(res), encoding="utf-8")


def _tavily(query: str, n: int) -> list[dict]:
    import requests
    r = requests.post("https://api.tavily.com/search", json={
        "api_key": os.environ["TAVILY_API_KEY"], "query": query, "max_results": n,
        "include_raw_content": True, "search_depth": "basic"}, timeout=40)
    r.raise_for_status()
    out = []
    for x in r.json().get("results", []):
        raw = x.get("raw_content") or ""
        if len(raw) > 500:                         # page text delivered by Tavily: store it so fetch.get_text() uses it
            try:
                _doc_cache_path(x["url"]).write_text(raw, encoding="utf-8", errors="ignore")
            except Exception:
                pass
        out.append({"url": x["url"], "title": x.get("title", ""), "snippet": x.get("content", "")})
    return out


def search(query: str, n: int = 8) -> list[dict]:
    hit = _cache_get(query, n)
    if hit:
        return hit
    if os.environ.get("TAVILY_API_KEY"):
        try:
            res = _tavily(query, n)
            if res:
                _cache_put(query, n, res)
                return res
        except Exception as e:
            print(f"[search] Tavily failed ({str(e)[:60]}), falling back to DuckDuckGo")
    try:
        from ddgs import DDGS
        with DDGS(timeout=10) as d:
            res = [{"url": x["href"], "title": x["title"], "snippet": x["body"]} for x in d.text(query, max_results=n)]
        if res:
            _cache_put(query, n, res)
        return res
    except Exception as e:
        print(f"[search] DuckDuckGo query failed ({str(e)[:60]}), skipping: {query[:60]}")
        return []


def discover_sources(company: str, n_per_type: int = 5) -> dict[str, list[dict]]:
    return {t: search(q.format(c=company), n_per_type) for t, q in DOC_QUERIES.items()}
