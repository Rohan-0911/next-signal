from types import SimpleNamespace as NS
from nextsignal.tools.periods import parse_period, label
from nextsignal.agent import panel as P


def pt(metric, period, value, doc="results"):
    return {"metric": metric, "period": period, "value": value, "passage": NS(doc_type=doc)}


def test_period_parsing_indian_fy():
    assert parse_period("Jun 2026") == (2027, 1)       # Apr-Jun 2026 is Q1 FY27
    assert parse_period("Mar 2026") == (2026, 4)
    assert parse_period("Q3 FY25") == (2025, 3)
    assert parse_period("FY26-Q4") == (2026, 4)
    assert parse_period("H1 FY26") is None
    assert label(parse_period("Dec 2025")) == "FY26-Q3"


def test_mixed_labels_sort_chronologically():
    pts = [pt("revenue", s, v) for s, v in
           [("Jun 2026", 17341), ("FY25-Q1", 15166), ("FY25-Q2", 15319), ("Dec 2025", 16800), ("FY26-Q4", 17000)]]
    q = P.quarterly(P.build_panel(pts)["panel"], "revenue")
    assert [label(k) for k in q] == ["FY25-Q1", "FY25-Q2", "FY26-Q3", "FY26-Q4", "FY27-Q1"]


def test_revenue_outlier_dropped():
    pts = [pt("revenue", s, v) for s, v in
           [("FY25-Q1", 15166), ("FY25-Q2", 15319), ("FY26-Q3", 5), ("FY27-Q1", 17341)]]
    b = P.build_panel(pts)
    assert "FY26-Q3" not in [label(k) for k in P.quarterly(b["panel"], "revenue")]
    assert any("outlier" in n for n in b["notes"])


def test_price_volume_aligned_by_period_not_position():
    # revenue growth and volume growth cover different quarters; only the overlap may be paired
    pts = [pt("revenue_growth_yoy", "FY25-Q4", 2), pt("revenue_growth_yoy", "FY26-Q4", 8),
           pt("volume_growth_yoy", "FY25-Q1", 4), pt("volume_growth_yoy", "FY25-Q2", 3),
           pt("volume_growth_yoy", "FY26-Q4", 4)]
    b = P.build_panel(pts)
    d = P.derive(b["panel"])
    split = d["price_vs_volume_split"]
    assert [x["period"] for x in split] == ["FY26-Q4"]
    assert abs(split[0]["price_mix_growth"] - (1.08 / 1.04 - 1)) < 1e-9


def test_revenue_growth_derived_from_levels():
    pts = [pt("revenue", "FY25-Q1", 100), pt("revenue", "FY26-Q1", 110)]
    d = P.derive(P.build_panel(pts)["panel"])
    assert abs(d["revenue_growth_yoy_derived"][(2026, 1)] - 10.0) < 1e-9


def test_gate_refuses_thin_data():
    thin = P.build_panel([pt("revenue", "Jun 2026", 17341), pt("operating_profit", "Jun 2026", 3947)])
    ok, why = P.enough_data(thin["panel"], P.derive(thin["panel"]))
    assert not ok and "need" in why


def test_gate_accepts_enough_data():
    pts = [pt("revenue", f"FY{y}-Q{q}", 100 + y + q) for y in (25, 26) for q in (1, 2, 3, 4)]
    pts += [pt("ebitda_margin", f"FY{y}-Q{q}", 23 + q / 10) for y in (25, 26) for q in (1, 2, 3, 4)]
    b = P.build_panel(pts)
    assert P.enough_data(b["panel"], P.derive(b["panel"]))[0]


def test_annual_working_capital_days_and_coverage():
    pts = []
    for fy, rec, rev, cogs, inv, pay in [(23, 600, 5000, 3000, 500, 900), (24, 800, 5200, 3100, 520, 880), (25, 1100, 5400, 3300, 560, 870)]:
        pts += [pt("trade_receivables", f"FY{fy}", rec), pt("revenue", f"FY{fy}", rev), pt("cogs", f"FY{fy}", cogs),
                pt("inventory", f"FY{fy}", inv), pt("trade_payables", f"FY{fy}", pay)]
    b = P.build_panel(pts)
    d = P.derive(b["panel"])
    assert abs(d["receivable_days_annual"][(2025, 0)] - 1100 / 5400 * 365) < 1e-9
    assert d["receivable_days_annual"][(2025, 0)] > d["receivable_days_annual"][(2023, 0)]
    cov = P.coverage(b["panel"], d)
    assert cov["working_capital_vs_revenue"] == "run"
    assert cov["price_vs_volume"].startswith("skipped")
    assert P.enough_data(b["panel"], d)[0]
    s = P.summarise(b["panel"], d)
    assert s["receivable_days_annual"]["periods"] == ["FY23", "FY24", "FY25"]
