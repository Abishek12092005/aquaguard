"""Quick Overpass reachability test - one tiny query, 30s cap, every mirror."""

import time
import requests

MIRRORS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.maps.mail.ru/osm/tools/overpass/api/interpreter",
]
QUERY = '[out:json][timeout:25];node(9.8,78.4,9.9,78.5)["place"="town"];out body 3;'
HEADERS = {"User-Agent": "AquaGuardAI/1.0 (water-quality-app)"}

for url in MIRRORS:
    t0 = time.monotonic()
    try:
        r = requests.post(url, data=QUERY, headers=HEADERS, timeout=30)
        dt = time.monotonic() - t0
        n = 0
        if r.status_code == 200:
            body = r.json()
            n = len(body.get("elements") or [])
        print(f"{url.split('/')[2]:40s} status={r.status_code} elements={n} {dt:.1f}s", flush=True)
    except Exception as exc:
        dt = time.monotonic() - t0
        print(f"{url.split('/')[2]:40s} FAILED {type(exc).__name__}: {str(exc)[:80]} {dt:.1f}s", flush=True)
