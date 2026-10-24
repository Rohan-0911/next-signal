"""Screener.in public company pages as the numeric spine.

One page gives ~12 quarters of P&L, ~10 years of annual P&L and a ratios table that includes
Debtor Days, Inventory Days, Days Payable and Cash Conversion Cycle. That covers the
working-capital and margin divergence tests directly, and the same loader works for any
listed company (and for its peers), which is what makes peer-adjusted checks possible.

Be a good citizen: pages are cached on disk, requests are spaced out, volume is low. Check the
site's terms before relying on it beyond the hackathon. Any failure returns [] and the pipeline
falls back to other sources.

Parsing is deliberately generic (section id -> table -> header cells -> rows) so small layout
changes do not break it.
"""
from __future__ import annotations
import hashlib
import json
import pathlib
import re
import time
import requests
from ..models import Passage

BASE = "https://www.screener.in"
CACHE = pathlib.Path(".cache/screener")
CACHE.mkdir(parents=True, exist_ok=True)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
_MON = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

# (section id, is_quarterly) -> {normalised row label: metric}
SECTIONS = {
    "quarters": (True, {"sales": "revenue", "operating profit": "operating_profit", "opm": "ebitda_margin",
                        "other income": "other_income", "net profit": "net_profit", "expenses": "total_expenses"}),
    "profit-loss": (False, {"sales": "revenue", "operating profit": "operating_profit", "opm": "ebitda_margin",
                            "other income": "other_income", "net profit": "net_profit", "expenses": "total_expenses"}),
    "ratios": (False, {"debtor days": "debtor_days", "inventory days": "inventory_days",
                       "days payable": "payable_days", "cash conversion cycle": "cash_conversion_cycle",
                       "working capital days": "working_capital_days", "roce": "roce"}),
}


def _get(url: str, ttl_hours: float = 48) -> str:
    p = CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".html")
    if p.exists() and (time.time() - p.stat().st_mtime) < ttl_hours * 3600:
        return p.read_text(encoding="utf-8", errors="ignore")
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    p.write_text(r.text, encoding="utf-8", errors="ignore")
    time.sleep(1.0)
    return r.text


def resolve_url(company: str) -> str | None:
    """company name -> consolidated page URL via Screener's public search endpoint."""
    if re.fullmatch(r"[A-Z0-9&-]{2,20}", company.strip()):       # already a symbol
        return f"{BASE}/company/{company.strip()}/consolidated/"
    try:
        r = requests.get(f"{BASE}/api/company/search/", params={"q": company}, headers=HEADERS, timeout=15)
        for item in r.json():
            u = item.get("url", "")
            if u.startswith("/company/"):
                return BASE + (u if u.endswith("/") else u + "/")
    except Exception:
        pass
    return None


def _num(txt: str):
    t = txt.replace(",", "").replace("%", "").replace("\xa0", " ").strip()
    if t in ("", "-"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _norm_label(txt: str) -> str:
    t = txt.replace("\xa0", " ").replace("+", " ").lower()
    t = re.sub(r"[%]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def parse_tables(html: str) -> dict[str, dict]:
    """-> {section_id: {"headers": [...], "rows": {label: [cells]}}}"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    out = {}
    for sec_id in SECTIONS:
        sec = soup.find(id=sec_id)
        table = sec.find("table") if sec else None
        if not table:
            continue
        headers = [th.get_text(" ", strip=True) for th in table.find_all("th")]
        rows = {}
        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 2:
                continue
            label = _norm_label(tds[0].get_text(" ", strip=True))
            rows[label] = [td.get_text(" ", strip=True) for td in tds[1:]]
        out[sec_id] = {"headers": headers[1:] if headers and headers[0] == "" else headers, "rows": rows}
    return out


def _period(header: str, quarterly: bool):
    m = re.fullmatch(r"([A-Za-z]{3})[a-z]*\s+(\d{4})", header.strip())
    if not m or m.group(1).lower() not in _MON:      # skips "TTM" and anything odd
        return None
    mon, yr = _MON[m.group(1).lower()], int(m.group(2))
    if quarterly:
        return f"{m.group(1).title()} {yr}"          # period-end as printed; panel parser maps it to a fiscal quarter
    fy = yr if mon <= 3 else yr + 1
    return f"FY{fy % 100:02d}"


def points_from_html(html: str, url: str) -> list[dict]:
    pts = []
    for sec_id, tbl in parse_tables(html).items():
        quarterly, mapping = SECTIONS[sec_id]
        for label, cells in tbl["rows"].items():
            metric = next((m for key, m in mapping.items() if label == key or label.startswith(key + " ")), None)
            if not metric:
                continue
            for header, raw in zip(tbl["headers"], cells):
                per, val = _period(header, quarterly), _num(raw)
                if per is None or val is None:
                    continue
                quote = f"screener[{sec_id}][{label}][{header}] = {raw}"
                pts.append({"metric": metric, "period": per, "value": val, "unit": "%" if metric in
                            ("ebitda_margin", "roce") else ("days" if metric.endswith("_days") or metric == "cash_conversion_cycle" else "Rs crore"),
                            "passage": Passage(f"{url}#{sec_id}", "results", f"Screener {sec_id}", header, quote, verified=True)})
    return pts


def load_points(company: str, url: str | None = None) -> list[dict]:
    try:
        url = url or resolve_url(company)
        if not url:
            return []
        return points_from_html(_get(url), url)
    except Exception as e:
        print(f"       [screener] unavailable: {str(e)[:80]}")
        return []


def find_peers(html: str, limit: int = 4) -> list[str]:
    """Best effort: symbols linked from the page's peers block (if present in the HTML)."""
    syms = []
    for s in re.findall(r'href="/company/([A-Z0-9&-]+)/', html):
        if s not in syms:
            syms.append(s)
    return syms


def peers_for(html: str, own_url: str, limit: int = 4) -> list[str]:
    """Peer symbols from Screener's peers block (loaded by a small API call). Best effort."""
    own = re.search(r"/company/([A-Z0-9&-]+)/", own_url)
    own = own.group(1) if own else ""
    syms: list[str] = find_peers(html, limit + 5)
    m = re.search(r'data-warehouse-id="(\d+)"', html)
    if m:
        try:
            r = requests.get(f"{BASE}/api/company/{m.group(1)}/peers/", headers=HEADERS, timeout=15)
            syms = find_peers(r.text, limit + 5) or syms
        except Exception:
            pass
    return [x for x in syms if x != own][:limit]


def load(company: str):
    """-> (points, html, url). Empty points if unavailable."""
    try:
        url = resolve_url(company)
        if not url:
            return [], "", ""
        html = _get(url)
        return points_from_html(html, url), html, url
    except Exception as e:
        print(f"       [screener] unavailable: {str(e)[:80]}")
        return [], "", ""
