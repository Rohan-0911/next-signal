# Next Signal — autonomous financial research agent (Track C: Consumer, FMCG & Retail)

Given any listed consumer company, the agent investigates public information on its own and reports a
**non-obvious, evidence-backed finding** with a source trail, a counterargument and a falsification condition.
It is not a summariser: it forms a hypothesis, tests it, then tries to break it.

> Status: pipeline runs end to end with Gemini. Period alignment, data gate and relevance checks are unit-tested offline; live accuracy is still being tuned.
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

## Search keys
Set `GOOGLE_API_KEY` (Gemini) and `TAVILY_API_KEY` (search). PowerShell: `$env:TAVILY_API_KEY="tvly-..."` for this window, or `setx TAVILY_API_KEY "tvly-..."` then open a new terminal.
Test: `python -c "from nextsignal.sources.search import search; print(search('Hindustan Unilever Q2 FY26 underlying volume growth', 5))"`

## Run

```bash
pip install -r requirements.txt

# Set your free Google Gemini API key (from https://aistudio.google.com/apikey)
# Linux/macOS:
export GOOGLE_API_KEY="your_api_key_here"

# Windows (PowerShell):
$env:GOOGLE_API_KEY="your_api_key_here"

$env:TAVILY_API_KEY="tvly-..."

# Run research agent for any company (writes out/<company>.html)
python run.py "<company name>"

# Run offline unit test suite
pytest -q
```

*Research output only. No investment recommendations.*
