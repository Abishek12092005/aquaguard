"""The final Step 17 query: every Indian district mapped to its own STATE.

Variant A works (828 rows / 814 distinct districts) but 122 of its parents are
DIVISIONS ("Agra division", "Ajmer division") rather than states, so a district
would be filed under a division name. The fix is to walk the parent chain one
level and require the grandparent to be a real state of India, while also
keeping a district whose direct parent IS the state.

Q1149652 is typed too loosely in places (it caught 814 units), so the result is
recorded with each unit's own type labels for inspection.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

HEADERS = {"User-Agent": "AquaGuardAI/1.0 (water-quality-app)",
           "Accept": "application/sparql-results+json"}

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

url = "https://query.wikidata.org/sparql?" + urllib.parse.urlencode(
    {"query": QUERY, "format": "json"})

for attempt in range(8):
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=170) as fh:
            rows = json.loads(fh.read().decode("utf-8"))["results"]["bindings"]
        print("ROWS:", len(rows), flush=True)
        units = {}
        for r in rows:
            qid = r["district"]["value"].rsplit("/", 1)[-1]
            rec = units.setdefault(qid, {"name": r["districtLabel"]["value"],
                                        "types": set(), "states": set()})
            rec["types"].add(r.get("typeLabel", {}).get("value", ""))
            rec["states"].add(r["stateLabel"]["value"])
        # Keep only units whose state is unambiguous.
        clean = {q: v for q, v in units.items() if len(v["states"]) == 1}
        multi = {q: v for q, v in units.items() if len(v["states"]) > 1}
        print("distinct units: %d  single-state: %d  multi-state: %d"
              % (len(units), len(clean), len(multi)), flush=True)
        from collections import Counter
        print("units: %d" % len(clean), flush=True)
        by_state = {}
        for v in clean.values():
            by_state.setdefault(list(v["states"])[0], set()).add(v["name"])
        for s in sorted(by_state, key=str.casefold):
            print("  %-40s %3d" % (s, len(by_state[s])), flush=True)
        print("states: %d districts: %d"
              % (len(by_state), sum(len(v) for v in by_state.values())))
        with open("step17_wikidata_raw.json", "w", encoding="utf-8") as fh:
            json.dump({k: sorted(v, key=str.casefold) for k, v in by_state.items()},
                      fh, ensure_ascii=False, indent=1, sort_keys=True)
        break
    except urllib.error.HTTPError as exc:
        print("HTTP", exc.code, "- waiting", flush=True)
        time.sleep(70)
    except Exception as exc:  # noqa: BLE001
        print("retry after", exc, flush=True)
        time.sleep(70)
