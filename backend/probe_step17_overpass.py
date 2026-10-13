"""Measure a structural (non-water) Overpass query for the district list."""
import sys
import time

sys.path.insert(0, r"c:\Users\abishek\OneDrive\Desktop\aquagaurd\backend")

import requests

HEADERS = {"User-Agent": "AquaGuardAI/1.0 (water-quality-app)"}
MIRRORS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)

q = (
    "[out:json][timeout:120];"
    'rel["name"="Tamil Nadu"]["boundary"="administrative"]["admin_level"="4"];'
    "map_to_area ->.st;"
    'rel(area.st)["boundary"="administrative"]["admin_level"="6"];'
    "out tags center 200;"
)

for url in MIRRORS:
    t = time.perf_counter()
    try:
        r = requests.post(url, data=q, headers=HEADERS, timeout=60)
        dt = time.perf_counter() - t
        if r.status_code != 200:
            print("%-45s %s in %.1fs" % (url.split("//")[1][:40], r.status_code, dt), flush=True)
            continue
        els = r.json().get("elements") or []
        names = sorted({(e.get("tags") or {}).get("name") for e in els} - {None})
        print("%-45s 200 in %.1fs -> %d elements / %d names" % (url.split("//")[1][:40], dt, len(els), len(names)), flush=True)
        for n in names:
            print("    ", n, flush=True)
        if names:
            break
    except Exception as exc:  # noqa: BLE001
        print("%-45s FAILED in %.1fs: %s" % (url.split("//")[1][:40], time.perf_counter() - t, exc), flush=True)
