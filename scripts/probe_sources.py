"""Which public sources actually load from YOUR machine, and do they contain usable tables?
Run:  python scripts/probe_sources.py            (defaults to HUL)
Paste the output back so we can choose the primary data source for the finals.
"""
import sys
import requests

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
     "Accept-Language": "en-US,en;q=0.9"}
SYMBOL = sys.argv[1] if len(sys.argv) > 1 else "HINDUNILVR"
BSE = sys.argv[2] if len(sys.argv) > 2 else "500696"

TARGETS = {
    "screener (consolidated)": (f"https://www.screener.in/company/{SYMBOL}/consolidated/", {}),
    "BSE announcements API": (f"https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno=1&strCat=Result&strPrevDate=20250101&strScrip={BSE}&strSearch=P&strToDate=20261021&strType=C",
                             {"Referer": "https://www.bseindia.com/", "Origin": "https://www.bseindia.com"}),
    "BSE results page": (f"https://www.bseindia.com/stock-share-price/x/{SYMBOL.lower()}/{BSE}/financials-results/", {}),
    "NSE corp filings": (f"https://www.nseindia.com/api/corporates-financial-results?index=equities&symbol={SYMBOL}", {"Referer": "https://www.nseindia.com/"}),
    "Trendlyne transcripts": (f"https://trendlyne.com/conference-calls/560/{SYMBOL}/", {}),
    "stockanalysis transcripts": (f"https://stockanalysis.com/quote/nse/{SYMBOL}/transcripts/", {}),
    "Economic Times quarterly": (f"https://economictimes.indiatimes.com/{SYMBOL.lower()}/quarterly", {}),
}

for name, (url, extra) in TARGETS.items():
    try:
        r = requests.get(url, headers={**H, **extra}, timeout=15)
        body = r.text[:150].replace("\n", " ")
        print(f"[{r.status_code}] {name:28s} {len(r.content):>9,} bytes  {body!r}")
    except Exception as e:
        print(f"[ERR] {name:28s} {str(e)[:100]}")

try:
    import yfinance as yf  # optional: pip install yfinance
    t = yf.Ticker(f"{SYMBOL}.NS")
    q = t.quarterly_income_stmt
    print(f"[yfinance] quarterly income columns: {len(q.columns)}  rows: {list(q.index[:6])}")
    b = t.balance_sheet
    print(f"[yfinance] annual balance sheet columns: {len(b.columns)}  has receivables: {any('eceivable' in str(i) for i in b.index)}")
except Exception as e:
    print(f"[yfinance] unavailable: {str(e)[:100]}")
