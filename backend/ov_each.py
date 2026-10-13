"""One tiny query against EACH mirror, once, to find any that answers."""

import time
import requests

QUERY = "[out:json][timeout:20];node(9.84,78.4,9.9,78.5);out body 1;"
HEADERS = {"User-Agent": "AquaGuardAI/1.0 (water-quality-app)"}

MIRRORS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.maps.mail.ru/osm/tools/overpass/api/interpreter",
]

for url in MIRRORS:
    t0 = time.monotonic()
    try:
        r = requests.post(url, data=QUERY, headers=HEADERS, timeout=40)
        n = len(r.json().get("elements") or []) if r.status_code == 200 else 0
        print(f"{url.split('/')[2]:32s} {r.status_code} elements={n} {time.monotonic()-t0:.1f}s", flush=True)
    except Exception as exc:
        print(f"{url.split('/')[2]:32s} FAIL {type(exc).__name__} {time.monotonic()-t0:.1f}s", flush=True)
