# Next Signal — autonomous financial research agent (Track C: Consumer, FMCG & Retail)

Given any listed consumer company, the agent investigates public information on its own and reports a
**non-obvious, evidence-backed finding** with a source trail, a counterargument and a falsification condition.
It is not a summariser: it forms a hypothesis, tests it, then tries to break it.

> Status: Round 1 skeleton. Calculation engine and verification logic are unit-tested.
> The LLM and web stages are implemented but still need live end-to-end testing and tuning on real companies.

## How it works

```
company ─► 1 PROFILE ─► 2 EXTRACT ─► 3 SCAN ─► 4 HYPOTHESISE ─► 5 TEST ─► 6 CHALLENGE ─► 7 VERIFY ─► 8 REPORT
           sources &     docs→panel   generic    one sharp         evidence   adversary     quotes in    8 required
           peers         + quotes     divergence story + testable  from ≥3    tries to      source,      elements,
                                      tests      implications      source     disprove,     independence clickable
                                                                   classes    peer test     graded       sources
```

* **No company-specific logic.** `agent/angles.py` is a library of generic divergence tests (price vs volume,
  working capital vs revenue, channel shift, margin quality, segment mix, narrative vs numbers). The agent runs
  all of them on whatever company it is given and ranks the results.
* **LLM never does arithmetic.** All numbers come from `tools/metrics.py` (price/volume split, receivable days,
  CCC, trend persistence, peer-adjusted gap, surprise score).
* **Anti-hallucination.** Every extracted number and every cited quote must literally appear in the fetched
  document (`sources/fetch.py::quote_in_document`). Unverified items are dropped, not shown.
* **Triangulation.** Evidence strength counts independent *source classes* (company primary, peer, industry,
  media) and publishers, not number of links (`agent/verify.py`).
* **Self-falsification.** An adversary step lists alternative explanations (sector-wide effect, base effect,
  accounting change, one-off, management explanation), searches for each, and states a falsification condition.
  A sector-wide pattern downgrades the evidence grade.

## Run

```bash
pip install -r requirements.txt

# Set your free Google Gemini API key (from https://aistudio.google.com/apikey)
# Linux/macOS:
export GOOGLE_API_KEY="your_api_key_here"

# Windows (PowerShell):
$env:GOOGLE_API_KEY="your_api_key_here"

# Run research agent for any company (writes out/<company>.html)
python run.py "<company name>"

# Run offline unit test suite
pytest -q
```

## Roadmap to the finals (25 Oct)
- 21 Oct: reliable ingestion for BSE/NSE filings, investor presentations, transcripts; quarterly panel schema
- 22 Oct: hypothesis ranking with peer adjustment; adversary step tuned
- 23 Oct: report/dashboard polish with claim→source click-through; run on 5+ companies
- 24 Oct: robustness (non-NIFTY peers, missing data, caching/fallback), live rehearsal
- 25 Oct: finals

*Research output only. No investment recommendations.*
