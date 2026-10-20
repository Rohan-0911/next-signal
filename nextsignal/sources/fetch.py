"""Fetch + cache public documents and return plain text with page markers.

Only publicly accessible URLs. Results are cached on disk so a live demo can
fall back to previously fetched documents if the network is slow.
"""
from __future__ import annotations
import hashlib
import io
import pathlib
import re
import requests

CACHE = pathlib.Path(".cache/docs")
CACHE.mkdir(parents=True, exist_ok=True)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _key(url: str) -> pathlib.Path:
    return CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".txt")


def get_text(url: str, timeout: int = 10) -> str:
    p = _key(url)
    if p.exists():
        cached = p.read_text(encoding="utf-8", errors="ignore")
        if cached.strip():
            return cached
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    ctype = r.headers.get("content-type", "").lower()
    if url.lower().endswith(".pdf") or "pdf" in ctype:
        text = _pdf_text(r.content)
    else:
        text = _html_text(r.text)
    if text.strip():
        p.write_text(text, encoding="utf-8", errors="ignore")
    return text


def _pdf_text(blob: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(blob))
    return "\n".join(f"[[page {i+1}]]\n{(pg.extract_text() or '')}" for i, pg in enumerate(reader.pages))


def _html_text(html: str) -> str:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "nav", "footer"]):
        t.decompose()
    return re.sub(r"\n{3,}", "\n\n", soup.get_text("\n"))


def normalise(s: str) -> str:
    """Normalize text for quote matching: unify smart quotes, dashes, whitespace and lowercase."""
    s = s.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    s = s.replace("—", "-").replace("–", "-").replace("\u00a0", " ")
    return re.sub(r"\s+", " ", s).strip().lower()


def quote_in_document(quote: str, text: str) -> bool:
    """Anti-hallucination check: the cited quote must literally appear in the source."""
    if not quote or not text:
        return False
    nq, nt = normalise(quote), normalise(text)
    if nq in nt:
        return True
    # If the quote is enclosed in quotation marks or brackets, try stripping them
    stripped = nq.strip('"\'-()[]{}')
    if len(stripped) >= 10 and stripped in nt:
        return True
    return False
