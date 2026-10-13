"""How long the real water-source query takes against the live Overpass.

STEP 36. The service walks the mirrors with a 2.5 s budget and a 2.5 s read
timeout, so whether water sources resolve at all depends entirely on whether the
mirror can answer inside that. This measures the ACTUAL query the service
builds - imported from the service itself, not a hand-written imitation - so a
slow mirror can be told apart from a broken one.
"""

import time

import requests

from app.services import location_service

LAT, LON = 13.08784, 80.27847
RADIUS = 3000

query = location_service._NEARBY_QUERY.format(radius=RADIUS, lat=LAT, lon=LON)
print(f"query length: {len(query)} chars")
print(f"service budget: {location_service._OVERPASS_BUDGET_S}s, "
      f"read timeout: {location_service._OVERPASS_READ_TIMEOUT}s")
print(f"headers the service sends: {location_service._HEADERS}\n")

for url in location_service._OVERPASS_MIRRORS:
    started = time.time()
    try:
        response = requests.post(
            url,
            data=query,
            headers=location_service._HEADERS,
            timeout=location_service._OVERPASS_READ_TIMEOUT,
        )
        elapsed = time.time() - started
        elements = (
            len(response.json().get("elements", [])) if response.status_code == 200 else "-"
        )
        verdict = "ANSWERS IN TIME" if response.status_code == 200 and elapsed < 2.5 else "too slow"
        print(f"{url}\n    status={response.status_code} {elapsed:.2f}s elements={elements}  {verdict}")
    except Exception as exc:  # noqa: BLE001 - the failure IS the datum
        print(f"{url}\n    FAILED after {time.time() - started:.2f}s: {exc}")