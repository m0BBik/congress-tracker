"""
Computes a "performance since transaction" percentage for every row in
data/senate_transactions.json and writes it back into the same file as a
`performance_pct` field (or null if it couldn't be computed).

WHY THIS RUNS HERE INSTEAD OF IN THE BROWSER
----------------------------------------------
The app originally tried to fetch stock prices straight from the user's
browser (client-side JS -> Stooq). Stooq doesn't send CORS headers, so
browsers block the response outright — no proxy is fully reliable for this
long-term. Server-to-server requests (like this script running in GitHub
Actions) have no such restriction, so this is the correct place to do it:
compute once a day here, ship the result as plain data, and the page just
displays it — instant, no flaky client-side fetching.

HOW THE NUMBER IS CALCULATED
------------------------------
For each transaction we fetch a daily price history for its ticker from
Stooq, starting at the transaction date. `performance_pct` is:
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
REQUEST_DELAY_SECONDS = 0.3  # be polite to Stooq's free endpoint


def to_stooq_date(dt):
    return dt.strftime("%Y%m%d")


def stooq_symbol(ticker):
    return ticker.lower().replace(".", "-") + ".us"


def parse_us_date(mdy):
    return datetime.strptime(mdy, "%m/%d/%Y")


def fetch_price_series(ticker, start_dt):
    """Returns (first_close, last_close) or None if unavailable."""
    sym = stooq_symbol(ticker)
    d1 = to_stooq_date(start_dt)
    d2 = to_stooq_date(datetime.now())
    url = f"https://stooq.com/q/d/l/?s={sym}&d1={d1}&d2={d2}&i=d"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        lines = [l for l in resp.text.strip().splitlines() if l and not l.startswith("Date")]
        if len(lines) < 2:
            return None
        rows = []
        for line in lines:
            parts = line.split(",")
            if len(parts) < 5:
                continue
            try:
                close = float(parts[4])
            except ValueError:
                continue
            rows.append(close)
        if len(rows) < 2:
            return None
        return rows[0], rows[-1]
    except requests.RequestException:
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
    for n, (ticker, rows) in enumerate(by_ticker.items(), 1):
        earliest = min(dt for _, dt in rows)
        result = fetch_price_series(ticker, earliest)
        price_cache[ticker] = result
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
