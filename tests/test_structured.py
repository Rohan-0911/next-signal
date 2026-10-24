import pandas as pd
from nextsignal.sources import structured as S
from nextsignal.agent import panel as P
from nextsignal.tools.periods import label


class FakeTicker:
    quarterly_income_stmt = pd.DataFrame(
        {pd.Timestamp("2025-06-30"): [1.65e11, 3.7e10, 8.0e10], pd.Timestamp("2025-03-31"): [1.60e11, 3.6e10, 7.9e10]},
        index=["Total Revenue", "EBITDA", "Gross Profit"])
    income_stmt = pd.DataFrame({pd.Timestamp("2025-03-31"): [6.0e11, 3.0e11]}, index=["Total Revenue", "Cost Of Revenue"])
    balance_sheet = pd.DataFrame({pd.Timestamp("2025-03-31"): [2.0e10, 1.0e10]}, index=["Accounts Receivable", "Inventory"])


def test_points_from_ticker_units_and_labels():
    pts = S.points_from_ticker(FakeTicker(), "X.NS")
    by = {(p["metric"], p["period"]): p["value"] for p in pts}
    assert abs(by[("revenue", "Jun 2025")] - 16500) < 1e-6           # 1.65e11 INR = 16,500 crore
    assert abs(by[("ebitda_margin", "Jun 2025")] - 3.7e10 / 1.65e11 * 100) < 1e-6
    assert abs(by[("trade_receivables", "FY25")] - 2000) < 1e-6
    assert all(p["passage"].verified and "yfinance" in p["passage"].quote for p in pts)
    b = P.build_panel(pts)
    assert label((2026, 1)) in [label(k) for k in P.quarterly(b["panel"], "revenue")]


def test_ambiguous_duplicate_quarter_values_dropped():
    from types import SimpleNamespace as NS
    mk = lambda per, v: {"metric": "revenue", "period": per, "value": v, "passage": NS(doc_type="results")}
    b = P.build_panel([mk("Jun 2025", 17341), mk("Jun 2026", 17341), mk("Sep 2025", 16241)])
    assert [label(k) for k in P.quarterly(b["panel"], "revenue")] == ["FY26-Q2"]
    assert any("ambiguous" in n for n in b["notes"])


def test_load_points_never_raises_without_network(monkeypatch):
    assert isinstance(S.load_points("Anything"), list)
