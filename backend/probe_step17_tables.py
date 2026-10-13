"""Inspect the table structure of a 'List of districts of X' article."""
import json
import sys
import time
import urllib.parse
import urllib.request

H = {"User-Agent": "AquaGuardAI/1.0 (water-quality-app)"}
API = "https://en.wikipedia.org/w/api.php"

for state in ("Assam", "Ladakh"):
    url = API + "?" + urllib.parse.urlencode({
        "action": "parse", "page": "List of districts of " + state,
        "prop": "wikitext", "format": "json", "formatversion": 2, "redirects": 1,
    })
    req = urllib.request.Request(url, headers=H)
    with urllib.request.urlopen(req, timeout=60) as fh:
        text = json.loads(fh.read().decode("utf-8"))["parse"]["wikitext"]
    print("=" * 70, state, len(text), flush=True)
    for i, line in enumerate(text.splitlines()[:70]):
        print("%3d| %s" % (i, line[:150]), flush=True)
    time.sleep(2)
