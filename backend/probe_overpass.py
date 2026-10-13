# AquaGuard AI - STEP 20/21 Overpass mirror probe
# Checks which Overpass API mirrors are reachable from this machine.
# Run: python backend/probe_overpass.py
import requests, time

H = {'User-Agent': 'AquaGuard/1.0 (water-quality app)'}
Q = '[out:json][timeout:20];node[amenity=cafe](12.9,79.9,13.1,80.1);out 3;'

for m in [
    'https://overpass.private.coffee/api/interpreter',
    'https://overpass-api.de/api/interpreter',
    'https://overpass.kumi.systems/api/interpreter',
    'https://overpass.osm.ch/api/interpreter',
]:
    t = time.time()
    try:
        r = requests.post(m, data=Q, headers=H, timeout=15)
        print(m, r.status_code, r.text[:150].replace('\n', ' '), round(time.time() - t, 1))
    except Exception as e:
        print(m, 'ERROR', type(e).__name__, str(e)[:120], round(time.time() - t, 1))


# --- Timing probe of the FULL nearby-water query against overpass-api.de ---
if __name__ == "__main__" and "--full" in __import__("sys").argv:
    import sys as _sys
    import os as _os
    _os.environ.setdefault("DATABASE_URL", "sqlite://")
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    from app.services import location_service as ls
    q = ls._NEARBY_QUERY.format(radius=15000, lat=13.0878, lon=80.2785)
    t = time.time()
    r = requests.post(
        "https://overpass-api.de/api/interpreter",
        data=q,
        headers={"User-Agent": "AquaGuardAI/1.0"},
        timeout=90,
    )
    print("FULL QUERY:", r.status_code, round(time.time() - t, 1), "s, elements:", len(r.json().get("elements", [])))
