"""
Refreshes data/senators_party.json from the official, public-domain
'congress-legislators' project (unitedstates/congress-legislators on GitHub).

This gives:
  - an accurate current Senate roster with party affiliation
  - each senator's current Senate committee assignments (e.g. "Energy and
    Natural Resources", "Banking, Housing, and Urban Affairs") — useful for
    spotting potential conflicts of interest, like a senator on the Energy
    committee trading energy-sector stocks.

All from the same public-domain source, kept in sync automatically instead
of being hand-maintained.
"""

import json
from pathlib import Path

import requests
import yaml

LEGISLATORS_URL = "https://raw.githubusercontent.com/unitedstates/congress-legislators/main/legislators-current.yaml"
COMMITTEES_URL = "https://raw.githubusercontent.com/unitedstates/congress-legislators/main/committees-current.yaml"
MEMBERSHIP_URL = "https://raw.githubusercontent.com/unitedstates/congress-legislators/main/committee-membership-current.yaml"

OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "senators_party.json"

PARTY_CODE = {
    "Democrat": "D",
    "Democratic": "D",
    "Republican": "R",
    "Independent": "I",
}


def fetch_yaml(url):
    resp = requests.get(url, timeout=30)
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


def main():
    legislators = fetch_yaml(LEGISLATORS_URL)
    committees = fetch_yaml(COMMITTEES_URL)
    membership = fetch_yaml(MEMBERSHIP_URL)

    committee_map = build_committee_map(committees, membership)

    senators = []
    for leg in legislators:
        terms = leg.get("terms", [])
        if not terms:
            continue
        last_term = terms[-1]
        if last_term.get("type") != "sen":
            continue
        name = leg.get("name", {})
        full = name.get("official_full") or f"{name.get('first','')} {name.get('last','')}"
        party = last_term.get("party", "")
        bioguide = leg.get("id", {}).get("bioguide", "")
        senators.append({
            "full_name": full,
            "first": name.get("first", ""),
            "last": name.get("last", ""),
            "state": last_term.get("state", ""),
            "party": PARTY_CODE.get(party, party[:1] if party else "?"),
            "committees": committee_map.get(bioguide, []),
        })

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(senators, f, ensure_ascii=False, indent=2)

    with_committees = sum(1 for s in senators if s["committees"])
    print(f"Wrote {len(senators)} current senators to {OUT_PATH} ({with_committees} with committee data)")


if __name__ == "__main__":
    main()
