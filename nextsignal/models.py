"""Core data structures. Every number and claim carries provenance."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Passage:
    """A verifiable excerpt from a source document."""
    url: str
    doc_type: str          # filing | results | presentation | transcript | annual_report | news | industry | peer
    title: str
    date: str              # ISO date of the document
    quote: str             # exact text copied from the document
    page: Optional[int] = None
    verified: bool = False  # set True only if quote is found in the fetched text


@dataclass
class DataPoint:
    metric: str            # e.g. "volume_growth_yoy", "trade_receivables", "revenue"
    period: str            # e.g. "2025Q3" or "FY2024"
    value: float
    unit: str
    source: Passage


@dataclass
class Hypothesis:
    id: str
    test_name: str                 # which generic divergence test raised it
    statement: str                 # one-sentence claim
    mechanism: str                 # why it might be true
    implications: list[str]        # other observable things that must be true if it holds
    surprise_score: float = 0.0


@dataclass
class EvidenceItem:
    hypothesis_id: str
    stance: str                    # "supports" | "contradicts" | "neutral"
    summary: str
    passages: list[Passage] = field(default_factory=list)
    source_class: str = ""         # used for independence counting


@dataclass
class Finding:
    company: str
    discovery: str
    why_it_matters: list[str]
    evidence: list[EvidenceItem]
    timeline: list[tuple[str, str]]       # (period, event)
    numbers: dict[str, object]
    counterargument: str
    falsification: str
    strength: str                          # Strong | Moderate | Weak
    strength_reasoning: str

    def to_dict(self):
        return asdict(self)
