"""Deterministic candidate generation and ranking.

Instead of letting the LLM eyeball a wall of numbers (and latch onto a one-off spike), code
proposes candidate divergences from the generic Track C tests and scores each with
tools.metrics.surprise_score = magnitude x persistence x company-specificity x (1 - narrative coverage).
The LLM then explains and stress-tests the top non-one-off candidate.
"""
from __future__ import annotations
import re
from statistics import median
from ..tools import metrics
from ..models import Passage, EvidenceItem
from ..tools.periods import label
from .panel import quarterly, annual

WC = {"debtor_days": "Receivable days", "inventory_days": "Inventory days",
      "payable_days": "Payable days", "cash_conversion_cycle": "Cash conversion cycle"}


def _z(peer_check: dict, key: str):
    v = (peer_check or {}).get(key)
    return None if not v else v.get("z")


def history_check(series: list[float], window: int) -> dict:
    """Is the move just a return to the company's own long-run range? A 3-year window that starts at a
    12-year trough will always look like a trend. Needs >= 8 points to say anything."""
    n = len(series)
    if n < 8:
        return {"n": n, "mean_reversion_risk": False, "start_pct": None, "latest_pct": None, "min": None, "max": None}
    start, latest = series[-window], series[-1]
    pct = lambda x: sum(1 for v in series if v <= x) / n
    delta = latest - start
    sp = pct(start)
    reverting = (sp <= 0.15 and delta > 0) or (sp >= 0.85 and delta < 0)
    return {"n": n, "mean_reversion_risk": bool(reverting), "start_pct": round(sp, 2), "latest_pct": round(pct(latest), 2),
            "min": min(series), "max": max(series)}


def rank_candidates(panel: dict, derived: dict, peer_check: dict | None = None) -> list[dict]:
    out: list[dict] = []
    rev_a = list(annual(panel, "revenue").values())

    # 1. Working capital moving away from revenue (annual)
    for m, name in WC.items():
        a = list(annual(panel, m).values())
        if len(a) < 3:
            continue
        n = min(len(a), 4)
        delta = a[-1] - a[-n]
        mag = min(abs(delta) / max(abs(a[-n]), 10.0), 1.0)
        pers = metrics.trend(a[-n:])["consistency"]
        rg = f", while revenue grew {(rev_a[-1] / rev_a[-n] - 1) * 100:.1f}%" if len(rev_a) >= n and rev_a[-n] else ""
        hist = history_check(a, n)
        flags = ["mean_reversion_risk"] if hist["mean_reversion_risk"] else []
        rng = (f" (long-run range {hist['min']:.0f} to {hist['max']:.0f}; window started at the "
               f"{hist['start_pct'] * 100:.0f}th percentile of its own {len(a)}-year history)") if hist["n"] >= 8 else ""
        out.append({"id": f"wc_{m}", "test": "working_capital_vs_revenue",
                    "claim": f"{name} moved from {a[-n]:.0f} to {a[-1]:.0f} over {n - 1} years{rg}{rng}",
                    "components": {"magnitude": round(mag, 2), "persistence": round(pers, 2),
                                   "peer_z": _z(peer_check, f"{m}_chg_3y"), "narrative_coverage": 0.1},
                    "history": hist, "flags": flags})

    # 2. Gross margin compression absorbed lower in the P&L
    gm, om = quarterly(panel, "gross_margin"), quarterly(panel, "ebitda_margin")
    if len(gm) >= 5 and len(om) >= 5:
        g, o = list(gm.values()), list(om.values())
        dg, do = g[-1] - g[-5], o[-1] - o[-5]
        if dg <= -1.0 and do >= dg + 0.8:
            out.append({"id": "margin_offset", "test": "margin_quality",
                        "claim": f"Gross margin fell {abs(dg):.1f}pp year on year but operating margin moved only {do:+.1f}pp, so costs below gross profit offset it",
                        "components": {"magnitude": round(min(abs(dg) / 5, 1), 2),
                                       "persistence": round(metrics.trend(g[-5:])["consistency"], 2),
                                       "peer_z": _z(peer_check, "opm_yoy_chg"), "narrative_coverage": 0.2},
                        "flags": []})

    # 3. Price vs volume (aligned by period)
    pv = derived.get("price_vs_volume_split", [])
    if len(pv) >= 3:
        pm = [x["price_mix_growth"] for x in pv]
        vg = [x["volume_growth"] for x in pv]
        weak_vol = sum(1 for v in vg if v <= 0.01)
        price_led = sum(1 for p, v in zip(pm, vg) if p > v)
        share = max(weak_vol, price_led) / len(pv)
        if share >= 0.5:
            out.append({"id": "price_vs_volume", "test": "price_vs_volume",
                        "claim": f"Growth was price/mix-led in {price_led} of {len(pv)} aligned quarters; volume growth was flat or negative in {weak_vol}",
                        "components": {"magnitude": round(min(abs(sum(pm) / len(pm) - sum(vg) / len(vg)) / 0.05, 1), 2),
                                       "persistence": round(share, 2), "peer_z": None, "narrative_coverage": 0.3},
                        "flags": []})

    # 3b. Profit bridge: how much of reported profit growth is non-operating? (earnings quality, any company)
    np_, op_, oi_ = annual(panel, "net_profit"), annual(panel, "operating_profit"), annual(panel, "other_income")
    common = sorted(set(np_) & set(op_) & set(oi_))
    if len(common) >= 2:
        k0, k1 = common[-2], common[-1]
        dnp, dop, doi = np_[k1] - np_[k0], op_[k1] - op_[k0], oi_[k1] - oi_[k0]
        if np_[k0] > 0 and dnp / np_[k0] >= 0.10 and doi / dnp >= 0.5:
            share = min(doi / dnp, 1.0)
            out.append({"id": f"profit_bridge_{label(k1)}", "test": "margin_quality",
                        "claim": (f"{label(k1)} net profit grew {dnp / np_[k0] * 100:.0f}% but operating profit grew only "
                                  f"{dop / op_[k0] * 100:.1f}%; other income explains {doi / dnp * 100:.0f}% of the net-profit increase"),
                        "components": {"magnitude": round(share, 2), "persistence": 0.5, "peer_z": None, "narrative_coverage": 0.5},
                        "flags": ["needs_explanation"]})

    # 4. One-off spikes (reported as caveats, never as discoveries)
    for m in ("other_income", "net_profit", "operating_profit"):
        q = quarterly(panel, m)
        if len(q) >= 4:
            vals = list(q.values())
            for k, v in q.items():
                rest = [x for kk, x in q.items() if kk != k]
                med = median(rest)
                if med > 0 and v > 3 * med:
                    out.append({"id": f"oneoff_{m}_{label(k)}", "test": "margin_quality", "period": label(k), "value": v, "metric": m,
                                "claim": f"{m} spiked to {v:g} in {label(k)} versus a median of {med:g} in other quarters",
                                "components": {"magnitude": 1.0, "persistence": round(1 / len(vals), 2),
                                               "peer_z": None, "narrative_coverage": 0.9},
                                "flags": ["one_off"]})

    for c in out:
        cm = c["components"]
        c["score"] = round(metrics.surprise_score(cm["magnitude"], cm["persistence"], cm["peer_z"], cm["narrative_coverage"]), 3)
        if "one_off" in c["flags"]:
            c["score"] = round(c["score"] * 0.2, 3)
        if "mean_reversion_risk" in c["flags"]:
            c["score"] = round(c["score"] * 0.15, 3)
    return sorted(out, key=lambda c: c["score"], reverse=True)


def numeric_evidence(cand: dict, panel: dict, peer_panels: dict, url: str) -> list[EvidenceItem]:
    """Evidence that comes from the numbers themselves, with provenance to the Screener table it came from.
    Source classes: the company's own statements (company_primary) and peers' statements (peer)."""
    ev: list[EvidenceItem] = []
    if not cand:
        return ev
    base = url.rstrip("/")

    def fmt(series: dict, k=6):
        return ", ".join(f"{label(x)}={v:g}" for x, v in list(series.items())[-k:])

    if cand["id"].startswith("wc_"):
        m = cand["id"][3:]
        own = annual(panel, m)
        a = list(own.values())
        h = cand.get("history") or {}
        passage = Passage(f"{base}/#ratios", "results", f"Screener ratios: {WC.get(m, m)}", "", f"{WC.get(m, m)}: {fmt(own)}", verified=True)
        if h.get("n", 0) >= 8:
            if h.get("mean_reversion_risk"):
                ev.append(EvidenceItem("h1", "contradicts",
                          f"Own-history check: the window starts at the {h['start_pct'] * 100:.0f}th percentile of {h['n']} years "
                          f"(range {h['min']:.0f} to {h['max']:.0f}); much of the move is a return toward the usual range", [passage], "company_primary"))
            else:
                ev.append(EvidenceItem("h1", "supports",
                          f"Own-history check: latest value sits at the {h['latest_pct'] * 100:.0f}th percentile of {h['n']} years "
                          f"(range {h['min']:.0f} to {h['max']:.0f}); not explained by a trough start", [passage], "company_primary"))
        else:
            ev.append(EvidenceItem("h1", "supports", f"Company series: {fmt(own)}", [passage], "company_primary"))
        # peers
        n = min(len(a), 4)
        mine = a[-1] - a[-n] if len(a) >= 2 else 0
        same, rows, pass_ = 0, [], []
        for sym, pp in peer_panels.items():
            pa = list(annual(pp, m).values())
            if len(pa) < n or n < 2:
                continue
            d = pa[-1] - pa[-n]
            rows.append(f"{sym}: {pa[-n]:g}->{pa[-1]:g}")
            if d * mine > 0 and abs(d) >= 0.5 * abs(mine):
                same += 1
            pass_.append(Passage(f"https://www.screener.in/company/{sym}/consolidated/#ratios", "peer",
                                 f"Screener ratios: {sym}", "", f"{WC.get(m, m)} {sym}: {fmt(annual(pp, m))}", verified=True))
        if rows:
            tot = len(rows)
            stance = "contradicts" if same >= (tot + 1) // 2 else "supports"
            ev.append(EvidenceItem("h1", stance,
                      f"Peer check: {same} of {tot} peers moved the same way by at least half as much ({'; '.join(rows)})"
                      + (" - looks sector-wide" if stance == "contradicts" else " - company-specific"), pass_, "peer"))
    elif cand["id"].startswith("profit_bridge"):
        passage = Passage(f"{base}/#profit-loss", "results", "Screener annual P&L", "",
                          f"Net profit: {fmt(annual(panel, 'net_profit'), 3)}; Operating profit: {fmt(annual(panel, 'operating_profit'), 3)}; "
                          f"Other income: {fmt(annual(panel, 'other_income'), 3)}", verified=True)
        ev.append(EvidenceItem("h1", "supports", cand["claim"], [passage], "company_primary"))
        # peers: how many show most of their latest profit growth coming from other income?
        rows, hits, pass_ = [], 0, []
        for sym, pp in peer_panels.items():
            np_, op_, oi_ = annual(pp, "net_profit"), annual(pp, "operating_profit"), annual(pp, "other_income")
            common = sorted(set(np_) & set(op_) & set(oi_))
            if len(common) < 2:
                continue
            k0, k1 = common[-2], common[-1]
            dnp, doi = np_[k1] - np_[k0], oi_[k1] - oi_[k0]
            share = (doi / dnp) if dnp > 0 else 0.0
            rows.append(f"{sym}: NP {((np_[k1] / np_[k0] - 1) * 100) if np_[k0] else 0:+.0f}%, other income share {share * 100:.0f}%")
            hits += 1 if (dnp > 0 and share >= 0.5) else 0
            pass_.append(Passage(f"https://www.screener.in/company/{sym}/consolidated/#profit-loss", "peer", f"Screener annual P&L: {sym}", "",
                                 f"{sym} net profit {fmt(np_, 3)}; other income {fmt(oi_, 3)}", verified=True))
        if rows:
            ev.append(EvidenceItem("h1", "contradicts" if hits >= (len(rows) + 1) // 2 else "supports",
                      f"Peer check: {hits} of {len(rows)} peers drew at least half of their latest profit growth from other income ({'; '.join(rows)})"
                      + (" - sector-wide" if hits >= (len(rows) + 1) // 2 else " - specific to this company"), pass_, "peer"))
    return ev


def explanation_queries(company: str, ranked: list[dict], selected: dict | None) -> list[tuple[str, str]]:
    """For a gap that needs an explanation, search for the cause around the quarter where it appeared.
    Deterministic (built from the computed spike), so it does not depend on the model guessing the right words."""
    if not selected or "needs_explanation" not in selected.get("flags", []):
        return []
    spikes = [c for c in ranked if "one_off" in c["flags"] and c.get("metric") in ("other_income", "net_profit")]
    if not spikes:
        return []
    top = max(spikes, key=lambda c: c.get("value", 0))
    m = re.search(r"FY(\d{2})-Q([1-4])", top["period"])
    if not m:
        return []
    qlabel, metric = f"Q{m.group(2)} FY{m.group(1)}", top["metric"].replace("_", " ")
    impl = f"What caused the spike in {metric} in {qlabel}? (exceptional item, demerger, disposal, one-time gain)"
    return [(f"{company} {qlabel} results net profit exceptional item one-off gain", impl),
            (f"{company} {qlabel} exceptional gain demerger disposal sale {metric}", impl)]


def falsification_for(cand: dict | None, panel: dict) -> str:
    """Deterministic falsification condition built only from computed numbers (so it can never contain an invented figure)."""
    if not cand:
        return ""
    cid = cand["id"]
    if cid.startswith("profit_bridge"):
        oi, np_, op_ = annual(panel, "other_income"), annual(panel, "net_profit"), annual(panel, "operating_profit")
        common = sorted(set(oi) & set(np_) & set(op_))
        if len(common) >= 2:
            k0, k1 = common[-2], common[-1]
            g = (np_[k1] / np_[k0] - 1) * 100
            return (f"Overturned if operating profit growth rises to match the {g:.0f}% net-profit growth, or if the disclosed cause of the "
                    f"{oi[k1]:.0f} other income in {label(k1)} turns out to be recurring (other income staying near {oi[k1] / 4:.0f} a quarter "
                    f"for the next four quarters with no one-off disclosed).")
    if cid.startswith("wc_"):
        m = cid[3:]
        a = list(annual(panel, m).values())
        if len(a) >= 3:
            return (f"Overturned if the move is not a return to normal: {WC.get(m, m)} reverting to its own median of {median(a):.0f} "
                    f"would remove the finding, as would at least half of the peers showing a similar move.")
    if cid == "price_vs_volume":
        return "Overturned if volume growth is positive for two consecutive quarters while price/mix growth falls below volume growth."
    if cid == "margin_offset":
        return "Overturned if gross margin recovers to its level a year earlier, or if costs below gross profit rise in line with gross profit."
    return ""
