"""One query for EVERY Indian district and its state, from Wikidata."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

H = {"User-Agent": "AquaGuardAI/1.0 (water-quality-app)",
     "Accept": "application/sparql-results+json"}

# Q1149652 = "district of India". One query covers the whole country, which
# matters: the endpoint rate-limits anonymous clients to ~1 request a minute
# during its current outage, so 36 per-state queries would take 40 minutes and
# a single one takes one.
QUERY = """
SELECT DISTINCT ?district ?districtLabel ?state ?stateLabel WHERE {{
  ?district wdt:P31 wd:Q1149652 .
  ?district wdt:P131 ?state .
  ?state wdt:P17 wd:Q668 .
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}
"""

url = "https://query.wikidata.org/sparql?" + urllib.parse.urlencode(
    {"query": QUERY, "format": "json"})

for attempt in range(10):
    try:
        req = urllib.request.Request(url, headers=H)
        with urllib.request.urlopen(req, timeout=180) as fh:
            rows = json.loads(fh.read().decode("utf-8"))["results"]["bindings"]
        out = {}
        for r in rows:
            state = r["stateLabel"]["value"]
            name = r["districtLabel"]["value"].strip()
            if name:
                out.setdefault(state, set()).add(name)
        total = 0
        for state in sorted(out, key=str.casefold):
            names = sorted(out[state], key=str.casefold)
            total += len(names)
            print('    "%s": %d,' % (state, len(names)), flush=True)
        print("states: %d  districts: %d" % (len(out), total))
        with open("step17_wikidata_raw.json", "w", encoding="utf-8") as fh:
            json.dump({k: sorted(v, key=str.casefold) for k, v in out.items()},
                      fh, ensure_ascii=False, indent=1, sort_keys=True)
        break
    except urllib.error.HTTPError as exc:
        print("HTTP", exc.code, "- waiting", flush=True)
        time.sleep(70)
    except Exception as exc:  # noqa: BLE001
        print("retry after", exc, flush=True)
        time.sleep(70)
