"""Uses the shape of the real HUL numbers from the Screener run: stretched payables, flat debtors,
and a one-quarter other-income spike that must NOT be chosen as the discovery."""
from types import SimpleNamespace as NS
from nextsignal.agent import panel as P, candidates as C


def pt(m, per, v):
    return {"metric": m, "period": per, "value": v, "passage": NS(doc_type="results")}


def hul_like():
    pts = []
    for fy, d, i, p, c, rev in [(23, 19, 55, 123, -50, 60580), (24, 18, 55, 143, -70, 61896),
                                (25, 23, 61, 156, -72, 61328), (26, 19, 61, 169, -89, 64468)]:
        pts += [pt("debtor_days", f"FY{fy}", d), pt("inventory_days", f"FY{fy}", i), pt("payable_days", f"FY{fy}", p),
                pt("cash_conversion_cycle", f"FY{fy}", c), pt("revenue", f"FY{fy}", rev)]
    qs = ["Jun 2025", "Sep 2025", "Dec 2025", "Mar 2026", "Jun 2026"]
    for q, oi, rev in zip(qs, [200, 269, 4048, 503, 113], [15757, 15919, 16441, 16351, 17341]):
        pts += [pt("other_income", q, oi), pt("revenue", q, rev)]
    for q, g, o in zip(["Jun 2025", "Sep 2025", "Dec 2025", "Mar 2026", "Jun 2026"], [51.4, 51.4, 51.0, 50.3, 49.5], [24, 24, 23, 23, 23]):
        pts += [pt("gross_margin", q, g), pt("ebitda_margin", q, o)]
    return P.build_panel(pts)["panel"]


def test_ranking_prefers_persistent_workingcapital_over_one_off_spike():
    panel = hul_like()
    ranked = C.rank_candidates(panel, P.derive(panel), None)
    assert ranked[0]["id"] in ("wc_payable_days", "wc_cash_conversion_cycle")
    one_offs = [c for c in ranked if "one_off" in c["flags"]]
    assert one_offs and all(c["score"] < ranked[0]["score"] for c in one_offs)
    assert any("Dec" not in c["claim"] and c["id"].startswith("oneoff_other_income") for c in one_offs)


def test_company_specific_peer_z_raises_score():
    panel = hul_like()
    base = {c["id"]: c["score"] for c in C.rank_candidates(panel, P.derive(panel), None)}
    pc = {"payable_days_chg_3y": {"z": 3.0}}
    boosted = {c["id"]: c["score"] for c in C.rank_candidates(panel, P.derive(panel), pc)}
    assert boosted["wc_payable_days"] > base["wc_payable_days"]


def test_growth_mismatch_flags_restated_base():
    pts = [pt("revenue", "Jun 2025", 15757), pt("revenue", "Jun 2026", 17341), pt("revenue_growth_yoy", "Jun 2026", 5.01)]
    b = P.build_panel(pts)["panel"]
    notes = P.growth_mismatches(b, P.derive(b))
    assert notes and "comparability break" in notes[0]


def test_key_changes_cover_payables():
    ch = P.key_changes(hul_like())
    assert ch["payable_days_chg_3y"] == 169 - 123
