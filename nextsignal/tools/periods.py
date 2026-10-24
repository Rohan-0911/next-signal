"""Normalise the many ways documents label periods into one sortable key.

Indian fiscal year: Apr-Mar. FY27 = Apr 2026 - Mar 2027.
Key = (fiscal_year, quarter) where quarter 0 means a full-year figure.
Supports: "FY26-Q4", "Q4 FY26", "Q4FY26", "FY26", "FY2026", "Jun 2026", "June 2026", "Q1 FY2027".
Anything else returns None so it is excluded rather than mis-ordered.
"""
from __future__ import annotations
import re

_MONTH_Q = {"jun": 1, "sep": 2, "dec": 3, "mar": 4}
_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


def _yr(s: str) -> int:
    y = int(s)
    return y + 2000 if y < 100 else y


def parse_period(label) -> tuple[int, int] | None:
    s = str(label).strip().lower().replace("_", " ")
    m = re.search(r"fy\s*(\d{2,4})\s*[-\s]?\s*q([1-4])", s) or None
    if m:
        return _yr(m.group(1)), int(m.group(2))
    m = re.search(r"q([1-4])\s*[-\s]?\s*fy\s*(\d{2,4})", s)
    if m:
        return _yr(m.group(2)), int(m.group(1))
    m = re.fullmatch(r"fy\s*(\d{2,4})", s)
    if m:
        return _yr(m.group(1)), 0
    m = re.fullmatch(r"([a-z]{3})[a-z]*\.?\s*[-']?\s*(\d{2,4})", s)
    if m and m.group(1) in _MONTH_Q:
        mon, year = m.group(1), _yr(m.group(2))
        fy = year if mon == "mar" else year + 1 if mon in ("jun", "sep", "dec") else year
        # Jun/Sep/Dec of calendar year Y belong to FY(Y+1); Mar of year Y belongs to FY(Y)
        return fy, _MONTH_Q[mon]
    m = re.fullmatch(r"(\d{1,2})\s*[-/]\s*(\d{4})", s)          # "06-2026", "3/2026"
    if m and int(m.group(1)) in (3, 6, 9, 12):
        mon, year = _MONTHS[int(m.group(1)) - 1], int(m.group(2))
        return parse_period(f"{mon} {year}")
    return None


def label(key: tuple[int, int]) -> str:
    fy, q = key
    return f"FY{fy % 100:02d}" + (f"-Q{q}" if q else "")


def yoy_key(key: tuple[int, int]) -> tuple[int, int]:
    return key[0] - 1, key[1]
