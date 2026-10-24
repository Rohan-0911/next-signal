"""Build a clean, period-aligned panel from extracted data points, and decide whether
there is enough verified data to justify forming a hypothesis at all.

Why this exists: earlier runs mixed 'Jun 2026' with 'FY25-Q1' labels, sorted periods as
strings, zipped series that covered different quarters, and let a stray value ('5' for
revenue) into the trend. Hypotheses built on that were wrong or invented.
"""
from __future__ import annotations
from statistics import median
from ..tools import metrics
from ..tools.periods import parse_period, label, yoy_key

DOC_PRIORITY = {"results": 0, "presentation": 1, "annual_report": 2, "transcript": 3, "news": 4}
# Metrics that are levels (should be same order of magnitude across quarters)
LEVEL_METRICS = {"revenue", "operating_profit", "cogs", "trade_receivables", "inventory", "trade_payables"}
MIN_QUARTERS = 4


def build_panel(points: list[dict]) -> dict:
    """points: [{metric, period, value, passage(with doc_type)}] -> {metric: {key: value}} + notes."""
    notes: list[str] = []
    best: dict[str, dict[tuple, tuple[int, float]]] = {}
    for p in points:
        key = parse_period(p.get("period", ""))
        if key is None:
            notes.append(f"dropped {p.get('metric')} with unparseable period {p.get('period')!r}")
            continue
        try:
            val = float(p["value"])
        except (TypeError, ValueError):
            continue
        prio = DOC_PRIORITY.get(getattr(p.get("passage"), "doc_type", "news"), 5)
        cur = best.setdefault(p["metric"], {}).get(key)
        if cur is None or prio < cur[0]:
            if cur is not None and abs(cur[1] - val) > 0.02 * max(abs(cur[1]), 1e-9):
                notes.append(f"conflict {p['metric']} {label(key)}: kept {val} over {cur[1]}")
            best[p["metric"]][key] = (prio, val)
        elif abs(cur[1] - val) > 0.02 * max(abs(cur[1]), 1e-9):
            notes.append(f"conflict {p['metric']} {label(key)}: kept {cur[1]} over {val}")

    panel = {m: {k: v for k, (_, v) in d.items()} for m, d in best.items()}

    # Outlier guard for level metrics: a quarterly value <15% or >6x the median is almost
    # certainly a unit / table-parsing error, so drop it and say so.
    for m in list(panel):
        if m in LEVEL_METRICS:
            q = {k: v for k, v in panel[m].items() if k[1] > 0}
            if len(q) >= 3:
                med = median(q.values())
                for k, v in q.items():
                    if med and (v < 0.15 * med or v > 6 * med):
                        notes.append(f"dropped outlier {m} {label(k)}={v} (median {med:g})")
                        del panel[m][k]
    # Duplicate-value guard: the same large level value in two different quarters almost always means
    # one period was mislabelled (e.g. calendar vs fiscal naming). Keep neither rather than guess.
    for m in LEVEL_METRICS:
        q = {k: v for k, v in panel.get(m, {}).items() if k[1] > 0}
        seen: dict[float, list] = {}
        for k, v in q.items():
            seen.setdefault(round(v, 1), []).append(k)
        for v, ks in seen.items():
            if len(ks) > 1 and abs(v) > 100:
                notes.append(f"dropped ambiguous {m}={v:g}: same value labelled {', '.join(label(k) for k in ks)}")
                for k in ks:
                    del panel[m][k]
    return {"panel": panel, "notes": notes}


def quarterly(panel: dict, metric: str) -> dict[tuple, float]:
    return {k: v for k, v in sorted(panel.get(metric, {}).items()) if k[1] > 0}


def annual(panel: dict, metric: str) -> dict[tuple, float]:
    return {k: v for k, v in sorted(panel.get(metric, {}).items()) if k[1] == 0}


def derive(panel: dict) -> dict:
    """Deterministic derived series. Revenue growth is computed from revenue levels when
    the same quarter of the previous year exists (never mixed by position)."""
    out = {}
    rev = quarterly(panel, "revenue")
    g = {}
    for k, v in rev.items():
        prev = rev.get(yoy_key(k))
        if prev:
            g[k] = (v / prev - 1) * 100
    if g:
        out["revenue_growth_yoy_derived"] = g

    # Price/volume split aligned BY PERIOD (reported growth preferred over derived)
    rg = {**g, **quarterly(panel, "revenue_growth_yoy")}
    vg = quarterly(panel, "volume_growth_yoy")
    common = sorted(set(rg) & set(vg))
    if common:
        out["price_vs_volume_split"] = [
            {"period": label(k), **metrics.price_volume_split(rg[k] / 100, vg[k] / 100)} for k in common
        ]
    # Annual revenue: use reported, else sum of four quarters of that FY
    arev = dict(annual(panel, "revenue"))
    for fy in {k[0] for k in rev}:
        if (fy, 0) not in arev and all((fy, q) in rev for q in (1, 2, 3, 4)):
            arev[(fy, 0)] = sum(rev[(fy, q)] for q in (1, 2, 3, 4))
    # Annual working-capital days: year-end balance / full-year flow * 365
    acogs = annual(panel, "cogs")
    arec, ainv, apay = annual(panel, "trade_receivables"), annual(panel, "inventory"), annual(panel, "trade_payables")
    rd = {k: metrics.receivable_days(arec[k], arev[k], 365) for k in arec if arev.get(k)}
    idays = {k: metrics.inventory_days(ainv[k], acogs[k], 365) for k in ainv if acogs.get(k)}
    pdays = {k: metrics.payable_days(apay[k], acogs[k], 365) for k in apay if acogs.get(k)}
    if rd:
        out["receivable_days_annual"] = rd
    if idays:
        out["inventory_days_annual"] = idays
    if pdays:
        out["payable_days_annual"] = pdays
    ccc = {k: metrics.cash_conversion_cycle(rd[k], idays[k], pdays[k]) for k in rd if k in idays and k in pdays}
    if ccc:
        out["cash_conversion_cycle_annual"] = ccc
    if len(arev) >= 2:
        out["annual_revenue"] = dict(sorted(arev.items()))

    # Working capital days (period-matched revenue, quarterly => 91 days)
    rec = quarterly(panel, "trade_receivables")
    days = {k: metrics.receivable_days(rec[k], rev[k], 91) for k in rec if k in rev and rev[k]}
    if days:
        out["receivable_days"] = days
    return out


def summarise(panel: dict, derived: dict) -> dict:
    """Shape consumed by the LLM and by report/render.py (periods/values/slope/consistency)."""
    computed: dict = {}
    for m in panel:
        q = quarterly(panel, m)
        if not q:
            continue
        vals = list(q.values())
        computed[m] = {"periods": [label(k) for k in q], "values": vals, **metrics.trend(vals)}
    for m in panel:
        a = annual(panel, m)
        if len(a) >= 2:
            vals = list(a.values())
            computed[f"{m}_annual"] = {"periods": [label(k) for k in a], "values": vals, **metrics.trend(vals)}
    for name, series in derived.items():
        if name == "price_vs_volume_split":
            computed[name] = series
            computed["volume_negative_quarters"] = sum(1 for s in series if s["volume_growth"] < 0)
        else:
            vals = list(series.values())
            computed[name] = {"periods": [label(k) for k in series], "values": [round(v, 2) for v in vals],
                              **metrics.trend(vals)}
    return computed


def enough_data(panel: dict, derived: dict) -> tuple[bool, str]:
    """Gate: refuse to hypothesise on thin data."""
    q_counts = {m: len(quarterly(panel, m)) for m in panel}
    good = [m for m, n in q_counts.items() if n >= MIN_QUARTERS]
    aligned = len(derived.get("price_vs_volume_split", []))
    if len(good) >= 2 or aligned >= 3 or any(v == "run" for v in coverage(panel, derived).values()):
        return True, f"{len(good)} metrics with >={MIN_QUARTERS} quarters; {aligned} aligned price/volume quarters"
    return False, (f"only {len(good)} metric(s) have >={MIN_QUARTERS} verified quarters and {aligned} aligned "
                   f"price/volume quarters; need 2 metrics or 3 aligned quarters")


TEST_NEEDS = {
    "price_vs_volume": ("aligned price/volume quarters >= 3", "investor presentation quarterly volume growth UVG underlying volume growth"),
    "working_capital_vs_revenue": ("annual receivable days for >= 3 years", "annual report balance sheet trade receivables inventories trade payables cost of materials"),
    "margin_quality": ("EBITDA or gross margin for >= 4 quarters", "quarterly results gross margin EBITDA margin advertising and promotion expenses"),
    "channel_shift": ("channel mix % for >= 3 periods", "earnings call transcript quick commerce modern trade ecommerce share of sales"),
    "segment_mix_shift": ("segment revenue for >= 3 periods", "segment results revenue by segment home care beauty foods annual report"),
}


def coverage(panel: dict, derived: dict) -> dict:
    """Which generic divergence tests had enough verified data to run, and what is missing."""
    cov = {}
    cov["price_vs_volume"] = len(derived.get("price_vs_volume_split", [])) >= 3
    cov["working_capital_vs_revenue"] = (len(derived.get("receivable_days_annual", {})) >= 3
                                         or len(derived.get("receivable_days", {})) >= 4
                                         or len(annual(panel, "debtor_days")) >= 3)
    cov["margin_quality"] = any(len(quarterly(panel, m)) >= 4 for m in ("ebitda_margin", "gross_margin"))
    def series_ok(prefix):
        return any(m.startswith(prefix) and (len(quarterly(panel, m)) >= 3 or len(annual(panel, m)) >= 3) for m in panel)
    cov["channel_shift"] = series_ok("channel_mix_pct")
    cov["segment_mix_shift"] = series_ok("segment_revenue")
    return {t: ("run" if ok else f"skipped: need {TEST_NEEDS[t][0]}") for t, ok in cov.items()}


def missing_tests(panel: dict, derived: dict) -> list[str]:
    return [t for t, v in coverage(panel, derived).items() if v != "run"]


def rich_enough(panel: dict, derived: dict) -> bool:
    """Target (not minimum): at least 3 of the 5 tests can run."""
    return sum(1 for v in coverage(panel, derived).values() if v == "run") >= 3


def key_changes(panel: dict) -> dict:
    """Comparable, company-agnostic change measures used for peer comparison."""
    out = {"opm_yoy_chg": None, "revenue_growth_latest": None}
    for m in ("debtor_days", "inventory_days", "payable_days", "cash_conversion_cycle"):
        a = list(annual(panel, m).values())
        out[f"{m}_chg_3y"] = (a[-1] - a[-4]) if len(a) >= 4 else ((a[-1] - a[0]) if len(a) == 3 else None)
    opm = quarterly(panel, "ebitda_margin")
    if opm:
        k = max(opm)
        prev = opm.get((k[0] - 1, k[1]))
        if prev is not None:
            out["opm_yoy_chg"] = opm[k] - prev
    rev = quarterly(panel, "revenue")
    if rev:
        k = max(rev)
        prev = rev.get((k[0] - 1, k[1]))
        if prev:
            out["revenue_growth_latest"] = (rev[k] / prev - 1) * 100
    return out


def peer_check(company_panel: dict, peer_panels: list[dict]) -> dict:
    """Is the move company-specific or shared by peers? z>=~1.5 suggests company-specific."""
    mine = key_changes(company_panel)
    peers = [key_changes(p) for p in peer_panels]
    out = {}
    for m, v in mine.items():
        pv = [x[m] for x in peers if x[m] is not None]
        if v is None or len(pv) < 2:
            continue
        g = metrics.peer_adjusted_gap(v, pv)
        # With fewer than 5 peers a z-score is noise (tiny peer spread gives z of -59); report rank instead.
        z = None if (g["z"] is None or len(pv) < 5) else round(g["z"], 2)
        out[m] = {"company": round(v, 2), "peer_mean": round(g["peer_mean"], 2), "peers_n": len(pv),
                  "gap": round(g["gap"], 2), "z": z, "above_n_of_m": f"{sum(1 for x in pv if v > x)} of {len(pv)}"}
    return out


def growth_mismatches(panel: dict, derived: dict, tol_pp: float = 2.0) -> list[str]:
    """Reported YoY growth vs growth derived from revenue levels. A big gap usually means the base was
    restated (demerger, merger, divestiture) so derived growth is not comparable. Reported is preferred."""
    notes = []
    rep = quarterly(panel, "revenue_growth_yoy")
    for k, d in derived.get("revenue_growth_yoy_derived", {}).items():
        if k in rep and abs(rep[k] - d) > tol_pp:
            notes.append(f"comparability break {label(k)}: reported growth {rep[k]:.2f}% vs {d:.2f}% derived from revenue levels "
                         f"(possible restatement or demerger); reported figure used")
    return notes
