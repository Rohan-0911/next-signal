# Next Signal

An autonomous research agent for consumer companies (FMCG, retail, jewellery, paints). Give it a listed company and it investigates public information on its own, then reports **one non-obvious, evidence-backed finding**: with a source trail, a counterargument, a falsification condition and an honest evidence grade.

It is not a summariser. It computes what the numbers say, forms a hypothesis, tries to break it, and only reports what survives. When the data is too thin, it says so and refuses to guess.

Built for the *Finding the Next Signal* hackathon (ATMOS 2026, BITS Pilani Hyderabad), Track C, and continued afterwards as a personal fintech project.

> Research output only. Not investment advice.

## What a report contains

1. **Discovery**: one sentence, with the numbers.
2. **Why it matters**: 3 to 5 bullets.
3. **Evidence trail**: every item with its source link, a verified quote and a stance (supports / explains / contradicts).
4. **Timeline** and **numbers**: period-aligned tables, price-vs-volume split, peer check.
5. **Strongest counterargument.**
6. **Falsification condition**: the future data that would overturn the finding.
7. **Evidence strength**: Strong / Moderate / Weak, with the reasoning shown.

### Example (Hindustan Unilever, FY26)

> FY26 net profit grew 41% while operating profit grew only 2.3%. Other income explains 81% of the net-profit increase, from a one-off gain on the demerger of the ice-cream business. 0 of 5 peers show the same pattern. **Evidence strength: Moderate** (2 independent source classes).

## How it works

```
company -> PROFILE -> EXTRACT -> SCAN -> HYPOTHESISE -> TEST -> CHALLENGE -> VERIFY -> REPORT
```

| Stage | What happens |
|---|---|
| **1 Profile** | Resolves the company, finds filings, results, presentations, transcripts and annual reports through web search. |
| **2 Extract** | Builds a numeric spine from Screener.in (12 quarters of P&L, about 12 years of annual data, working-capital ratios), with yfinance as fallback. An LLM reads documents for text-only metrics (volume growth, channel mix, segments). Every extracted number must appear literally in the document text, or it is dropped. |
| **3 Scan** | Python (never the LLM) runs generic divergence tests: price vs volume, working capital vs revenue, margin quality (including a profit bridge showing how much profit growth came from other income), channel shift, segment mix. Peers come from a track-level universe. |
| **4 Hypothesise** | Candidates are ranked by `surprise score = magnitude x persistence x company-specificity x (1 - narrative coverage)`. One-offs and mean-reversion risks (a value that is just returning to its own 12-year range) are penalised. The LLM states the top candidate and what else must be true if it holds. |
| **5 Test** | Searches for evidence on each implication, plus explanations for the gap (exceptional items, demergers, accounting changes). |
| **6 Challenge** | An adversary step tries to disprove the finding: sector-wide effect, base effect, accounting change, one-off, management's own explanation. |
| **7 Verify** | Quotes are checked against the fetched source text. Evidence is graded by rule. |
| **8 Report** | Writes the note. Any sentence containing a number that is not in the computed numbers or a verified quote is dropped. |

## Design principles

* **No company-specific logic.** The same pipeline runs on any consumer company. Peers, units and segment names are discovered at runtime.
* **The LLM never does arithmetic.** All numbers come from tested Python in `nextsignal/tools/metrics.py` and `agent/panel.py`.
* **Every claim is traceable.** Claim -> computed metric -> source passage -> document.
* **Independence is counted by source class, not link count.** Classes: company primary (filings, decks, transcripts), peer, industry, media, structured data (aggregator numbers such as Screener count as one class, however many ways they are sliced). Social media posts never count as independent evidence.
* **Refuse rather than guess.** If too few verified periods exist, the agent reports "insufficient verified data" instead of inventing a story.
* **Period-aware.** Indian fiscal year (Apr to Mar). `Jun 2026` is FY27-Q1. Series are aligned by period, never by position.

### Evidence grading

| Strength | Rule |
|---|---|
| **Strong** | 3 or more independent source classes, quotes verified, not explained by a sector-wide effect, no unresolved contradictions |
| **Moderate** | 2 or more classes and at most one unresolved contradiction |
| **Weak** | Otherwise |

"Explains" evidence identifies the cause of a gap without overturning the finding, so it counts as support, not as a contradiction.

## Setup

Requires Python 3.10+.

```bash
git clone https://github.com/Rohan0911/next-signal.git
cd next-signal
pip install -r requirements.txt
cp .env.example .env        # Windows: copy .env.example .env
```

Fill in `.env` (never commit it):

```
GOOGLE_API_KEY=       # https://aistudio.google.com/apikey
TAVILY_API_KEY=       # https://tavily.com  (web search with page content)
NS_MODEL=gemini-3.5-flash-lite
NS_MIN_INTERVAL=4     # seconds between LLM calls, avoids free-tier rate limits
```

Without a Tavily key the agent falls back to DuckDuckGo search, with weaker retrieval from company sites.

## Usage

```bash
python run.py "Hindustan Unilever"          # full run -> out/<company>_<timestamp>.html and .json
python run.py TATACONSUM                    # a Screener symbol always resolves
python run.py --replay "Hindustan Unilever" # re-render the latest saved run (offline)
pytest -q                                   # offline test suite
```

* A refused or failed run never overwrites the last good report (`out/<company>.html`).
* The run ends with `LLM calls: N | failed: N | rate-limit waits: N`. If `failed` is above 0, evidence may have been lost to quota limits. Wait and rerun before trusting the grade.
* Free-tier Gemini keys can hit per-minute and per-day limits. The client paces requests and honours retry delays; enabling billing removes the problem.

## Project layout

```
run.py                      CLI, preflight checks, replay, output handling
nextsignal/
  llm.py                    Gemini wrapper: pacing, 429 backoff, model fallback, call stats
  models.py                 Passage, EvidenceItem, Finding
  agent/
    pipeline.py             the 8-stage loop
    panel.py                period-aligned panel, conflict resolution, scale/outlier guards
    candidates.py           ranking, own-history check, profit bridge, falsification
    synthesis.py            final note with number grounding
    verify.py               quote verification, source classes, grading
    peers.py, angles.py     peer selection, generic divergence tests
  sources/                  screener, search (Tavily/DuckDuckGo), fetch, structured
  tools/                    metrics.py, periods.py
  report/render.py          HTML report
  data/track_universe.json  peer groups (staples, retail, jewellery, paints)
scripts/probe_sources.py    checks which public sources are reachable
tests/                      50 offline tests
```

## Known limitations

* **Free public data only.** Screener.in is the numeric backbone. Exchange APIs (BSE/NSE) block automated access, so filings are read through search and company IR sites.
* **Extraction noise.** LLM-read tables can mislabel units or columns. Scale and outlier guards catch many cases, but some noise remains in the numbers table.
* **Duplicate evidence.** The same source can appear more than once in the evidence trail.
* **Not always non-obvious.** The top-ranked story can already be widely reported (for example a demerger gain). The agent finds it independently from the numbers, but a known story is still a known story.
* **Name resolution.** Misspelled company names fall back to shorter queries; use the exchange symbol if resolution fails.
* **Single-fiscal-year focus.** Quarterly volume and channel data depend on what companies disclose in text.

## Roadmap

* Deduplicate evidence by URL and quote.
* Evaluation table across 10 to 15 companies with manual checking of each finding.
* Richer report page (profit-bridge chart, evidence cards).
* Cache LLM responses to cut repeat calls.

## Data sources

Screener.in (financials), company investor-relations pages, annual reports, earnings-call transcripts, news and Yahoo Finance via search, all public. Respect each site's terms of use.

*Research output only. No investment recommendations.*