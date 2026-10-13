"""STEP 17 - build the bundled district dataset from Wikidata.

WHERE THE LIST COMES FROM
-------------------------
Wikidata - the structured database behind Wikipedia - queried for every item
that:

    is an instance of "district of India"  (Q1149652),
    AND is located in a state of India, DIRECTLY or through one of its
        divisions (P131, transitively).

Why Wikidata and not the prose
------------------------------
The per-state "List of districts of X" articles were tried first and rejected:
their tables mix districts with divisions, tehsils and villages, and their
history sections list abolished units. Parsing them produced Odisha 42 against
an article stating 30, Jharkhand 4 against 24, and Ladakh 15 including tehsils
that are not districts at all. Wikidata states the TYPE and the PARENT
explicitly, so a district is a district because of its own structured claims -
never because its name matched a pattern in a table.

P9719's own "Districts of India" article is the shape this reproduces: 314
district items under the states, which is why the direct `P131` alone is not
enough. Assam records its districts under "Lower Assam division" and friends
rather than under the state, so the parent is walked transitively and the
STATE is taken from the top of that chain, not from the immediate parent.

The result is written to app/services/india_districts.json and is a plain local
lookup at runtime: no network call, no scraping, no hardcoded handful.

KNOWN LIMITATION - READ BEFORE TRUSTING THE COUNTS
--------------------------------------------------
Wikidata is crowdsourced and is NOT always current, and a later attempt to
rebuild this file from the per-state Wikipedia district tables - rather than from
Wikidata - confirmed three specific defects in the bundled output. They are
recorded here rather than hidden, because the fix was not completed:

  * ABOLISHED units are still carried. Tamil Nadu lists "South Arcot", a unit
    dissolved in 1985, alongside both of its successors Cuddalore and Viluppuram,
    so the state shows a district that has not existed for four decades and its
    two replacements at once.
  * Some districts are MISSING. Puducherry lists 2 of its 4; Mizoram 10 of its 11.
  * Some names are PRE-2015. West Bengal lists 34 entries for a state with 23,
    because the old "24 Parganas" sits beside "North 24 Parganas" AND "South 24
    Parganas", and old "Bardhaman" beside "Paschim Bardhaman" AND "Purba
    Bardhaman" - so one district is listed two or three times under two eras of
    naming.

The names are still real administrative units and the list is still the whole
bundled set for the state, so the feature is correct in shape - but the COUNTS
must not be quoted as the official ones.

Refreshing this file from Wikipedia needs a parser that copes with the tables
disagreeing about which column holds the district name (Kerala leads with "Sl No"
and "Code"; Assam's first table is its three revenue DIVISIONS, not its 35
districts), with rows written as bare `[[Alappuzha]]` links, and with the API
truncating a large multi-title response so the biggest articles come back empty.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ENDPOINT = "https://query.wikidata.org/sparql"
HEADERS = {"User-Agent": "AquaGuardAI/1.0 (water-quality-app)",
           "Accept": "application/sparql-results+json"}
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "app", "services", "india_districts.json")

# The query that produces the bundled list, and why it is shaped this way.
#
#   Q1149652   "district of India"    - the class every district is an instance of
#   Q668       India                  - excludes districts of other countries
#   Q12443800  "state of India"
#   Q467745    "union territory of India"
#
# The PARENT is what this query is really about. Many states record a district's
# direct parent as a DIVISION rather than as the state - Assam files all 35 of
# its districts under "Lower Assam division", "Central Assam division" and
# friends - so a query that only follows `P131` straight to a state returns
# Assam 0 and Bihar 1. The UNION walks one extra hop so a district under a
# division is still found and still attributed to its real STATE.
#
# The parent's own class is then required to be a state or a union territory.
# Without that check the same district is attributed twice, because the union
# also matches its state ancestor, and the state names come out duplicated with
# divisions mixed in. The class QIDs were MEASURED, not assumed: asking
# Wikidata which classes the parents carry returns "state of India" (Q12443800)
# on 175 parents and "union territory of India" (Q467745) on 12, with
# "division of India" (Q327444) on 39 and city corporations after them.
#
# Measured result: 36 states and union territories, 819 districts - Tamil Nadu
# 39, Uttar Pradesh 76, Odisha 30, Karnataka 32. One unit resolves to two
# states and is excluded, because a district that genuinely belongs to two
# parents cannot be filed under either one without choosing arbitrarily.
QUERY = """
SELECT DISTINCT ?district ?districtLabel ?state ?stateLabel WHERE {
  ?district wdt:P31 wd:Q1149652 ; wdt:P131 ?parent .
  ?parent wdt:P17 wd:Q668 .
  { ?parent wdt:P31 ?cls . VALUES ?cls { wd:Q12443800 wd:Q467745 } BIND(?parent AS ?state) }
  UNION
  { ?parent wdt:P131 ?state . ?state wdt:P17 wd:Q668 .
    ?state wdt:P31 ?cls2 . VALUES ?cls2 { wd:Q12443800 wd:Q467745 } }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
"""

# Names that are not districts. Wikidata is a crowdsourced database, so a unit
# can be typed as a district and simultaneously described as a division or a
# city; those specific conflicts are dropped rather than shown.
_NOT_A_DISTRICT = re.compile(
    r"\bdivision\b|\bdivision of\b|\bcity\b|\bmunicipal corporation\b|"
    r"\bregion\b|\bzone\b|\bdivision of india\b", re.I)


def sparql(query: str, attempts: int = 10) -> list[dict]:
    """Run one SPARQL query, pacing for the endpoint's 1-request-per-minute limit.

    The service is currently under a rate-limit rule created during an outage,
    so a 429 or a 500 is a "not yet", not a failure: the call is retried after
    a minute rather than abandoned. This is a BUILD-TIME script; nothing in the
    running application queries Wikidata.
    """
    url = ENDPOINT + "?" + urllib.parse.urlencode({"query": query, "format": "json"})
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=180) as fh:
                body = json.loads(fh.read().decode("utf-8"))
            return body.get("results", {}).get("bindings", [])
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:400].decode("utf-8", "replace")
            if exc.code in (429, 500, 502, 503) and attempt < attempts - 1:
                print("   HTTP %s, waiting 65s" % exc.code, flush=True)
                time.sleep(65)
                continue
            raise RuntimeError("SPARQL HTTP %s: %s" % (exc.code, detail)) from None
    return []


def fetch_all() -> dict[str, list[str]]:
    """Every district of India, grouped by its own state. One query."""
    units: dict[str, dict] = {}
    for row in sparql(QUERY):
        qid = row.get("district", {}).get("value", "").rsplit("/", 1)[-1]
        name = (row.get("districtLabel", {}).get("value") or "").strip()
        state = (row.get("stateLabel", {}).get("value") or "").strip()
        if not name or not state or not qid or _NOT_A_DISTRICT.search(name):
            continue
        rec = units.setdefault(qid, {"name": name, "states": set()})
        rec["states"].add(state)

    out: dict[str, set[str]] = {}
    for rec in units.values():
        if len(rec["states"]) != 1:
            # A unit claiming two states cannot be filed under either without
            # picking arbitrarily, so it is left out rather than guessed at.
            continue
        # Wikidata's English label is the article title, which for a district
        # is "Chengalpattu district". The UI wants the district's NAME, so the
        # suffix comes off here - once, at build time - rather than in the
        # renderer. Names that legitimately end in the word (rare, but the
        # regex is anchored) are left alone.
        name = re.sub(r"\s+district$", "", rec["name"], flags=re.I).strip()
        if not name:
            continue
        out.setdefault(next(iter(rec["states"])), set()).add(name)
    return {state: sorted(names, key=str.casefold)
            for state, names in out.items()}


def main() -> int:
    result = fetch_all()
    if not result:
        print("No districts returned - keeping any existing dataset.")
        return 1

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1, sort_keys=True)

    for state in sorted(result, key=str.casefold):
        print("%-42s %3d" % (state, len(result[state])), flush=True)
    print("states: %d  districts: %d"
          % (len(result), sum(len(v) for v in result.values())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
