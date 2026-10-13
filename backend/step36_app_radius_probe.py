"""Which radius actually returns water sources, at the radius the app uses.

STEP 36. `nearby_sources` defaults to radius_m=15000. This measures the real
query at that radius and at tighter ones, so a radius change is made on measured
ground rather than on the assumption that a smaller one still finds real water.
"""

import time

import requests

from app.services import location_service

LAT, LON = 13.08784, 80.27847  # Chennai
HEADERS = location_service._HEADERS
URL = "https://overpass-api.de/api/interpreter"

# 15000 is the default `nearby_sources` really uses; the others bracket it.
for radius in (1500, 3000, 5000, 10000, 15000):
    query = location_service._NEARBY_QUERY.format(radius=radius, lat=LAT, lon=LON)
    started = time.time()
    try:
        response = requests.post(URL, data=query, headers=HEADERS, timeout=90)
        elapsed = time.time() - started
        elements = response.json().get("elements", []) if response.status_code == 200 else []
        print(
            f"radius={radius:>6}m  status={response.status_code}  {elapsed:6.2f}s  "
            f"elements={len(elements)}"
        )
    except Exception as exc:  # noqa: BLE001 - the failure IS the datum
        print(f"radius={radius:>6}m  FAILED after {time.time() - started:6.2f}s: {exc}")