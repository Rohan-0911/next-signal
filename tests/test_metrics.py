import math
from nextsignal.tools import metrics as m


def test_price_volume_split_price_led():
    r = m.price_volume_split(0.08, -0.02)
    assert math.isclose(r["price_mix_growth"], 1.08 / 0.98 - 1)
    assert r["price_share_of_growth"] > 1.0  # price more than explains growth


def test_price_volume_split_volume_led():
    r = m.price_volume_split(0.10, 0.10)
    assert abs(r["price_mix_growth"]) < 1e-12


def test_receivable_days():
    assert math.isclose(m.receivable_days(46, 365), 46.0)
    assert math.isclose(m.receivable_days(25, 100, 90), 22.5)


def test_ccc():
    assert m.cash_conversion_cycle(30, 40, 50) == 20


def test_trend_and_divergence():
    rev = [0.05, 0.06, 0.07, 0.08, 0.09, 0.10]
    days = [28, 31, 35, 39, 42, 46]
    assert m.divergence(rev, days)["diverging"] is False  # both rising
    rev_down = [0.10, 0.09, 0.07, 0.05, 0.04, 0.02]
    assert m.divergence(rev_down, days)["diverging"] is True


def test_count_below():
    assert m.count_below([0.01, -0.02, -0.01, 0.0, -0.03]) == 3


def test_peer_gap_sector_vs_company():
    # all peers also weak -> small gap -> sector story
    near = m.peer_adjusted_gap(-0.01, [-0.02, -0.01, -0.015])
    far = m.peer_adjusted_gap(-0.05, [0.03, 0.04, 0.02])
    assert abs(far["gap"]) > abs(near["gap"])


def test_surprise_prefers_underdiscussed_company_specific():
    obvious = m.surprise_score(0.8, 0.9, 0.2, 0.9)
    hidden = m.surprise_score(0.8, 0.9, 2.5, 0.1)
    assert hidden > obvious
