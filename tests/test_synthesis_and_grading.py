from nextsignal.agent import synthesis as SY, verify as V, peers as PE
from nextsignal.models import EvidenceItem, Passage


def ev(stance, doc_type, url, quote="q", summary="s"):
    p = Passage(url, doc_type, "t", "", quote, verified=True)
    return EvidenceItem("h1", stance, summary, [p], V.source_class(doc_type))


def test_number_grounding_catches_invented_figures():
    g = SY.numbers_in("Net profit 15059, operating profit 15039, other income explains 81% of the increase; "
                      "exceptional gain of Rs 4,611 crore", include_small_ints=True)
    assert SY.ungrounded("Net profit grew 41% to Rs 15,059 crore (FY26) on a 4,611 crore gain", g + [41.13]) == []
    assert SY.ungrounded("The gain was Rs 7,200 crore", g) == [7200.0]
    assert SY.ungrounded("over 3 years, 2 of 3 peers moved", g) == []          # small counts are not checked
    assert SY.ungrounded("In FY26-Q3 and Q3 FY26, 2025 base", g) == []          # period labels are not numbers


def test_synthesis_drops_ungrounded_bullets(monkeypatch):
    evidence = [ev("explains", "news", "https://m.com/a", quote="a one-off gain of Rs 4,611 crore from the ice cream demerger")]
    monkeypatch.setattr(SY.llm, "complete_json", lambda s, u, **k: {
        "discovery": "FY26 net profit rose 41% but a Rs 4,611 crore demerger gain explains the jump.",
        "why_it_matters": ["Reported growth overstates operations: the gain is 4,611 crore.",
                           "Analysts expect a Rs 9,999 crore buyback.",                      # invented
                           "Comparability is distorted until the base is restated."],
        "counterargument": "Continuing PAT was flat.", "falsification": "Other income stays above 1,000 for 4 quarters."})
    res, notes = SY.synthesize("X", "FY26 net profit grew 41%", {"n": [15059, 10671, 41.13]}, evidence, [], "")
    assert len(res["why_it_matters"]) == 2 and any("9999" in n or "9999.0" in n for n in notes)
    assert res["discovery"].startswith("FY26 net profit rose 41%")


def test_explains_counts_as_independent_support_but_not_as_contradiction():
    items = [ev("supports", "results", "https://www.screener.in/x"),
             ev("explains", "annual_report", "https://www.hul.co.in/ar.pdf"),
             ev("explains", "news", "https://etretail.com/a"),
             ev("contradicts", "news", "https://other.com/b")]
    assert set(V.independence(items)["classes"]) == {"company_primary", "media"}
    level, why = V.grade(items, False, len(V.contradictions(items)))
    assert level == "Moderate"          # was Weak when explanations were mislabelled as contradictions


def test_doc_type_inference():
    f = lambda u, t="": V.infer_doc_type(u, t, "Hindustan Unilever")
    assert f("https://www.hul.co.in/files/annual-report-2025-26.pdf") == "annual_report"
    assert f("https://www.hul.co.in/files/hul-jq-26-results.pdf") == "results"
    assert f("https://www.youtube.com/watch?v=abc", "HUL Q3 results LIVE") == "news"
    assert f("https://www.investing.com/news/transcripts/earnings-call-transcript-hul") == "transcript"
    assert f("https://www.bseindia.com/xml-data/corpfiling/x.pdf") == "filing"


def test_peer_selection_uses_track_universe_not_industry_tags():
    peers, rule = PE.pick_peers("HINDUNILVR", ["ITC", "HNDFDS", "GODAVARIB"], 5)
    assert "HNDFDS" not in peers and "GODAVARIB" not in peers and "NESTLEIND" in peers and "universe group" in rule
    peers, rule = PE.pick_peers("UNKNOWNCO", ["ITC", "HNDFDS"], 5)
    assert peers == ["ITC"] and "restricted" in rule
    assert PE.pick_peers("UNKNOWNCO", ["HNDFDS"], 5)[0] == []
    assert PE.symbol_from_url("https://www.screener.in/company/HINDUNILVR/consolidated/") == "HINDUNILVR"
