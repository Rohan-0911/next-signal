"""End-to-end autonomous loop: company -> hypotheses -> evidence -> challenge -> finding.

Stages (see README for the diagram):
 1 PROFILE     resolve company, find peers, discover sources
 2 EXTRACT     LLM reads documents into a period-indexed panel WITH quotes (provenance)
 3 SCAN        run every generic divergence test, compute with tools/metrics.py
 4 HYPOTHESISE rank anomalies by surprise score; LLM states hypothesis + implications
 5 TEST        gather evidence for each implication from independent source classes
 6 CHALLENGE   adversary searches for disconfirming evidence and alternative explanations
 7 VERIFY      quotes must appear in source; independence counted; strength graded
 8 REPORT      eight required elements, every claim linked to a verified passage
"""
from __future__ import annotations
import json
from .. import llm
from ..models import Passage, EvidenceItem, Finding
from ..sources.search import discover_sources, search
from ..sources.fetch import get_text
from ..tools import metrics
from .angles import TRACK_C_TESTS
from .verify import verify_passage, grade, contradictions, source_class

SYS_EXTRACT = (
    "You extract structured financial data from a company document. Output JSON: "
    '{"points":[{"metric":str,"period":str,"value":number,"unit":str,"quote":str}]}. '
    "Use standard metric keys whenever present: revenue, revenue_growth_yoy, volume_growth_yoy, "
    "trade_receivables, inventory, trade_payables, cogs, ebitda_margin, gross_margin, operating_profit, ad_promo_spend. "
    "Period format: e.g. FY24, FY24-Q1, FY24-Q2, FY24-Q3, FY24-Q4, or Jun 2024. "
    "The quote MUST be a short verbatim excerpt (1-2 sentences or table cell) copied from the document containing the number. "
    "If a value is not stated, omit it. Never infer or estimate numbers."
)

SYS_HYP = (
    "You are a sceptical equity research analyst. Given computed anomalies for ONE company, "
    "pick the most non-obvious, company-specific story. State it as one sentence, give the mechanism, and list "
    "observable implications that must ALSO be true if it holds. Do not give investment advice. "
    'JSON: {"statement":str,"mechanism":str,"implications":[str],"timeline":[[period,event]]}'
)

SYS_ADV = (
    "You are an adversary whose job is to DISPROVE the hypothesis. Given the hypothesis and the evidence so far, "
    "list the strongest alternative explanations (sector-wide effect, base effect, accounting/definition change, "
    "one-off, portfolio change, management explanation) and the specific public evidence to search for each. "
    'JSON: {"alternatives":[{"explanation":str,"search_queries":[str]}],"falsification":str}'
)


def extract_panel(doc_url: str, doc_type: str, title: str, date: str) -> list[dict]:
    text = get_text(doc_url)
    if not text.strip():
        return []
    out = llm.complete_json(SYS_EXTRACT, f"Document ({doc_type}, {title}):\n{text[:45000]}")
    pts = []
    for p in out.get("points", []):
        quote = str(p.get("quote", "")).strip()
        if not quote:
            continue
        passage = verify_passage(Passage(doc_url, doc_type, title, date, quote))
        if passage.verified:                      # unverified numbers are dropped, not trusted
            pts.append({**p, "passage": passage})
    return pts


def run(company: str, max_docs_per_type: int = 2) -> Finding:
    # 1 PROFILE
    print(f"[1/8] PROFILE — discovering sources for '{company}'...")
    sources = discover_sources(company)
    total = sum(len(v) for v in sources.values())
    print(f"       Found {total} source URLs across {len(sources)} doc types")

    # 2 EXTRACT  (generic: same extractor for every company)
    print(f"[2/8] EXTRACT — fetching & parsing documents (max {max_docs_per_type} per type)...")
    panel: list[dict] = []
    for doc_type in ("results", "presentation", "annual_report", "transcript"):
        for s in sources.get(doc_type, [])[:max_docs_per_type]:
            try:
                print(f"       [{doc_type}] {s['url'][:80]}")
                extracted = extract_panel(s["url"], doc_type, s["title"], date="")
                print(f"       [{doc_type}] -> {len(extracted)} verified data points")
                panel += extracted
            except Exception as e:
                safe_err = str(e).encode("ascii", errors="replace").decode("ascii")
                print(f"       [{doc_type}] SKIP — {safe_err}")
                continue
    print(f"       Total extracted: {len(panel)} verified data points across all docs")

    # 3 SCAN: group by metric and let the LLM-chosen hypothesis step see computed facts.
    print(f"[3/8] SCAN — computing trends and divergence across {len(panel)} points...")
    series: dict[str, list[tuple[str, float]]] = {}
    for p in panel:
        try:
            val = float(p["value"])
            series.setdefault(p["metric"], []).append((str(p["period"]), val))
        except (ValueError, TypeError, KeyError):
            continue
    computed = {}
    for m, vals in series.items():
        vals.sort()
        v = [x for _, x in vals]
        computed[m] = {"periods": [k for k, _ in vals], "values": v, **metrics.trend(v)}
    if "revenue_growth_yoy" in computed and "volume_growth_yoy" in computed:
        n = min(len(computed["revenue_growth_yoy"]["values"]), len(computed["volume_growth_yoy"]["values"]))
        rg = computed["revenue_growth_yoy"]["values"][-n:]
        vg = computed["volume_growth_yoy"]["values"][-n:]
        computed["price_vs_volume_split"] = [metrics.price_volume_split(a / 100, b / 100) for a, b in zip(rg, vg)]
        computed["volume_negative_quarters"] = metrics.count_below(vg)
    print(f"       Computed trends for metrics: {list(computed.keys()) if computed else 'None'}")

    # 4 HYPOTHESISE
    print(f"[4/8] HYPOTHESISE — asking Gemini to form a hypothesis...")
    hyp = llm.complete_json(SYS_HYP, json.dumps({"company": company, "tests": TRACK_C_TESTS, "computed": computed}, default=str))
    print(f"       Hypothesis: {hyp.get('statement', '?')[:100]}")

    # 5 TEST: search each implication, extract supporting quotes from independent sources
    print(f"[5/8] TEST — gathering evidence for {len(hyp['implications'])} implications...")
    evidence: list[EvidenceItem] = []
    for impl in hyp["implications"]:
        print(f"       Testing: {impl[:80]}")
        for r in search(f"{company} {impl}", n=3):
            try:
                text = get_text(r["url"])[:25_000]
            except Exception:
                continue
            try:
                ev = llm.complete_json(
                    "Does this document support, contradict or not bear on the claim? Give a verbatim quote. "
                    'JSON: {"stance":"supports|contradicts|neutral","summary":str,"quote":str}',
                    f"Claim: {impl}\nHypothesis: {hyp['statement']}\nDocument:\n{text}")
                p = verify_passage(Passage(r["url"], "news", r["title"], "", ev.get("quote", "")))
                if p.verified and ev["stance"] != "neutral":
                    evidence.append(EvidenceItem("h1", ev["stance"], ev["summary"], [p], source_class("news")))
            except Exception as e:
                print(f"       [eval] skipping evidence doc due to error: {e!r}")
                continue

    # 6 CHALLENGE: adversary
    print(f"[6/8] CHALLENGE — adversary trying to disprove hypothesis ({len(evidence)} evidence items so far)...")
    try:
        adv = llm.complete_json(SYS_ADV, json.dumps({"hypothesis": hyp, "evidence": [e.summary for e in evidence]}))
    except Exception as e:
        print(f"       [adversary] could not generate challenge ({e!r}), using fallback...")
        adv = {"alternatives": []}

    peer_explains = False
    for alt in adv.get("alternatives", [])[:2]:
        for q in alt.get("search_queries", [])[:1]:
            for r in search(f"{company} {q}", n=2):
                try:
                    text = get_text(r["url"])[:20_000]
                except Exception:
                    continue
                try:
                    ev = llm.complete_json(
                        'Does this document support the ALTERNATIVE explanation? JSON: {"supports_alternative":bool,"summary":str,"quote":str}',
                        f"Alternative: {alt['explanation']}\nDocument:\n{text}")
                    if ev.get("supports_alternative"):
                        p = verify_passage(Passage(r["url"], "news", r["title"], "", ev.get("quote", "")))
                        if p.verified:
                            evidence.append(EvidenceItem("h1", "contradicts", f"[{alt['explanation']}] {ev['summary']}", [p], source_class("news")))
                            if "sector" in alt["explanation"].lower():
                                peer_explains = True
                except Exception:
                    continue

    # 7 VERIFY + grade
    print(f"[7/8] VERIFY — grading evidence strength...")
    unresolved = len(contradictions(evidence))
    level, reasoning = grade(evidence, peer_explains, unresolved)
    print(f"       Strength: {level}")

    # 8 FINDING
    print(f"[8/8] REPORT — assembling final finding...")
    counter = next((e.summary for e in evidence if e.stance == "contradicts"), adv.get("alternatives", [{}])[0].get("explanation", "None found") if adv.get("alternatives") else "None found")
    return Finding(
        company=company, discovery=hyp.get("statement", ""),
        why_it_matters=[hyp.get("mechanism", "")],
        evidence=evidence, timeline=[tuple(t) for t in hyp.get("timeline", [])],
        numbers=computed, counterargument=counter, falsification=adv.get("falsification", "None stated"),
        strength=level, strength_reasoning=reasoning,
    )
