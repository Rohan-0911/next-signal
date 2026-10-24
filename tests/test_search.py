import json
from nextsignal.sources import search as S, fetch as F


class Resp:
    def raise_for_status(self): pass
    def json(self): return {"results": [{"url": "https://blocked.example.com/pr", "title": "PR", "content": "snip",
                                         "raw_content": "Underlying volume growth was 4% in the quarter. " * 30}]}


def test_tavily_raw_content_lands_in_document_cache_and_results_are_cached(monkeypatch, tmp_path):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.setattr(S, "CACHE", tmp_path)
    monkeypatch.setattr(F, "CACHE", tmp_path)
    monkeypatch.setattr(S, "_doc_cache_path", lambda url: tmp_path / "doc.txt")
    calls = []
    import requests
    monkeypatch.setattr(requests, "post", lambda *a, **k: calls.append(1) or Resp())
    r1 = S.search("hul volume growth", 3)
    r2 = S.search("hul volume growth", 3)             # served from the search cache: no second API call
    assert r1 == r2 and len(calls) == 1
    assert "Underlying volume growth" in (tmp_path / "doc.txt").read_text()
