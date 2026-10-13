"""What classes DO the parents of Indian districts actually carry?"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

HEADERS = {"User-Agent": "AquaGuardAI/1.0 (water-quality-app)",
           "Accept": "application/sparql-results+json"}

QUERY = """
SELECT ?cls ?clsLabel (COUNT(DISTINCT ?parent) AS ?n) WHERE {
  ?district wdt:P31 wd:Q1149652 ; wdt:P131 ?parent .
  ?parent wdt:P31 ?cls .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
GROUP BY ?cls ?clsLabel
ORDER BY DESC(?n)
LIMIT 40
"""

url = "https://query.wikidata.org/sparql?" + urllib.parse.urlencode(
    {"query": QUERY, "format": "json"})

for attempt in range(8):
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=170) as fh:
            rows = json.loads(fh.read().decode("utf-8"))["results"]["bindings"]
        for r in rows:
            qid = r["cls"]["value"].rsplit("/", 1)[-1]
            print("  %-10s %-46s %s" % (qid, r["clsLabel"]["value"],
                                        r["n"]["value"]), flush=True)
        break
    except urllib.error.HTTPError as exc:
        print("HTTP", exc.code, "- waiting", flush=True)
        time.sleep(70)
    except Exception as exc:  # noqa: BLE001
        print("retry after", exc, flush=True)
        time.sleep(70)
