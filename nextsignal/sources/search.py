"""Search layer. Pluggable: default uses DuckDuckGo (no key); set TAVILY_API_KEY to use Tavily.

Source discovery is generic: per-company queries are templated by document type,
never hard-coded to a company.

Note: the old 'duckduckgo_search' package has been renamed to 'ddgs'.
"""
from __future__ import annotations
import os

DOC_QUERIES = {
    "results": "{c} quarterly results financial screener consolidated summary",
    "presentation": "{c} investor presentation quarterly results volume growth",
    "transcript": "{c} earnings call transcript management commentary",
    "annual_report": "{c} annual report trade receivables financial notes",
    "filing": "{c} BSE NSE financial announcement filing",
    "industry": "{c} industry volume growth category FMCG market data",
    "news": "{c} distributors channel quick commerce growth analysis",
}


def search(query: str, n: int = 8) -> list[dict]:
    if os.environ.get("TAVILY_API_KEY"):
        import requests
        r = requests.post("https://api.tavily.com/search", json={
            "api_key": os.environ["TAVILY_API_KEY"], "query": query, "max_results": n}, timeout=30)
        return [{"url": x["url"], "title": x["title"], "snippet": x.get("content", "")}
                for x in r.json().get("results", [])]
    try:
        from ddgs import DDGS
        with DDGS(timeout=10) as d:
            return [{"url": x["href"], "title": x["title"], "snippet": x["body"]}
                    for x in d.text(query, max_results=n)]
    except Exception as e:
        print(f"[search] DuckDuckGo query failed ({e!r}), skipping: {query[:60]}")
        return []


def discover_sources(company: str, n_per_type: int = 5) -> dict[str, list[dict]]:
    return {t: search(q.format(c=company), n_per_type) for t, q in DOC_QUERIES.items()}
