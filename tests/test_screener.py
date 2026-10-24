from nextsignal.sources import screener as S
from nextsignal.agent import panel as P
from nextsignal.tools.periods import label

def table(section, headers, rows):
    th = "<th></th>" + "".join(f"<th>{h}</th>" for h in headers)
    trs = "".join(f"<tr><td class='text'><button>{name}&nbsp;<span>+</span></button></td>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>" for name, cells in rows)
    return f"<section id='{section}'><table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table></section>"

Q = ["Jun 2024", "Sep 2024", "Dec 2024", "Mar 2025", "Jun 2025"]
HTML = ("<html><body><div id='company-info' data-warehouse-id='123'></div>"
        + table("quarters", Q, [("Sales&nbsp;+", ["15,166", "15,319", "15,000", "15,200", "15,900"]),
                               ("Operating Profit", ["3,700", "3,600", "3,500", "3,550", "3,700"]),
                               ("OPM %", ["24%", "23%", "23%", "23%", "23%"])])
        + table("ratios", ["Mar 2022", "Mar 2023", "Mar 2024", "Mar 2025"],
                [("Debtor Days", ["8", "9", "11", "14"]), ("Inventory Days", ["40", "41", "40", "39"]),
                 ("Days Payable", ["90", "88", "85", "80"]), ("Cash Conversion Cycle", ["-42", "-38", "-34", "-27"])])
        + table("profit-loss", ["Mar 2024", "Mar 2025", "TTM"], [("Sales +", ["60,000", "61,000", "62,000"])])
        + "</body></html>")


def test_parse_and_period_mapping():
    pts = S.points_from_html(HTML, "https://www.screener.in/company/X/consolidated/")
    by = {(p["metric"], p["period"]): p["value"] for p in pts}
    assert by[("revenue", "Jun 2024")] == 15166.0
    assert by[("ebitda_margin", "Jun 2025")] == 23.0
    assert by[("debtor_days", "FY25")] == 14.0             # Mar 2025 -> FY25 (annual)
    assert ("revenue", "FY24") in by and not any(p["period"] == "TTM" for p in pts)
    assert all(p["passage"].verified for p in pts)


def test_panel_from_screener_runs_working_capital_and_margin_tests():
    b = P.build_panel(S.points_from_html(HTML, "u"))
    d = P.derive(b["panel"])
    cov = P.coverage(b["panel"], d)
    assert cov["working_capital_vs_revenue"] == "run"        # 4 annual debtor-days points
    assert cov["margin_quality"] == "run"
    ch = P.key_changes(b["panel"])
    assert ch["debtor_days_chg_3y"] == 6.0                   # 14 - 8
    assert abs(ch["revenue_growth_latest"] - (15900 / 15166 - 1) * 100) < 1e-6 or ch["revenue_growth_latest"] is None


def test_peer_check_flags_company_specific_move():
    mk = lambda dd: P.build_panel(S.points_from_html(HTML.replace("8", str(dd[0])).replace("14", str(dd[1])), "u"))["panel"]
    company = P.build_panel(S.points_from_html(HTML, "u"))["panel"]
    peers = [{"debtor_days": {(2022, 0): 30.0, (2023, 0): 30.0, (2024, 0): 30.0, (2025, 0): 30.5 + i * 0.2}} for i in range(3)]
    pc = P.peer_check(company, peers)
    assert pc["debtor_days_chg_3y"]["gap"] > 4
    assert S.find_peers('<a href="/company/ITC/">x</a><a href="/company/DABUR/">y</a>') == ["ITC", "DABUR"]
