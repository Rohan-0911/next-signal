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
import re
from .. import llm
from ..models import Passage, EvidenceItem, Finding
from ..sources.search import discover_sources, search
from ..sources.fetch import get_text
from ..tools import metrics
from .angles import TRACK_C_TESTS
from .verify import verify_passage, grade, contradictions, source_class, infer_doc_type
from . import peers as peermod, synthesis
from . import panel as panelmod
from . import candidates as cand
from ..sources import structured, screener
from ..tools.periods import parse_period, label as period_label

SYS_EXTRACT = (
    "You extract structured financial data from a company document. Output JSON: "
    '{"points":[{"metric":str,"period":str,"value":number,"unit":str,"quote":str}]}. '
    "Use standard metric keys whenever present: revenue, revenue_growth_yoy, volume_growth_yoy, "
    "trade_receivables, inventory, trade_payables, cogs, ebitda_margin, gross_margin, operating_profit, ad_promo_spend, "
    "channel_mix_pct:<channel>, segment_revenue:<segment> (Rs crore only) and segment_growth_yoy:<segment> (percent): one metric key PER channel or segment, and never put a growth rate in a revenue key, "
    "Full-year balance-sheet or P&L figures use period FY24 (no quarter). "
    "Period: for QUARTERS use the period-END month and year exactly as printed in the document header or text (e.g. 'Jun 2025', 'Sep 2025'); do NOT convert to fiscal-year labels and do NOT guess. For FULL YEARS use FY25 (year ended Mar 2025). If the period is not clearly stated, omit the value. "
    "The quote MUST be a short verbatim excerpt (1-2 sentences or table cell) copied from the document containing the number. "
    "Rules: the period must be the quarter or year the number REFERS TO (not the report date). Revenue, profit, cogs, receivables, inventory, payables in Rs crore as stated (use the table unit; if the document is in lakh or million, skip it). "
    "Growth and margins in percent (8.0 means 8%). Prefer consolidated numbers. "
    "If a value is not stated, omit it. Never infer or estimate numbers."
)

SYS_HYP = (
    "You are a sceptical equity research analyst. You are given computed series for ONE company. "
    "RULES: (1) Use ONLY numbers present in `computed`; never add outside facts, events, competitors or "
    "management actions to the statement or timeline. (2) The statement must be a testable claim about "
    "the numbers, e.g. a divergence between two series. (3) Every timeline entry is [period, event] where "
    "period is one of the periods in `computed` and the event restates only values from `computed`. "
    "(4) Put anything that needs outside evidence (channel stuffing, share loss, discounts, etc.) ONLY in "
    "`implications`, written as something that must also be observable if the claim holds. "
    "(4b) `peer_check` compares the company with peers: |z| >= 1.5 means company-specific, small |z| means a sector-wide move; state which. "
    "(4c) `ranked_candidates` are pre-computed, scored divergences (higher score = more non-obvious). Build the hypothesis on the highest-scoring candidate that is NOT flagged one_off; "
    "Candidates flagged mean_reversion_risk are mostly a return to the company's own long-run range: do NOT present them as a new divergence; use them as the counter-argument. Candidates flagged needs_explanation (e.g. profit growth driven by other income) are allowed, but then `implications` must ask what the non-operating item was (exceptional gain, disposal, demerger, treasury income) and where it is disclosed. "
    "mention one_off items only as caveats (they are usually exceptional items, demergers or disposals, already visible in headlines). "
    "Check `data_quality_notes`-style comparability breaks before claiming a growth change. "
    "(5) If the numbers show no non-obvious divergence, say so in `statement` and set implications to []. "
    "Do not give investment advice. "
    'JSON: {"statement":str,"mechanism":str,"implications":[str],"timeline":[[period,event]]}'
)

SYS_ADV = (
    "You are an adversary whose job is to DISPROVE the hypothesis. Given the hypothesis and the evidence so far, "
    "list the strongest alternative explanations and the specific public evidence to search for each. "
    "Each alternative has a category: sector (industry-wide effect), base_effect, accounting, one_off, portfolio, "
    "management (management's own explanation) and an `effect`: 'overturn' if it would make the hypothesis wrong, "
    "'refine' if it would only explain or qualify it (e.g. the cause of a gap the hypothesis already claims). "
    "Search queries must name the company and India. "
    "Also state a falsification condition: concrete future data (metric, direction, number of quarters) that would "
    "overturn the hypothesis. "
    'JSON: {"alternatives":[{"category":str,"effect":"overturn|refine","explanation":str,"search_queries":[str]}],"falsification":str}'
)

SYS_JUDGE = (
    "You judge whether a document tests a specific implication about ONE named company in India. "
    "Stances: 'supports' = the quote confirms the claimed numbers or relationship for THAT company; "
    "'explains' = the quote identifies the CAUSE or accounting treatment of the gap without changing its size "
    "(e.g. an exceptional gain, a demerger, a restatement); 'contradicts' = the quote reports different numbers or a "
    "relationship that undermines the claim; 'neutral' = other company, other country, other topic, or only loosely related. "
    "Before choosing 'contradicts', convert units (1 billion = 100 crore; 1 crore = 10 million) and compare GROWTH RATES, "
    "not levels, because sources define lines differently (EBIT vs EBITDA, consolidated vs standalone). If the growth rates "
    "and direction agree, the answer is 'supports'. "
    'JSON: {"stance":"supports|explains|contradicts|neutral","summary":str,"quote":str}'
)

def mentions_company(company: str, text: str) -> bool:
    """Relevance guard. Short names (ITC, HUL) collide with unrelated firms, so they must appear
    as a whole word followed by a legal suffix (Limited/Ltd) or an exchange tag."""
    t = text.lower()
    name = re.sub(r"\s+", " ", company.lower()).strip()
    if len(name) <= 5 and " " not in name:
        n = re.escape(name)
        return bool(re.search(rf"\b{n}\s+(limited|ltd)\b|\b(nse|bse)\s*[:\-]\s*{n}\b", t))
    first = name.split()[0]
    return name in t or (len(first) >= 5 and re.search(rf"\b{re.escape(first)}\b", t) is not None)


def extract_panel(doc_url: str, doc_type: str, title: str, date: str, focus: str = "") -> list[dict]:
    if "screener.in" in doc_url:        # already loaded as the structured spine; re-extracting it caused one-quarter shifts
        return []
    text = get_text(doc_url)
    if not text.strip():
        return []
    focus_hint = (f"FOCUS: extract these if present: {focus}\n\n" if focus else "")
    out = llm.complete_json(SYS_EXTRACT, f"Document ({doc_type}, {title}):\n{focus_hint}{text[:45000]}")
    pts = []
    raw_points = out.get("points", [])
    for p in raw_points:
        quote = str(p.get("quote", "")).strip()
        if not quote:
            continue
        passage = verify_passage(Passage(doc_url, doc_type, title, date, quote))
        if passage.verified:                      # unverified numbers are dropped, not trusted
            pts.append({**p, "passage": passage})
    print(f"       [extract] model returned {len(raw_points)} points, {len(pts)} verified against the document text")
    return pts


def insufficient(company: str, why: str, notes: list[str], computed: dict) -> Finding:
    """Honest refusal: no hypothesis is formed when verified data is too thin."""
    return Finding(
        company=company,
        discovery=f"No discovery reported: insufficient verified data ({why}).",
        why_it_matters=["The agent refuses to speculate without verified, period-aligned numbers."],
        evidence=[], timeline=[], numbers={**computed, "data_quality_notes": notes},
        counterargument="Not applicable: no hypothesis was formed.",
        falsification="Not applicable: no hypothesis was formed.",
        strength="Weak", strength_reasoning=f"Refused to hypothesise: {why}",
    )


def run(company: str, max_docs_per_type: int = 4) -> Finding:
    # 1 PROFILE
    print(f"[1/8] PROFILE - discovering sources for '{company}'...")
    sources = discover_sources(company)
    total = sum(len(v) for v in sources.values())
    print(f"       Found {total} source URLs across {len(sources)} doc types")

    # 2 EXTRACT (generic). Stop as soon as the panel has enough verified, period-aligned data.
    print(f"[2/8] EXTRACT - fetching & parsing documents (up to {max_docs_per_type} per type)...")
    points: list[dict] = []
    spine, scr_html, scr_url = screener.load(company)
    src = "screener"
    if not spine:
        spine, src = structured.load_points(company), "yfinance"
    print(f"       Structured spine ({src}): {len(spine)} data points" + ("" if spine else " - falling back to documents"))
    points += spine
    built = panelmod.build_panel(points)
    derived: dict = {}
    done = False
    for doc_type in ("results", "presentation", "annual_report", "transcript"):
        if done:
            break
        for s in sources.get(doc_type, [])[:max_docs_per_type]:
            try:
                print(f"       [{doc_type}] {s['url'][:80]}")
                extracted = extract_panel(s["url"], doc_type, s["title"], date="")
                print(f"       [{doc_type}] -> {len(extracted)} verified data points")
                points += extracted
            except Exception as e:
                safe_err = str(e).encode("ascii", errors="replace").decode("ascii")
                print(f"       [{doc_type}] SKIP - {safe_err}")
                continue
            built = panelmod.build_panel(points)
            derived = panelmod.derive(built["panel"])
            if panelmod.rich_enough(built["panel"], derived):
                print("       Rich enough: at least 3 of 5 divergence tests can run")
                done = True
                break
    # Targeted retrieval: for tests that cannot run yet, search specifically for the missing metrics.
    for test in panelmod.missing_tests(built["panel"], derived)[:3]:
        need, hint = panelmod.TEST_NEEDS[test]
        print(f"       [targeted] {test}: need {need}")
        for r in search(f"{company} {hint}", n=3)[:2]:
            try:
                ex = extract_panel(r["url"], "annual_report" if "annual" in hint else "presentation", r["title"], "", focus=hint)
                print(f"       [targeted] {r['url'][:70]} -> {len(ex)} verified data points")
                points += ex
            except Exception as e:
                print(f"       [targeted] SKIP - {str(e)[:80]}")
        built = panelmod.build_panel(points)
        derived = panelmod.derive(built["panel"])
    # Volume growth is rarely in numeric tables: fetch it quarter by quarter from results releases / transcripts.
    if "price_vs_volume" in panelmod.missing_tests(built["panel"], derived):
        qs = sorted(panelmod.quarterly(built["panel"], "revenue"))[-4:]
        for fy, q in reversed(qs):
            end_mon = {1: "Jun", 2: "Sep", 3: "Dec", 4: "Mar"}[q]
            end_year = fy if q == 4 else fy - 1
            focus = (f"volume_growth_yoy (underlying volume growth, or like-for-like / same-store growth for retailers) and "
                     f"revenue_growth_yoy for the quarter ended {end_mon} {end_year}. Use period '{end_mon} {end_year}'.")
            print(f"       [volume] Q{q} FY{fy % 100:02d}")
            for r in search(f"{company} Q{q} FY{fy % 100:02d} results underlying volume growth press release", n=3)[:2]:
                try:
                    ex = [x for x in extract_panel(r["url"], "presentation", r["title"], "", focus=focus)
                          if x["metric"] in ("volume_growth_yoy", "revenue_growth_yoy")]
                    print(f"       [volume] {r['url'][:70]} -> {len(ex)} points")
                    points += ex
                except Exception as e:
                    print(f"       [volume] SKIP - {str(e)[:80]}")
        built = panelmod.build_panel(points)
        derived = panelmod.derive(built["panel"])
    print(f"       Total extracted: {len(points)} verified data points")

    if not points and total == 0:
        raise RuntimeError("NO DATA RETRIEVED: no source was reachable (network/DNS problem or blocking). "
                           "Not writing a report. Check your connection and rerun.")

    # 3 SCAN: period-aligned panel, deterministic derivations
    print("[3/8] SCAN - computing period-aligned trends and divergences...")
    computed = panelmod.summarise(built["panel"], derived)
    cov = panelmod.coverage(built["panel"], derived)
    computed["test_coverage"] = cov
    print("       Test coverage: " + "; ".join(f"{t}={v}" for t, v in cov.items()))
    # Peer check: same loader on peers, so "company-specific vs sector-wide" is measured, not argued.
    peer_by_sym = {}
    if scr_html:
        peer_by_sym: dict = {}
        own_sym = peermod.symbol_from_url(scr_url)
        picked, rule = peermod.pick_peers(own_sym, screener.peers_for(scr_html, scr_url, limit=8), limit=5)
        print(f"       Peers ({rule}): {picked}")
        for sym in picked:
            pp, _, _ = screener.load(sym)
            if pp:
                peer_by_sym[sym] = panelmod.build_panel(pp)["panel"]
        pc = panelmod.peer_check(built["panel"], list(peer_by_sym.values()))
        print(f"       Peer check: peers {list(peer_by_sym)} metrics {list(pc)}")
        computed["peer_detail"] = {sym: {k: (None if v is None else round(v, 2)) for k, v in panelmod.key_changes(pp).items()}
                                   for sym, pp in peer_by_sym.items()}
        if pc:
            computed["peer_check"] = pc
    notes = built["notes"] + panelmod.growth_mismatches(built["panel"], derived)
    ranked = cand.rank_candidates(built["panel"], derived, computed.get("peer_check"))
    computed["ranked_candidates"] = ranked[:6]
    selected = next((c for c in ranked if "one_off" not in c["flags"] and c["score"] > 0), None)
    computed["selected_candidate"] = selected["id"] if selected else None
    print("       Ranked candidates: " + " | ".join(f"{c['id']}={c['score']}" for c in ranked[:5]))
    for n in notes[:8]:
        print(f"       note: {n}")
    ok, why = panelmod.enough_data(built["panel"], derived)
    if not ok:
        print(f"       GATE: {why} -> refusing to hypothesise")
        return insufficient(company, why, notes, computed)

    # 4 HYPOTHESISE (grounded in computed numbers only)
    print("[4/8] HYPOTHESISE - forming a hypothesis from computed numbers...")
    hyp = llm.complete_json(SYS_HYP, json.dumps({"company": company, "tests": TRACK_C_TESTS, "computed": computed}, default=str))
    print(f"       Hypothesis: {hyp.get('statement', '?')[:100]}")
    valid_periods = {pl for v in computed.values() if isinstance(v, dict) for pl in v.get("periods", [])}
    valid_periods |= {x["period"] for x in computed.get("price_vs_volume_split", [])}
    timeline = []
    for t in hyp.get("timeline", []):
        try:
            key = parse_period(t[0])
            if key and period_label(key) in valid_periods:
                timeline.append((period_label(key), str(t[1])))
        except Exception:
            continue

    # 5 TEST
    implications = hyp.get("implications", [])
    print(f"[5/8] TEST - gathering evidence for {len(implications)} implications...")
    numeric_ev = cand.numeric_evidence(selected, built["panel"], peer_by_sym, scr_url) if (selected and scr_url) else []
    evidence: list[EvidenceItem] = list(numeric_ev)
    print(f"       Numeric evidence items (company + peers): {len(numeric_ev)}")
    for impl in implications:
        print(f"       Testing: {impl[:80]}")
        for r in search(f"{company} India {impl}", n=3):
            try:
                text = get_text(r["url"])[:25_000]
            except Exception:
                continue
            if not mentions_company(company, text):
                continue
            try:
                ev = llm.complete_json(
                    SYS_JUDGE,
                    f"Company: {company}\nImplication: {impl}\nHypothesis: {hyp['statement']}\nDocument:\n{text}")
                dt = infer_doc_type(r["url"], r["title"], company)
                p = verify_passage(Passage(r["url"], dt, r["title"], "", ev.get("quote", "")))
                if p.verified and ev["stance"] in ("supports", "explains", "contradicts"):
                    evidence.append(EvidenceItem("h1", ev["stance"], ev["summary"], [p], source_class(dt)))
            except Exception as e:
                print(f"       [eval] skipping evidence doc due to error: {e!r}")
                continue

    # 5b EXPLAIN: if the gap needs an explanation, search around the quarter where it appeared
    for q, impl in cand.explanation_queries(company, ranked, selected):
        print(f"       Explaining: {q[:80]}")
        for r in search(q, n=3):
            try:
                text = get_text(r["url"])[:25_000]
                if not mentions_company(company, text):
                    continue
                ev = llm.complete_json(SYS_JUDGE, f"Company: {company}\nImplication: {impl}\nHypothesis: {hyp['statement']}\nDocument:\n{text}")
                dt = infer_doc_type(r["url"], r["title"], company)
                p = verify_passage(Passage(r["url"], dt, r["title"], "", ev.get("quote", "")))
                if p.verified and ev["stance"] in ("supports", "explains", "contradicts"):
                    evidence.append(EvidenceItem("h1", ev["stance"], ev["summary"], [p], source_class(dt)))
            except Exception as e:
                print(f"       [explain] skipped: {str(e)[:60]}")

    # 6 CHALLENGE
    print(f"[6/8] CHALLENGE - adversary trying to disprove ({len(evidence)} evidence items so far)...")
    try:
        adv = llm.complete_json(SYS_ADV, json.dumps({"hypothesis": hyp, "evidence": [e.summary for e in evidence]}))
    except Exception as e:
        print(f"       [adversary] could not generate challenge ({e!r}), using fallback...")
        adv = {"alternatives": []}

    peer_explains = False
    for alt in adv.get("alternatives", [])[:3]:
        for q in alt.get("search_queries", [])[:1]:
            for r in search(q if company.lower() in q.lower() else f"{company} {q}", n=2):
                try:
                    text = get_text(r["url"])[:20_000]
                except Exception:
                    continue
                if not mentions_company(company, text):
                    continue
                try:
                    ev = llm.complete_json(
                        "Does this document, about THIS company in India, support the ALTERNATIVE explanation? "
                        'JSON: {"supports_alternative":bool,"summary":str,"quote":str}',
                        f"Company: {company}\nAlternative: {alt.get('explanation','')}\nDocument:\n{text}")
                    if ev.get("supports_alternative"):
                        dt = infer_doc_type(r["url"], r["title"], company)
                        p = verify_passage(Passage(r["url"], dt, r["title"], "", ev.get("quote", "")))
                        if p.verified:
                            overturns = str(alt.get("effect", "overturn")).lower() != "refine"
                            evidence.append(EvidenceItem("h1", "contradicts" if overturns else "explains",
                                                         f"[{alt.get('category','alt')}] {ev['summary']}", [p], source_class(dt)))
                            if overturns and str(alt.get("category", "")).lower() == "sector":
                                peer_explains = True
                except Exception:
                    continue

    # 7 VERIFY + grade
    print("[7/8] VERIFY - grading evidence strength...")
    unresolved = len(contradictions(evidence))
    level, reasoning = grade(evidence, peer_explains, unresolved)
    if not implications:
        level, reasoning = "Weak", "Numbers show no testable divergence; no implications to test. " + reasoning
    print(f"       Strength: {level}")

    # 8 FINDING
    print("[8/8] REPORT - assembling final finding...")
    alts = adv.get("alternatives", [])
    counter = next((e.summary for e in evidence if e.stance == "contradicts"),
                   alts[0].get("explanation", "None found") if alts else "None found")
    det_fals = cand.falsification_for(selected, built["panel"])
    draft = adv.get("falsification") or ""
    grounded_base = synthesis.numbers_in(json.dumps(computed, default=str) + " " + (selected["claim"] if selected else ""), include_small_ints=True)
    falsification = draft if (draft and not synthesis.ungrounded(draft, grounded_base)) else (det_fals or draft or
        "Reconsider if the cited metrics reverse direction for two consecutive quarters.")
    discovery = hyp.get("statement", "")
    why = (["Hypothesised mechanism (not independently verified): " + hyp.get("mechanism", "")]
           if implications else
           ["No divergence was found in the tests that had enough verified data. Tests that could not run are listed under coverage; "
            "absence of a finding is not evidence of absence."])
    syn_notes: list[str] = []
    if implications and evidence:
        print("       SYNTHESIS - writing final note from verified evidence, with number check...")
        try:
            key = {"selected_candidate": selected, "ranked_candidates": ranked[:3],
                   "price_vs_volume": computed.get("price_vs_volume_split"),
                   "annual": {k: v for k, v in computed.items() if k.endswith("_annual") and isinstance(v, dict)},
                   "quarterly": {k: v for k, v in computed.items() if k in ("revenue", "operating_profit", "net_profit", "other_income", "ebitda_margin") and isinstance(v, dict)}}
            res, syn_notes = synthesis.synthesize(company, selected["claim"] if selected else discovery, key, evidence, alts, falsification)
            discovery = res["discovery"] or discovery
            counter = res["counterargument"] or counter
            falsification = res["falsification"] or falsification  # drafted above: grounded model text, else deterministic
            if res["why_it_matters"]:
                why = res["why_it_matters"]
            for n in syn_notes:
                print(f"       synthesis note: {n}")
        except Exception as e:
            print(f"       [synthesis] skipped ({str(e)[:80]}); keeping the earlier draft")
    return Finding(
        company=company, discovery=discovery, why_it_matters=why,
        evidence=evidence, timeline=timeline,
        numbers={**computed, "data_quality_notes": notes + syn_notes}, counterargument=counter, falsification=falsification,
        strength=level, strength_reasoning=reasoning,
    )
