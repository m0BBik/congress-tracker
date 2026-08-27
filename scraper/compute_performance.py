"""
Computes a "performance since transaction" percentage for every row in
data/senate_transactions.json and writes it back into the same file as a
`performance_pct` field (or null if it couldn't be computed).

WHY THIS RUNS HERE INSTEAD OF IN THE BROWSER
----------------------------------------------
The app originally tried to fetch stock prices straight from the user's
browser (client-side JS -> Stooq). Stooq doesn't send CORS headers, so
browsers block the response outright. Server-to-server requests (like this
script running in GitHub Actions) don't have that particular problem — but
it turns out Stooq separately blocks traffic from cloud/datacenter IP
ranges (which is exactly what GitHub Actions runners use) regardless of
headers, returning a blank "noindex" HTML page instead of data. So this
uses Yahoo Finance's public chart endpoint instead (the same one the
popular `yfinance` Python package wraps) — no API key needed, and it
tolerates server-side/automated traffic much better than Stooq does.

HOW THE NUMBER IS CALCULATED
------------------------------
For each transaction we fetch daily closing prices for its ticker from
Yahoo Finance, starting at the transaction date. `performance_pct` is:
  - for a Purchase: % change from the price near the transaction date to
    the most recent available close (positive = stock went up since they
    bought it)
  - for a Sale: the same % change, but flipped in sign (positive = they
    sold before it fell — i.e. good timing)

This is a simplified approximation, not a real return: it ignores the
exact fill price, dividends, and position size (the law only requires
disclosing an amount *range*, not an exact dollar figure).
"""

import json
import time
from datetime import datetime
from pathlib import Path

import requests

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "senate_transactions.json"
REQUEST_DELAY_SECONDS = 0.4  # be polite to Yahoo's free endpoint

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


def yahoo_symbol(ticker):
    # Yahoo uses a dash for share classes (BRK.B -> BRK-B), same idea as
    # most other providers, and otherwise takes the ticker as-is.
    return ticker.upper().replace(".", "-")


def parse_us_date(mdy):
    return datetime.strptime(mdy, "%m/%d/%Y")


def fetch_price_series(ticker, start_dt, retries=2):
    """Returns (first_close, last_close) or None if unavailable."""
    sym = yahoo_symbol(ticker)
    period1 = int(start_dt.timestamp())
    period2 = int(datetime.now().timestamp())
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
        f"?period1={period1}&period2={period2}&interval=1d"
    )
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code == 429:
                time.sleep(2 * (attempt + 1))  # back off and retry on rate limiting
                continue
            resp.raise_for_status()
            data = resp.json()
            result = data.get("chart", {}).get("result")
            if not result:
                return None
            closes = result[0]["indicators"]["quote"][0]["close"]
            closes = [c for c in closes if c is not None]
            if len(closes) < 2:
                return None
            return closes[0], closes[-1]
        except (requests.RequestException, KeyError, ValueError, IndexError):
            if attempt < retries:
                time.sleep(1)
                continue
            return None
    return None


def main():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        transactions = json.load(f)

    # group row indices by ticker + earliest date needed, so we only hit
    # the network once per ticker instead of once per transaction
    by_ticker = {}
    for i, t in enumerate(transactions):
        ticker = t.get("ticker")
        if not ticker:
            continue
        try:
            dt = parse_us_date(t["date"])
        except (KeyError, ValueError):
            continue
        by_ticker.setdefault(ticker, []).append((i, dt))

    print(f"Fetching prices for {len(by_ticker)} unique tickers...")
    price_cache = {}
    failures_shown = 0
    for n, (ticker, rows) in enumerate(by_ticker.items(), 1):
        earliest = min(dt for _, dt in rows)
        result = fetch_price_series(ticker, earliest)
        price_cache[ticker] = result
        if result is None and failures_shown < 5:
            print(f"  [debug] {ticker}: no usable price data returned")
            failures_shown += 1
        if n % 25 == 0:
            print(f"  ...{n}/{len(by_ticker)} tickers done")
        time.sleep(REQUEST_DELAY_SECONDS)

    computed = 0
    for t in transactions:
        ticker = t.get("ticker")
        prices = price_cache.get(ticker)
        if not prices:
            t["performance_pct"] = None
            continue
        first_close, last_close = prices
        if first_close <= 0:
            t["performance_pct"] = None
            continue
        pct = ((last_close - first_close) / first_close) * 100
        if "sale" in (t.get("type") or "").lower():
            pct = -pct
        t["performance_pct"] = round(pct, 2)
        computed += 1

    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(transactions, f, ensure_ascii=False, indent=2)

    print(f"Computed performance for {computed}/{len(transactions)} transactions.")


if __name__ == "__main__":
    main()

