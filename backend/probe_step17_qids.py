"""Resolve every Indian state / UT to its Wikidata QID, in one query."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

H = {"User-Agent": "AquaGuardAI/1.0 (water-quality-app)",
     "Accept": "application/sparql-results+json"}

STATES = [
    "Andaman and Nicobar Islands", "Andhra Pradesh", "Arunachal Pradesh",
    "Assam", "Bihar", "Chandigarh", "Chhattisgarh",
    "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Goa", "Gujarat",
    "Haryana", "Himachal Pradesh", "Jammu and Kashmir", "Jharkhand",
    "Karnataka", "Kerala", "Ladakh", "Lakshadweep", "Madhya Pradesh",
    "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha",
    "Puducherry", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana",
    "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
]

# Every state/UT of India, labelled, in ONE query.
#
# The class path is kept SHALLOW on purpose: query.wikidata.org is currently
# rate-limiting anonymous clients to about one request a minute and times out
# (HTTP 500) on the unbounded P31/P279* walk, which is exactly what a full
# subclass closure of "state of India" produces. Q10742 is "state of India" and
# Q13539817 "union territory of India"; a district's own item sits directly
# under one of them or under the handful of intermediate classes below, so the
# depth-3 walk is both sufficient and fast.
QUERY = """
SELECT DISTINCT ?state ?stateLabel WHERE {{
  VALUES ?class {{ wd:Q10742 wd:Q13539817 wd:Q15659839 wd:Q15659847
                   wd:Q17378135 wd:Q2020158 }}
  ?state wdt:P31 ?class ; wdt:P17 wd:Q668 .
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}
"""

url = "https://query.wikidata.org/sparql?" + urllib.parse.urlencode(
    {"query": QUERY, "format": "json"})

for attempt in range(8):
    try:
        req = urllib.request.Request(url, headers=H)
        with urllib.request.urlopen(req, timeout=120) as fh:
            rows = json.loads(fh.read().decode("utf-8"))["results"]["bindings"]
        got = {}
        for r in rows:
            got[r["stateLabel"]["value"]] = r["state"]["value"].rsplit("/", 1)[-1]
        for s in STATES:
            print('    "%s": "%s",   # %s' % (s, got.get(s, "?"),
                                               "OK" if s in got else "MISSING"))
        print("resolved %d/%d" % (len(got), len(STATES)))
        break
    except Exception as exc:  # noqa: BLE001
        print("retry after", exc, flush=True)
        time.sleep(70)
