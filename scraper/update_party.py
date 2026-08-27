"""
Refreshes data/senators_party.json from the official, public-domain
'congress-legislators' project (unitedstates/congress-legislators on GitHub).

This gives:
  - an accurate current Senate roster with party affiliation
  - former senators too (going back ~30 years), so someone like Pat Roberts
    or Patrick Toomey — no longer serving, but still in our transaction
    history — still gets a party instead of showing "?"
  - each senator's current Senate committee assignments (e.g. "Energy and
    Natural Resources", "Banking, Housing, and Urban Affairs") — used both
    to let people filter by committee and to flag potential conflicts of
    interest (a senator trading in a sector their committee oversees)

All from the same public-domain source, kept in sync automatically instead
of being hand-maintained. Former senators obviously won't have *current*
committee assignments, since they're not serving — that's expected.
"""

import json
from pathlib import Path

import requests
import yaml

LEGISLATORS_CURRENT_URL = "https://raw.githubusercontent.com/unitedstates/congress-legislators/main/legislators-current.yaml"
LEGISLATORS_HISTORICAL_URL = "https://raw.githubusercontent.com/unitedstates/congress-legislators/main/legislators-historical.yaml"
COMMITTEES_URL = "https://raw.githubusercontent.com/unitedstates/congress-legislators/main/committees-current.yaml"
MEMBERSHIP_URL = "https://raw.githubusercontent.com/unitedstates/congress-legislators/main/committee-membership-current.yaml"
TRANSACTIONS_PATH = Path(__file__).resolve().parent.parent / "data" / "senate_transactions.json"

OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "senators_party.json"

PARTY_CODE = {
    "Democrat": "D",
    "Democratic": "D",
    "Republican": "R",
    "Independent": "I",
}


def fetch_yaml(url):
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    return yaml.safe_load(resp.text)


def build_committee_map(committees, membership):
    """bioguide -> sorted list of Senate committee short names (top-level only)."""
    tid_to_name = {}
    for c in committees:
        if c.get("type") != "senate":
            continue
        tid = c.get("thomas_id")
        if not tid:
            continue
        name = c["name"].replace("Senate Committee on ", "").replace("Senate ", "")
        tid_to_name[tid] = name

    bio_committees = {}
    for tid, members in membership.items():
        if tid not in tid_to_name:
            continue  # skip subcommittees and non-Senate committees
        cname = tid_to_name[tid]
        for m in members:
            bg = m.get("bioguide")
            if not bg:
                continue
            bio_committees.setdefault(bg, set()).add(cname)

    return {k: sorted(v) for k, v in bio_committees.items()}


def last_names_in_our_data():
    """Only pull in historical legislators whose last name actually shows up
    in our scraped transactions — the historical file has ~10,000 people
    going back to 1789 and we only need the handful relevant to us."""
    if not TRANSACTIONS_PATH.exists():
        return set()
    with open(TRANSACTIONS_PATH, "r", encoding="utf-8") as f:
        txns = json.load(f)
    names = set()
    for t in txns:
        senator = (t.get("senator") or "").replace(",", " ")
        parts = senator.split()
        if parts:
            names.add(parts[-1].lower())
    return names


def extract_senators(legislators, committee_map, only_last_names=None):
    senators = []
    for leg in legislators:
        terms = leg.get("terms", [])
        sen_terms = [t for t in terms if t.get("type") == "sen"]
        if not sen_terms:
            continue
        name = leg.get("name", {})
        last = name.get("last", "")
        if only_last_names is not None and last.lower() not in only_last_names:
            continue
        last_term = sen_terms[-1]
        full = name.get("official_full") or f"{name.get('first','')} {last}"
        party = last_term.get("party", "")
        bioguide = leg.get("id", {}).get("bioguide", "")
        senators.append({
            "full_name": full,
            "first": name.get("first", ""),
            "last": last,
            "state": last_term.get("state", ""),
            "party": PARTY_CODE.get(party, party[:1] if party else "?"),
            "committees": committee_map.get(bioguide, []),
            "end_year": last_term.get("end", "")[:4] if last_term.get("end") else None,
        })
    return senators


def main():
    legislators_current = fetch_yaml(LEGISLATORS_CURRENT_URL)
    committees = fetch_yaml(COMMITTEES_URL)
    membership = fetch_yaml(MEMBERSHIP_URL)
    committee_map = build_committee_map(committees, membership)

    current_senators = extract_senators(legislators_current, committee_map)

    relevant_last_names = last_names_in_our_data()
    already_covered = {s["last"].lower() for s in current_senators}
    still_needed = relevant_last_names - already_covered

    historical_senators = []
    if still_needed:
        print(f"Looking up {len(still_needed)} last name(s) in historical roster: {sorted(still_needed)}")
        legislators_historical = fetch_yaml(LEGISLATORS_HISTORICAL_URL)
        historical_senators = extract_senators(legislators_historical, {}, only_last_names=still_needed)

    all_senators = current_senators + historical_senators

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(all_senators, f, ensure_ascii=False, indent=2)

    with_committees = sum(1 for s in all_senators if s["committees"])
    print(f"Wrote {len(all_senators)} senators ({len(current_senators)} current + "
          f"{len(historical_senators)} historical) to {OUT_PATH} ({with_committees} with committee data)")


if __name__ == "__main__":
    main()
