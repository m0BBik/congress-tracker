"""
Refreshes data/senators_party.json from the official, public-domain
'congress-legislators' project (unitedstates/congress-legislators on GitHub).
This gives an accurate current Senate roster with party affiliation, kept
in sync automatically instead of being hand-maintained.
"""

import json
from pathlib import Path

import requests
import yaml

SOURCE_URL = "https://raw.githubusercontent.com/unitedstates/congress-legislators/main/legislators-current.yaml"
OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "senators_party.json"

PARTY_CODE = {
    "Democrat": "D",
    "Democratic": "D",
    "Republican": "R",
    "Independent": "I",
}


def main():
    resp = requests.get(SOURCE_URL, timeout=30)
    resp.raise_for_status()
    legislators = yaml.safe_load(resp.text)

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
        senators.append({
            "full_name": full,
            "first": name.get("first", ""),
            "last": name.get("last", ""),
            "state": last_term.get("state", ""),
            "party": PARTY_CODE.get(party, party[:1] if party else "?"),
        })

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(senators, f, ensure_ascii=False, indent=2)

    print(f"Wrote {len(senators)} current senators to {OUT_PATH}")


if __name__ == "__main__":
    main()
