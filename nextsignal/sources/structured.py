"""Structured numeric spine from a public API (Yahoo Finance via the `yfinance` package).

Why: scraping numbers out of random web pages with an LLM is the least reliable step.
This gives period-labelled quarterly P&L and annual balance-sheet values directly, with
provenance (ticker, statement, row, column date). Text sources (press releases, transcripts)
are still used for volume growth, channel mix and management commentary.

Everything is wrapped so that a failure just returns [] and the pipeline falls back to
document extraction. Values are converted from INR to Rs crore (1 crore = 1e7).
"""
from __future__ import annotations
import math
from ..models import Passage

CRORE = 1e7
ROWS = {  # metric -> candidate row names (first match wins)
    "revenue": ["Total Revenue", "Operating Revenue"],
    "cogs": ["Cost Of Revenue"],
    "gross_profit": ["Gross Profit"],
    "ebitda": ["EBITDA", "Normalized EBITDA"],
    "operating_profit": ["Operating Income"],
}
BS_ROWS = {
    "trade_receivables": ["Accounts Receivable", "Receivables", "Net Receivables"],
    "inventory": ["Inventory"],
    "trade_payables": ["Accounts Payable", "Payables"],
}
_MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def resolve_symbol(company: str, yf) -> str | None:
    try:
        res = yf.Search(company, max_results=8).quotes
        for q in res:
            sym = q.get("symbol", "")
            if sym.endswith(".NS") and q.get("quoteType", "EQUITY") == "EQUITY":
                return sym
        for q in res:
            if q.get("symbol", "").endswith(".BO"):
                return q["symbol"]
    except Exception:
        pass
    return None


def _row(df, names):
    if df is None or getattr(df, "empty", True):
        return None
    for n in names:
        if n in df.index:
            return df.loc[n]
    return None


def _fy_label(ts) -> str:
    fy = ts.year if ts.month <= 3 else ts.year + 1
    return f"FY{fy % 100:02d}"


def _point(metric, period, value, unit, url, title, row, ts, raw):
    quote = f"yfinance[{row}][{ts.date()}] = {raw:,.0f} INR"
    return {"metric": metric, "period": period, "value": float(value), "unit": unit,
            "passage": Passage(url, "results", title, str(ts.date()), quote, verified=True)}


def points_from_ticker(t, symbol: str) -> list[dict]:
    url = f"https://finance.yahoo.com/quote/{symbol}/financials/"
    title = f"Yahoo Finance structured data ({symbol})"
    pts: list[dict] = []

    def emit(df, mapping, quarterly: bool):
        rows = {m: _row(df, names) for m, names in mapping.items()}
        for m, series in rows.items():
            if series is None:
                continue
            for ts, raw in series.items():
                if raw is None or (isinstance(raw, float) and math.isnan(raw)):
                    continue
                period = f"{_MON[ts.month - 1]} {ts.year}" if quarterly else _fy_label(ts)
                name = next(n for n in mapping[m] if n in df.index)
                pts.append(_point(m, period, raw / CRORE, "Rs crore", url, title, name, ts, raw))
        # derived margins, computed from the same statement and column
        rev = rows.get("revenue")
        if rev is not None:
            for key, out in (("ebitda", "ebitda_margin"), ("gross_profit", "gross_margin")):
                s = rows.get(key)
                if s is None:
                    continue
                for ts in rev.index:
                    r, v = rev.get(ts), s.get(ts)
                    if r and v is not None and not (isinstance(r, float) and math.isnan(r)) \
                            and not (isinstance(v, float) and math.isnan(v)):
                        period = f"{_MON[ts.month - 1]} {ts.year}" if quarterly else _fy_label(ts)
                        pts.append(_point(out, period, v / r * 100, "%", url, title, f"{key}/revenue", ts, v))

    for attr, mapping, q in (("quarterly_income_stmt", ROWS, True), ("income_stmt", ROWS, False),
                             ("balance_sheet", BS_ROWS, False)):
        try:
            emit(getattr(t, attr), mapping, q)
        except Exception:
            continue
    return pts


def load_points(company: str, symbol: str | None = None) -> list[dict]:
    try:
        import yfinance as yf
    except Exception:
        return []
    try:
        symbol = symbol or resolve_symbol(company, yf)
        if not symbol:
            return []
        return points_from_ticker(yf.Ticker(symbol), symbol)
    except Exception:
        return []
