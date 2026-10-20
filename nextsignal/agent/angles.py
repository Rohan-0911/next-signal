"""Generic divergence-test library for Track C (Consumer, FMCG & Retail).

Each test is a company-agnostic template: it says WHICH metrics to extract and
WHICH relationship to look for. Nothing here names a company. The agent runs
every test on whichever company it is given, then ranks what it finds.

To add a track, add another list of tests; the rest of the pipeline is unchanged.
"""

TRACK_C_TESTS = [
    {
        "name": "price_vs_volume",
        "question": "Is reported growth driven by price/mix rather than volume, contrary to the narrative?",
        "metrics": ["revenue_growth_yoy", "volume_growth_yoy"],
        "implications": [
            "volume growth is flat or negative in multiple recent quarters",
            "management commentary emphasises 'premiumisation' or 'value growth' over volume",
            "peers' volume trend (to separate sector vs company)",
        ],
    },
    {
        "name": "working_capital_vs_revenue",
        "question": "Do receivable days / inventory days / cash conversion cycle diverge from revenue growth?",
        "metrics": ["revenue", "trade_receivables", "inventory", "trade_payables", "cogs"],
        "implications": [
            "receivable days rising while revenue growth is slowing or price-led",
            "auditor / note disclosures on credit terms or distributor financing",
            "peer receivable days (sector-wide credit loosening vs company-specific)",
        ],
    },
    {
        "name": "channel_shift",
        "question": "Is a distribution shift (quick commerce, modern trade, D2C, rural, GT) visible in numbers before headlines?",
        "metrics": ["channel_mix_pct", "segment_revenue", "rural_vs_urban_growth"],
        "implications": [
            "channel share disclosed in presentations or call transcripts across several quarters",
            "margin or A&P spend change coinciding with the shift",
            "peers or industry sources confirming the channel trend",
        ],
    },
    {
        "name": "margin_quality",
        "question": "Is margin change explained by input costs, mix, one-offs or other income rather than operations?",
        "metrics": ["ebitda_margin", "gross_margin", "other_income", "ad_promo_spend", "exceptional_items"],
        "implications": [
            "gross margin vs commodity trend",
            "other income / exceptional items share of profit growth",
            "A&P cuts supporting EBITDA margin",
        ],
    },
    {
        "name": "segment_mix_shift",
        "question": "Has the revenue/profit mix across segments or categories moved away from the public narrative?",
        "metrics": ["segment_revenue", "segment_profit"],
        "implications": [
            "segment disclosures in annual report notes over 5 years",
            "management description of 'core' vs reported segment contribution",
        ],
    },
    {
        "name": "narrative_vs_numbers",
        "question": "Which recurring management claims (e.g. 'volume-led', 'market share gains') are contradicted by their own disclosed data?",
        "metrics": ["management_claims"],
        "implications": [
            "claims repeated across 4+ call transcripts",
            "the disclosed metric that would confirm or refute each claim",
        ],
    },
]
