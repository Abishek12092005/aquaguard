"""STEP 36b - why do Chennai and Varanasi walk to zero elements?

The probe showed: Muzaffarpur fine (60 elements), Chennai 0 elements after a
12 s walk, Varanasi 0 elements at 0.0 s. Two different suspects:
  * Varanasi 0.0 s -> the outage breaker was OPEN (it trips after any walk
    where every mirror fails), so the query never left the process.
  * Chennai 0 elements -> either a genuinely empty area or the rate-limit
    lie described in the empty-cache comment.

This asks each mirror the SAME query for each point, one at a time, with a
long budget, and reports what each said. No cache, no breaker, no racing.
"""

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from app import create_app  # noqa: E402
from app.services import location_service as ls  # noqa: E402

app = create_app("testing")

POINTS = [
    ("Chennai", 13.08784, 80.27847),
    ("Varanasi", 25.31668, 83.01041),
]

OUT = {}

with app.app_context():
    ls._overpass_budget(45.0)  # give every mirror room to answer
    for label, lat, lon in POINTS:
        query = ls._NEARBY_QUERY.format(radius=15000, lat=lat, lon=lon)
        per_mirror = {}
        for url in ls._OVERPASS_MIRRORS:
            started = time.time()
            body = ls._overpass_one(url, query, time.monotonic() + 45.0)
            took = round(time.time() - started, 2)
            if body is None:
                per_mirror[url] = {"seconds": took, "outcome": "None"}
            else:
                per_mirror[url] = {
                    "seconds": took,
                    "elements": len(body.get("elements", [])),
                }
        OUT[label] = per_mirror

path = os.path.join(HERE, "s36_mirror_report.json")
with open(path, "w", encoding="utf-8") as handle:
    json.dump(OUT, handle, indent=2, default=str)

print(json.dumps(OUT, indent=2, default=str))
print(f"\nwrote {path}")
sys.stdout.flush()
sys.exit(0)
