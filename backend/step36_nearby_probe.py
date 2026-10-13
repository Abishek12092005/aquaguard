"""STEP 36 - the nearby-water-source fallback, measured directly.

The failure-modes suite could not verify the fallback at its probe point, so this
calls the service the way the API does, at several real points, and reports for
each: the walk outcome, the fallback decision and the fallback candidates. The
point is to separate "the provider had nothing here" from "the provider had
something and the fallback did not use it".
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
    ("Muzaffarpur, Bihar", 26.1445, 85.8918),
    ("Chennai", 13.08784, 80.27847),
    ("Varanasi", 25.31668, 83.01041),
]

OUT = {}

with app.app_context():
    for label, lat, lon in POINTS:
        record = {}

        # 1. The raw walk, at the default radius.
        started = time.time()
        query = ls._NEARBY_QUERY.format(radius=15000, lat=lat, lon=lon)
        body = ls._overpass(query)
        record["walk_seconds"] = round(time.time() - started, 2)
        record["walk_elements"] = len(body.get("elements", [])) if body else 0

        # 2. The full water context - what the API actually serves.
        started = time.time()
        context = ls.water_context({"lat": lat, "lon": lon, "name": label})
        record["context_seconds"] = round(time.time() - started, 2)
        water = context if "available" in context else context.get("water", {})
        record["available"] = water.get("available")
        record["primary"] = water.get("primary")
        record["exact"] = water.get("exact")
        nearest = water.get("nearest")
        record["nearest"] = (
            {k: nearest.get(k) for k in ("name", "type", "distance_m")}
            if nearest else None
        )
        nearby_list = water.get("nearby") or []
        record["nearby_count"] = len(nearby_list)
        record["first_nearby"] = (
            {k: nearby_list[0].get(k) for k in ("name", "type", "distance_m")}
            if nearby_list else None
        )
        record["message"] = water.get("message")
        OUT[label] = record

path = os.path.join(HERE, "s36_nearby_results.json")
with open(path, "w", encoding="utf-8") as handle:
    json.dump(OUT, handle, indent=2, default=str)

print(json.dumps(OUT, indent=2, default=str))
print(f"\nwrote {path}")
sys.stdout.flush()
sys.exit(0)