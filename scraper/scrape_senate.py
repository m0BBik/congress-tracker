"""
Scraper for efdsearch.senate.gov Periodic Transaction Reports (PTR).

WHAT THIS DOES
---------------
1. Opens a headless browser, accepts the required "prohibition agreement"
   (the Senate's EFD system will not show any data until this is accepted
   in-session — there is no way around this with plain HTTP requests, which
   is why this uses Playwright instead of `requests`).
2. Filters to filer type = Senator, report type = Periodic Transaction Report.
3. Paginates through the results table and collects each report's link.
4. Visits each new report link (skips ones already saved from a previous run)
   and parses the transactions table out of the report page.
5. Merges newly found transactions into data/senate_transactions.json,
   de-duplicated by report URL + row index, and writes the file back out.

NOTES / LIMITATIONS
--------------------
- This scrapes a real, official, public government website. It is not an
  official API and the site's markup can change at any time — if it does,
  the CSS selectors below will need updating (that's normal maintenance
  for any scraper, not a sign of something being broken beyond repair).
- Only electronically-filed HTML reports are parsed. A number of older or
  paper-filed reports are scanned PDFs; those are skipped here (flagged in
  the output as `"skipped_pdf": true`) since OCR is a separate, heavier
  problem. Most current-day filings are electronic.
- Be a good citizen: this script runs once a day (see the GitHub Actions
  workflow), uses modest concurrency, and only fetches *new* report pages
  on each run — it does not re-scrape the entire site every time.
- I wrote this based on the documented structure of the EFD search site and
  prior open-source scrapers of it, but I have not been able to run it live
  against efdsearch.senate.gov from this environment (no network access to
  that domain here). Treat the first run as a test: check the Action logs
  and the resulting JSON before relying on it.
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE_URL = "https://efdsearch.senate.gov"
HOME_URL = f"{BASE_URL}/search/home/"
DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "senate_transactions.json"

# Only look back this many days for *new* filings each run. The first run
# you do, bump this up (e.g. 400) to backfill more history; after that,
# daily runs only need to look back a week or two to catch anything new.
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "14"))


def load_existing():
    if DATA_PATH.exists():
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save(all_rows):
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    all_rows.sort(key=lambda r: r.get("date_sort", ""), reverse=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(all_rows, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(all_rows)} total transactions to {DATA_PATH}")


def to_sortable_date(mdy):
    try:
        m, d, y = mdy.split("/")
        return f"{y}-{int(m):02d}-{int(d):02d}"
    except Exception:
        return "0000-00-00"


def accept_agreement_and_search(page):
    page.goto(HOME_URL, wait_until="networkidle")
    page.check("#agree_statement")
    page.check("#filerTypeLabelSenator")
    page.click("button[type=submit].btn-primary")
    page.wait_for_selector("#filedReports", timeout=15000)


def collect_report_links(page, cutoff_date):
    """Walk the paginated #filedReports table, stop once rows are older
    than cutoff_date (table is sorted newest-first by default)."""
    reports = []
    seen_pages = 0
    while True:
        page.wait_for_selector("#filedReports tbody tr")
        rows = page.query_selector_all("#filedReports tbody tr")
        stop = False
        for row in rows:
            cells = row.query_selector_all("td")
            if len(cells) < 5:
                continue
            first_name = cells[0].inner_text().strip()
            last_name = cells[1].inner_text().strip()
            office = cells[2].inner_text().strip()
            link_el = cells[3].query_selector("a")
            report_title = link_el.inner_text().strip() if link_el else ""
            href = link_el.get_attribute("href") if link_el else None
            report_date = cells[4].inner_text().strip()

            if "Periodic Transaction Report" not in report_title:
                continue

            report_dt = None
            try:
                report_dt = datetime.strptime(report_date, "%m/%d/%Y")
            except ValueError:
                pass

            if report_dt and report_dt < cutoff_date:
                stop = True
                continue

            if href:
                reports.append({
                    "senator": f"{first_name} {last_name}".strip(),
                    "office": office,
                    "report_date": report_date,
                    "link": BASE_URL + href if href.startswith("/") else href,
                })

        seen_pages += 1
        next_btn = page.query_selector(".paginate_button.next:not(.disabled)")
        if stop or not next_btn or seen_pages > 200:  # 200-page hard stop, safety net
            break
        next_btn.click()
        page.wait_for_timeout(600)

    return reports


def parse_report_page(page, report_meta):
    page.goto(report_meta["link"], wait_until="networkidle")
    if "This report is not available" in page.content():
        return []

    # PDF-scanned reports render an <embed>/<iframe> instead of a table.
    if page.query_selector("embed, iframe.pdf-viewer"):
        return [{
            **report_meta,
            "skipped_pdf": True,
        }]

    rows_out = []
    tables = page.query_selector_all("table")
    for table in tables:
        headers = [th.inner_text().strip().lower() for th in table.query_selector_all("thead th")]
        if not any("ticker" in h for h in headers):
            continue  # not the transactions table

        col_index = {name: i for i, name in enumerate(headers)}

        def get(cells, key_options, default="--"):
            for k in key_options:
                if k in col_index and col_index[k] < len(cells):
                    return cells[col_index[k]].inner_text().strip()
            return default

        for i, tr in enumerate(table.query_selector_all("tbody tr")):
            cells = tr.query_selector_all("td")
            if not cells:
                continue
            ticker = get(cells, ["ticker"])
            if not ticker or ticker in ("--", ""):
                continue
            tx_date = get(cells, ["transaction date", "date"])
            rows_out.append({
                "senator": report_meta["senator"],
                "office": report_meta["office"],
                "filed_date": report_meta["report_date"],
                "date": tx_date,
                "date_sort": to_sortable_date(tx_date),
                "ticker": ticker.upper(),
                "company": get(cells, ["security name", "asset name", "company"], ""),
                "type": get(cells, ["type", "transaction type"], ""),
                "owner": get(cells, ["owner"], "--"),
                "amount": get(cells, ["amount"], "Unknown"),
                "comment": get(cells, ["comment"], ""),
                "link": report_meta["link"],
                "row_id": f"{report_meta['link']}#{i}",
            })
    return rows_out


def main():
    existing = load_existing()
    existing_by_id = {r.get("row_id"): r for r in existing if r.get("row_id")}
    existing_links_done = {r.get("link") for r in existing if r.get("link")}

    cutoff = datetime.now() - timedelta(days=LOOKBACK_DAYS)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        print("Accepting agreement and loading search form...")
        accept_agreement_and_search(page)

        print(f"Collecting report links back to {cutoff.date()}...")
        reports = collect_report_links(page, cutoff)
        print(f"Found {len(reports)} PTR filings in lookback window.")

        new_rows = []
        for i, rep in enumerate(reports):
            if rep["link"] in existing_links_done:
                continue  # already scraped this exact report in a prior run
            print(f"  [{i+1}/{len(reports)}] {rep['senator']} — {rep['report_date']}")
            try:
                rows = parse_report_page(page, rep)
                new_rows.extend(rows)
            except Exception as e:
                print(f"    ! failed to parse {rep['link']}: {e}", file=sys.stderr)

        browser.close()

    merged = list(existing_by_id.values())
    existing_ids = set(existing_by_id.keys())
    added = 0
    for row in new_rows:
        rid = row.get("row_id")
        if rid and rid not in existing_ids:
            merged.append(row)
            existing_ids.add(rid)
            added += 1

    print(f"Added {added} new transaction rows.")
    save(merged)


if __name__ == "__main__":
    main()
