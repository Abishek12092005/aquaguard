"""Can a cheaper Overpass query return real water sources inside the app budget?

STEP 36. The service's query fans out over ~40 tag alternations across ways and
nodes, which is what pushes it past 7 s. This measures progressively simpler
forms against the live mirror so the fix is based on measured timings rather
than on a guess about which part is expensive.
"""

import time

import requests

from app.services import location_service

LAT, LON = 13.08784, 80.27847  # Chennai
HEADERS = location_service._HEADERS
URL = "https://overpass-api.de/api/interpreter"

CANDIDATES = [
    ("current service query, 1500 m", location_service._NEARBY_QUERY.format(
        radius=1500, lat=LAT, lon=LON)),
    ("water tags only, 2000 m", (
        "[out:json][timeout:25];("
        'way["water"](around:2000,%f,%f);'
        'node["natural"="water"](around:2000,%f,%f);'
        'way["natural"="water"](around:2000,%f,%f);'
        'node["natural"="spring"](around:2000,%f,%f);'
        'way["landuse"="reservoir"](around:2000,%f,%f);'
        'node["man_made"~"water_well|borehole"](around:2000,%f,%f);'
        ");out center tags 60;" % (LAT, LON, LAT, LON, LAT, LON, LAT, LON, LAT, LON, LAT, LON)
    )),
    ("water tags only, 3000 m", (
        "[out:json][timeout:25];("
        'way["water"](around:3000,%f,%f);'
        'node["natural"="water"](around:3000,%f,%f);'
        'way["natural"="water"](around:3000,%f,%f);'
        'node["natural"="spring"](around:3000,%f,%f);'
        'way["landuse"="reservoir"](around:3000,%f,%f);'
        'node["man_made"~"water_well|borehole"](around:3000,%f,%f);'
        ");out center tags 60;" % (LAT, LON, LAT, LON, LAT, LON, LAT, LON, LAT, LON, LAT, LON)
    )),
    ("named water bodies only, 3000 m", (
        "[out:json][timeout:25];("
        'way["waterway"~"^(river|stream|canal)$"](around:3000,%f,%f);'
        'node["natural"="spring"](around:3000,%f,%f);'
        'way["landuse"="reservoir"](around:3000,%f,%f);'
        'node["man_made"="water_well"](around:3000,%f,%f);'
        ");out center tags 60;" % (LAT, LON, LAT, LON, LAT, LON, LAT, LON)
    )),
]

for label, query in CANDIDATES:
    started = time.time()
    try:
        response = requests.post(URL, data=query, headers=HEADERS, timeout=90)
        elapsed = time.time() - started
        elements = response.json().get("elements", []) if response.status_code == 200 else []
        print(
            f"{label:38s} status={response.status_code} {elapsed:6.2f}s "
            f"elements={len(elements)}  fits_in_2.5s={'YES' if elapsed < 2.5 else 'NO'}"
        )
        for element in elements[:3]:
            tags = element.get("tags", {})
            print(f"      e.g. {tags.get('name')!r} {tags.get('natural') or tags.get('waterway') or tags.get('water')}")
    except Exception as exc:  # noqa: BLE001 - the failure IS the datum
        print(f"{label:38s} FAILED after {time.time() - started:6.2f}s: {exc}")