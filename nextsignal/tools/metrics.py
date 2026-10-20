"""Deterministic calculations. The LLM never does arithmetic: it calls these.

All functions are generic (no company-specific logic) and operate on plain
period-indexed dicts so any company's extracted panel can be passed in.
"""
from __future__ import annotations
from statistics import mean, pstdev


def price_volume_split(revenue_growth: float, volume_growth: float) -> dict:
    """Split YoY revenue growth (as fractions, 0.08 = 8%) into volume vs price/mix.

    (1+rev) = (1+vol)(1+price_mix)  ->  price_mix = (1+rev)/(1+vol) - 1
    """
    price_mix = (1 + revenue_growth) / (1 + volume_growth) - 1
    return {
        "revenue_growth": revenue_growth,
        "volume_growth": volume_growth,
        "price_mix_growth": price_mix,
        "price_share_of_growth": (price_mix / revenue_growth) if revenue_growth else None,
    }


def receivable_days(receivables: float, revenue: float, days_in_period: int = 365) -> float:
    """Receivable days = receivables / revenue * days. Use period-matched revenue."""
    return receivables / revenue * days_in_period


def inventory_days(inventory: float, cogs: float, days_in_period: int = 365) -> float:
    return inventory / cogs * days_in_period


def payable_days(payables: float, cogs: float, days_in_period: int = 365) -> float:
    return payables / cogs * days_in_period


def cash_conversion_cycle(rec_days: float, inv_days: float, pay_days: float) -> float:
    return rec_days + inv_days - pay_days


def trend(series: list[float]) -> dict:
    """Simple least-squares slope, plus direction-consistency (share of steps in the
    dominant direction). Persistence matters more than a single-period jump."""
    n = len(series)
    if n < 3:
        return {"slope": 0.0, "consistency": 0.0, "n": n}
    xs = list(range(n))
    xm, ym = mean(xs), mean(series)
    denom = sum((x - xm) ** 2 for x in xs)
    slope = sum((x - xm) * (y - ym) for x, y in zip(xs, series)) / denom
    steps = [b - a for a, b in zip(series, series[1:])]
    up = sum(1 for s in steps if s > 0)
    down = sum(1 for s in steps if s < 0)
    consistency = max(up, down) / len(steps)
    return {"slope": slope, "consistency": consistency, "n": n}


def count_below(series: list[float], threshold: float = 0.0) -> int:
    return sum(1 for v in series if v < threshold)


def peer_adjusted_gap(company: float, peers: list[float]) -> dict:
    """How far the company sits from its peer set. A move shared by all peers is a
    sector story; a large residual is a company story."""
    if not peers:
        return {"gap": None, "z": None, "peer_mean": None}
    pm = mean(peers)
    sd = pstdev(peers) if len(peers) > 1 else 0.0
    gap = company - pm
    return {"gap": gap, "z": (gap / sd) if sd else None, "peer_mean": pm}


def divergence(a_series: list[float], b_series: list[float]) -> dict:
    """Do two series move in opposite directions? e.g. revenue growth vs
    receivable days, loan growth vs asset quality, etc. Returns trend of each and a
    divergence flag based on opposite-signed slopes that are each persistent."""
    ta, tb = trend(a_series), trend(b_series)
    opposite = ta["slope"] * tb["slope"] < 0
    persistent = min(ta["consistency"], tb["consistency"]) >= 0.6
    return {"a": ta, "b": tb, "diverging": bool(opposite and persistent)}


def surprise_score(magnitude: float, persistence: float, peer_z: float | None,
                   narrative_coverage: float) -> float:
    """Rank candidate stories.

    magnitude:  normalised size of the effect (0-1)
    persistence: direction consistency over time (0-1)
    peer_z:     company deviation from peers in std devs (None -> neutral 1.0)
    narrative_coverage: 0-1, how much management/news already say this (high = obvious)

    Non-obvious = large, persistent, company-specific and under-discussed.
    """
    company_specific = 1.0 if peer_z is None else min(abs(peer_z) / 2.0, 1.5)
    return magnitude * persistence * company_specific * (1.0 - narrative_coverage)
