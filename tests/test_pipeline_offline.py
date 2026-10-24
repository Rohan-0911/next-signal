"""Run the full pipeline with a fake LLM, fake search and fake documents (no network)."""
from nextsignal.agent import pipeline as PL
from nextsignal.report.render import render

DOC = "\n".join(f"Revenue Q{q} FY{y} was {100+y+q} crore" for y in (25, 26) for q in (1, 2, 3, 4))
DOC += "\n" + "\n".join(f"EBITDA margin Q{q} FY{y} was {23+q/10}%" for y in (25, 26) for q in (1, 2, 3, 4))
DOC += "\nAcme Foods reported that distributor credit days rose in FY26."


def fake_json(system, user, **kw):
    if system.startswith("You extract"):
        pts = [{"metric": "revenue", "period": f"FY{y}-Q{q}", "value": 100 + y + q, "unit": "crore",
                "quote": f"Revenue Q{q} FY{y} was {100+y+q} crore"} for y in (25, 26) for q in (1, 2, 3, 4)]
        pts += [{"metric": "ebitda_margin", "period": f"FY{y}-Q{q}", "value": 23 + q / 10, "unit": "%",
                 "quote": f"EBITDA margin Q{q} FY{y} was {23+q/10}%"} for y in (25, 26) for q in (1, 2, 3, 4)]
        return {"points": pts}
    if "sceptical equity" in system:
        return {"statement": "Margins and revenue diverge", "mechanism": "m", "implications": ["credit days rose"],
                "timeline": [["FY26-Q4", "ok"], ["FY40-Q1", "invented period"]]}
    if "judge" in system:
        return {"stance": "supports", "summary": "credit days rose", "quote": "distributor credit days rose in FY26"}
    if "adversary" in system:
        return {"alternatives": [{"category": "sector", "explanation": "industry wide", "search_queries": ["Acme Foods sector credit"]}],
                "falsification": "credit days fall 2 quarters"}
    return {"supports_alternative": False, "summary": "", "quote": ""}


def patch(monkeypatch, doc):
    monkeypatch.setattr(PL, "discover_sources", lambda c: {"results": [{"url": "https://x.com/r", "title": "R"}]})
    monkeypatch.setattr(PL, "search", lambda q, n=3: [{"url": "https://x.com/n", "title": "N"}])
    monkeypatch.setattr(PL, "get_text", lambda u: doc)
    monkeypatch.setattr("nextsignal.agent.verify.get_text", lambda u: doc)
    monkeypatch.setattr(PL.llm, "complete_json", fake_json)
    monkeypatch.setattr(PL.structured, "load_points", lambda c, symbol=None: [])
    monkeypatch.setattr(PL.screener, "load", lambda c: ([], "", ""))


def test_happy_path(monkeypatch):
    patch(monkeypatch, DOC)
    f = PL.run("Acme Foods")
    assert f.timeline == [("FY26-Q4", "ok")]            # invented period dropped
    assert f.falsification == "credit days fall 2 quarters"
    assert any(e.stance == "supports" for e in f.evidence)
    assert "Acme Foods" in render(f)


def test_gate_refuses_when_no_data(monkeypatch):
    patch(monkeypatch, "Nothing useful here about Acme Foods.")
    f = PL.run("Acme Foods")
    assert f.discovery.startswith("No discovery reported")
    assert f.evidence == [] and f.strength == "Weak"
    render(f)  # must not crash


def test_off_topic_documents_ignored(monkeypatch):
    patch(monkeypatch, DOC.replace("Acme Foods", "Someone Else"))
    f = PL.run("Acme Foods")
    assert f.evidence == []   # doc never mentions the company


def test_nothing_reachable_raises_instead_of_fake_refusal(monkeypatch):
    import pytest
    monkeypatch.setattr(PL, "discover_sources", lambda c: {})
    monkeypatch.setattr(PL.structured, "load_points", lambda c, symbol=None: [])
    monkeypatch.setattr(PL.screener, "load", lambda c: ([], "", ""))
    with pytest.raises(RuntimeError, match="NO DATA RETRIEVED"):
        PL.run("Acme Foods")


def test_finding_roundtrip_for_replay(monkeypatch):
    import json
    from nextsignal.models import finding_from_dict
    patch(monkeypatch, DOC)
    f = PL.run("Acme Foods")
    f2 = finding_from_dict(json.loads(json.dumps(f.to_dict(), default=str)))
    assert render(f2) == render(f)
