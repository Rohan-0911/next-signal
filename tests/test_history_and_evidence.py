"""Uses the REAL HUL annual series from the v7 run: the 'discovery' there was a rebound from a 12-year trough."""
from nextsignal.agent import panel as P, candidates as C
from types import SimpleNamespace as NS

FY = list(range(15, 27))
PAYABLE = [148, 156, 164, 185, 166, 176, 163, 145, 123, 143, 156, 169]
CCC = [-60, -67, -85, -107, -90, -101, -83, -64, -50, -70, -72, -89]
NP = [4376, 4151, 4490, 5227, 6060, 6756, 7999, 8892, 10143, 10282, 10671, 15059]
OP = [5412, 5910, 6328, 7499, 8880, 9861, 11626, 12857, 14147, 14659, 14698, 15039]
OI = [1247, 486, 606, 353, 322, 424, 170, 219, 448, 817, 1355, 4923]
REV = [31972, 32186, 33162, 35545, 39310, 39783, 47028, 52446, 60580, 61896, 61328, 64468]


def pt(m, per, v):
    return {"metric": m, "period": per, "value": v, "passage": NS(doc_type="results")}


def hul_panel():
    pts = []
    for i, fy in enumerate(FY):
        for m, series in (("payable_days", PAYABLE), ("cash_conversion_cycle", CCC), ("net_profit", NP),
                          ("operating_profit", OP), ("other_income", OI), ("revenue", REV)):
            pts.append(pt(m, f"FY{fy}", series[i]))
    return P.build_panel(pts)["panel"]


def test_trough_start_is_flagged_as_mean_reversion():
    ranked = C.rank_candidates(hul_panel(), {}, None)
    by = {c["id"]: c for c in ranked}
    assert "mean_reversion_risk" in by["wc_payable_days"]["flags"]
    assert "mean_reversion_risk" in by["wc_cash_conversion_cycle"]["flags"]
    assert "12-year history" in by["wc_payable_days"]["claim"]
    assert by["wc_payable_days"]["history"]["min"] == 123 and by["wc_payable_days"]["history"]["max"] == 185


def test_profit_bridge_finds_nonoperating_profit_growth():
    ranked = C.rank_candidates(hul_panel(), {}, None)
    bridge = next(c for c in ranked if c["id"].startswith("profit_bridge"))
    assert "81%" in bridge["claim"] and "2.3%" in bridge["claim"] and "41%" in bridge["claim"]
    assert "needs_explanation" in bridge["flags"]
    # the honest ordering: the profit bridge now outranks the trough-start working-capital stories
    assert ranked[0]["id"] == bridge["id"]


def test_numeric_evidence_gives_company_and_peer_classes():
    panel = hul_panel()
    cand = next(c for c in C.rank_candidates(panel, {}, None) if c["id"] == "wc_payable_days")
    peers = {"AAA": P.build_panel([pt("payable_days", f"FY{y}", v) for y, v in zip(FY, [100] * 8 + [100, 125, 140, 160])])["panel"],   # same-direction peer
             "BBB": P.build_panel([pt("payable_days", f"FY{y}", 120) for y in FY])["panel"]}               # flat peer
    ev = C.numeric_evidence(cand, panel, peers, "https://www.screener.in/company/HINDUNILVR/consolidated/")
    assert {e.source_class for e in ev} == {"company_primary", "peer"}
    assert all(p.verified for e in ev for p in e.passages)
    assert any(e.stance == "contradicts" and "return toward" in e.summary for e in ev)     # own-history check
    assert any("1 of 2 peers" in e.summary for e in ev)


def test_peer_z_suppressed_with_few_peers():
    pc = P.peer_check(hul_panel(), [hul_panel(), hul_panel(), hul_panel()])
    assert all(v["z"] is None for v in pc.values()) or pc == {}


def test_explanation_queries_target_the_spike_quarter():
    panel = P.build_panel([pt(m, f"FY{fy}", s[i]) for i, fy in enumerate(FY)
                           for m, s in (("net_profit", NP), ("operating_profit", OP), ("other_income", OI), ("revenue", REV))]
                          + [pt("other_income", q, v) for q, v in zip(["Jun 2025", "Sep 2025", "Dec 2025", "Mar 2026", "Jun 2026"], [103, 269, 4048, 503, 113])]
                          + [pt("revenue", q, v) for q, v in zip(["Jun 2025", "Sep 2025", "Dec 2025", "Mar 2026", "Jun 2026"], [15757, 15919, 16441, 16351, 17341])])["panel"]
    ranked = C.rank_candidates(panel, {}, None)
    selected = ranked[0]
    assert selected["id"].startswith("profit_bridge")
    qs = C.explanation_queries("Hindustan Unilever", ranked, selected)
    assert len(qs) == 2 and all("Q3 FY26" in q for q, _ in qs) and any("demerger" in q for q, _ in qs)
    assert C.explanation_queries("X", ranked, {"id": "wc_x", "flags": []}) == []      # only for gaps that need an explanation


def test_deterministic_falsification_uses_only_computed_numbers():
    from nextsignal.agent import synthesis as SY
    panel = hul_panel()
    cand = C.rank_candidates(panel, {}, None)[0]
    text = C.falsification_for(cand, panel)
    allowed = SY.numbers_in(" ".join(str(v) for v in OI + NP + OP) + " 41 4923 1231", include_small_ints=True)
    assert SY.ungrounded(text, allowed) == [] and "41%" in text


def test_spine_day_ratios_are_not_recomputed_from_document_levels():
    pts = [pt("debtor_days", f"FY{y}", 19) for y in (24, 25, 26)]
    pts += [pt("trade_receivables", f"FY{y}", 19000) for y in (24, 25, 26)] + [pt("revenue", f"FY{y}", 60000) for y in (24, 25, 26)]
    d = P.derive(P.build_panel(pts)["panel"])
    assert "receivable_days_annual" not in d          # the 112-day nonsense from v9 cannot reappear


def test_screener_pages_are_not_reextracted(monkeypatch):
    from nextsignal.agent import pipeline as PL
    monkeypatch.setattr(PL.llm, "complete_json", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call the model")))
    assert PL.extract_panel("https://www.screener.in/company/HINDUNILVR/consolidated?order=asc", "results", "t", "") == []


def test_profit_bridge_peer_evidence_specific_vs_sector():
    panel = hul_panel()
    cand = next(c for c in C.rank_candidates(panel, {}, None) if c["id"].startswith("profit_bridge"))

    def peer(np_, oi_):
        pts = []
        for i, fy in enumerate(FY):
            pts += [pt("net_profit", f"FY{fy}", np_[i]), pt("operating_profit", f"FY{fy}", 1000), pt("other_income", f"FY{fy}", oi_[i])]
        return P.build_panel(pts)["panel"]

    normal = peer([100 + i for i in range(12)], [10] * 12)                 # profit grew 1 a year, other income flat
    ev = C.numeric_evidence(cand, panel, {"A": normal, "B": normal, "C": normal}, "https://www.screener.in/company/X/consolidated/")
    assert {e.source_class for e in ev} == {"company_primary", "peer"}
    assert next(e for e in ev if e.source_class == "peer").stance == "supports"    # specific to this company
    spiky = peer([100] * 11 + [200], [10] * 11 + [90])
    ev2 = C.numeric_evidence(cand, panel, {"A": spiky, "B": spiky, "C": normal}, "https://www.screener.in/company/X/consolidated/")
    assert next(e for e in ev2 if e.source_class == "peer").stance == "contradicts"  # sector-wide
