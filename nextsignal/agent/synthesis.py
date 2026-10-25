"""Final write-up step with a hard number check.

The model rewrites the discovery, the 3-5 'why it matters' bullets, the counterargument and the falsification
condition using ONLY the computed numbers and verified quotes. Every number it writes is then checked against
those sources; sentences with a number that cannot be found are dropped. This is how 'unsupported claims'
are kept out of the final output.
"""
from __future__ import annotations
import json
import re
from .. import llm

SYS_SYN = (
    "You write the final note for ONE research finding about a listed company. Use ONLY the numbers in `numbers` "
    "and the verified quotes in `evidence`; never add outside facts. Return JSON: "
    '{"discovery":str,"why_it_matters":[str],"counterargument":str,"falsification":str}. '
    "Rules: (1) `discovery` is ONE sentence stating what the evidence shows, including the cause if an evidence item "
    "identifies it. (2) `why_it_matters` has 3 to 5 bullets about significance for how an analyst should read the company "
    "(earnings quality, comparability, sustainability), each grounded in a number or a quote. "
    "(3) `counterargument` is the strongest alternative explanation or contradicting evidence; say whether it overturns "
    "the finding or only refines it. (4) `falsification` is concrete future data (metric, direction, number of periods) "
    "that would overturn the finding. (5) Never give investment advice."
)

_FY = re.compile(r"\bFY\s?\d{2,4}(?:-?Q[1-4])?\b|\bQ[1-4]\s?FY\s?\d{2,4}\b|\b(?:19|20)\d{2}\b", re.I)
_NUM = re.compile(r"\d[\d,]*\.?\d*")


def numbers_in(text: str, include_small_ints: bool = False) -> list[float]:
    t = _FY.sub(" ", text)
    out = []
    for tok in _NUM.findall(t):
        tok = tok.rstrip(".,")
        try:
            v = float(tok.replace(",", ""))
        except ValueError:
            continue
        if not include_small_ints and v <= 12 and "." not in tok:
            continue                       # counts like "3 years", "2 of 3 peers"
        out.append(v)
    return out


def ungrounded(text: str, grounded: list[float]) -> list[float]:
    bad = []
    for n in numbers_in(text):
        if not any(abs(n - g) <= max(0.6, 0.01 * abs(g)) for g in grounded):
            bad.append(n)
    return bad


def grounded_numbers(key_numbers: dict, evidence) -> list[float]:
    blob = json.dumps(key_numbers, default=str)
    quotes = " ".join(p.quote for e in evidence for p in e.passages if p.verified)
    nums = numbers_in(blob + " " + quotes, include_small_ints=True)
    # Fractions in the computed data (0.75 percentile, 0.515 price share) are written as percentages in prose.
    return nums + [round(n * 100, 1) for n in nums if 0 < n <= 1.5]


def synthesize(company: str, claim: str, key_numbers: dict, evidence, alternatives: list, falsification_draft: str):
    """-> (dict | None, notes). None means: keep the earlier draft."""
    ev_payload = [{"stance": e.stance, "source_class": e.source_class, "summary": e.summary,
                   "quotes": [p.quote for p in e.passages if p.verified]} for e in evidence]
    payload = {"company": company, "claim": claim, "numbers": key_numbers, "evidence": ev_payload,
               "alternatives": alternatives, "falsification_draft": falsification_draft}
    out = llm.complete_json(SYS_SYN, json.dumps(payload, default=str))
    g = grounded_numbers(key_numbers, evidence) + numbers_in(claim, include_small_ints=True)
    notes = []
    res = {"discovery": str(out.get("discovery", "")).strip(), "why_it_matters": [], "counterargument": str(out.get("counterargument", "")).strip(),
           "falsification": str(out.get("falsification", "")).strip()}
    for field in ("discovery", "counterargument", "falsification"):
        bad = ungrounded(res[field], g)
        if bad:
            notes.append(f"dropped {field}: numbers not found in sources {bad[:4]}")
            res[field] = ""
    for b in out.get("why_it_matters", []):
        bad = ungrounded(str(b), g)
        if bad:
            notes.append(f"dropped bullet: numbers not found in sources {bad[:4]}")
        elif str(b).strip():
            res["why_it_matters"].append(str(b).strip())
    return res, notes
