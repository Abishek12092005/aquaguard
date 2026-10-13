"""How much time the real water-source query needs, and how radius affects it.

STEP 36. Measured with a generous client timeout so the answer is the mirror's
real time rather than the app's cutoff. Reports, per radius, whether the answer
fits inside the service's current budget - which is the number that decides
whether the Location page can show a water source at all.
"""

import time

import requests

from app.services import location_service

LAT, LON = 13.08784, 80.27847
HEADERS = location_service._HEADERS
URL = "https://overpass-api.de/api/interpreter"

for radius in (1500, 3000, 5000):
    query = location_service._NEARBY_QUERY.format(radius=radius, lat=LAT, lon=LON)
    started = time.time()
    try:
        response = requests.post(URL, data=query, headers=HEADERS, timeout=90)
        elapsed = time.time() - started
        elements = len(response.json().get("elements", [])) if response.status_code == 200 else "-"
        print(
            f"radius={radius:>5}m  status={response.status_code}  {elapsed:6.2f}s  "
            f"elements={elements}  fits_in_2.5s={'YES' if elapsed < 2.5 else 'NO'}"
        )
    except Exception as exc:  # noqa: BLE001 - the failure IS the datum
        print(f"radius={radius:>5}m  FAILED after {time.time() - started:6.2f}s: {exc}")