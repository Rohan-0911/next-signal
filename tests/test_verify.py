from nextsignal.models import Passage, EvidenceItem
from nextsignal.sources.fetch import quote_in_document
from nextsignal.agent import verify


def test_quote_must_appear_in_source():
    doc = "Underlying volume growth was  (2.1)%  in the quarter,\nwhile pricing contributed 6%."
    assert quote_in_document("underlying volume growth was (2.1)% in the quarter", doc)
    assert not quote_in_document("volume growth was 5% in the quarter", doc)


def _ev(stance, doc_type, url):
    p = Passage(url, doc_type, "t", "2025-01-01", "q", verified=True)
    return EvidenceItem("h1", stance, "s", [p], verify.source_class(doc_type))


def test_grading_needs_independent_classes():
    one_class = [_ev("supports", "presentation", "https://a.com/1"), _ev("supports", "results", "https://a.com/2")]
    assert verify.grade(one_class, False, 0)[0] == "Weak"
    three = one_class + [_ev("supports", "peer", "https://b.com/1"), _ev("supports", "industry", "https://c.com/1")]
    assert verify.grade(three, False, 0)[0] == "Strong"
    assert verify.grade(three, True, 0)[0] == "Moderate"  # sector-wide pattern downgrades


def test_unverified_quotes_do_not_count():
    p = Passage("https://a.com", "presentation", "t", "", "q", verified=False)
    it = EvidenceItem("h1", "supports", "s", [p])
    assert verify.independence([it])["classes"] == []
