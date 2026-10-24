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
