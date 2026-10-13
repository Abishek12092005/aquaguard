"""STEP 36 - water lookup against a FRESH process, bypassing breaker state.

The dev server latches its Overpass outage breaker for 120 s after a total
failure, so a request issued right after one is skipped without trying. That is
correct behaviour, but it makes repeated manual probing read as "the fix did not
work". This calls the service directly in a fresh process, so the breaker starts
closed and the walk really runs.
"""

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from app import create_app  # noqa: E402
from app.services import location_service  # noqa: E402

app = create_app("testing")

print(f"budget={location_service._OVERPASS_BUDGET_S}s "
      f"read_timeout={location_service._OVERPASS_READ_TIMEOUT}s "
      f"breaker_state={location_service._overpass_state}")

POINTS = [
    ("Chennai", 13.08784, 80.27847),
    ("Varanasi", 25.31668, 83.01041),
]

with app.app_context():
    for label, lat, lon in POINTS:
        started = time.time()
        context = location_service.water_context({"lat": lat, "lon": lon, "name": label})
        elapsed = time.time() - started
        water = context if "available" in context else context.get("water", {})
        nearby = water.get("nearby") or []
        nearest = water.get("nearest")
        print(f"\n{label} ({lat}, {lon}) in {elapsed:.2f}s")
        print(f"  available = {water.get('available')}")
        print(f"  primary   = {water.get('primary')!r}")
        print(f"  nearby    = {len(nearby)}")
        print(f"  nearest   = "
              f"{(nearest.get('name'), nearest.get('type'), nearest.get('distance_m')) if nearest else None}")
        for entry in nearby[:3]:
            print(f"     - {entry.get('name')!r} {entry.get('type')!r} {entry.get('distance_m')}m")
        if not nearby:
            print(f"  message   = {water.get('message')}")

        # The state after a call is what the breaker uses next time.
        print(f"  breaker   = {location_service._overpass_state}")