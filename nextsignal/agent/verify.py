"""Triangulation, quote verification and evidence-strength scoring (all deterministic)."""
from __future__ import annotations
from urllib.parse import urlparse
from ..models import EvidenceItem, Passage
from ..sources.fetch import get_text, quote_in_document

# Independence is judged by source CLASS and publisher domain, not by count of links.
INDEPENDENT_CLASSES = {
    "company_primary": {"filing", "results", "presentation", "annual_report", "transcript"},
    "peer": {"peer"},
    "industry": {"industry"},
    "media": {"news"},
}


def source_class(doc_type: str) -> str:
    for cls, types in INDEPENDENT_CLASSES.items():
        if doc_type in types:
            return cls
    return "other"


def verify_passage(p: Passage) -> Passage:
    """Mark a passage verified only if its quote literally appears in the fetched document."""
    try:
        p.verified = quote_in_document(p.quote, get_text(p.url))
    except Exception:
        p.verified = False
    return p


def independence(items: list[EvidenceItem]) -> dict:
    """Count independent classes and publishers among SUPPORTING, VERIFIED evidence."""
    classes, domains = set(), set()
    for it in items:
        if it.stance != "supports":
            continue
        for p in it.passages:
            if p.verified:
                classes.add(source_class(p.doc_type))
                domains.add(urlparse(p.url).netloc)
    return {"classes": sorted(classes), "domains": sorted(domains)}


def contradictions(items: list[EvidenceItem]) -> list[EvidenceItem]:
    return [it for it in items if it.stance == "contradicts"]


def grade(items: list[EvidenceItem], peer_story_explains: bool, unresolved_contradictions: int) -> tuple[str, str]:
    """Strong / Moderate / Weak with the reasoning spelled out."""
    ind = independence(items)
    n_cls = len(ind["classes"])
    n_dom = len(ind["domains"])
    reasons = [f"{n_cls} independent source classes ({', '.join(ind['classes']) or 'none'}), {n_dom} publishers, verified quotes only"]
    if peer_story_explains:
        reasons.append("peer test shows the pattern is largely sector-wide")
    if unresolved_contradictions:
        reasons.append(f"{unresolved_contradictions} contradicting evidence item(s) not resolved")

    if n_cls >= 3 and not peer_story_explains and unresolved_contradictions == 0:
        level = "Strong"
    elif n_cls >= 2 and unresolved_contradictions <= 1:
        level = "Moderate"
    else:
        level = "Weak"
    return level, "; ".join(reasons)
