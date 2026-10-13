"""Targeted retest of the two Overpass-dependent checks only:
TEST3 (district places) and TEST4-water (nearby sources). Long timeouts."""

import json
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:5000/api/v1"
EMAIL = "step32final@aquaguard.test"
PASSWORD = "Str0ngPass!2026"


def request(path, token=None, timeout=1500):
    url = BASE + urllib.parse.quote(path, safe="/?&= ").replace(" ", "%20")
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


login = json.loads(urllib.request.urlopen(urllib.request.Request(
    BASE + "/auth/login", method="POST",
    data=json.dumps({"email": EMAIL, "password": PASSWORD}).encode(),
    headers={"Content-Type": "application/json"}), timeout=60).read())
token = login["data"]["tokens"]["access_token"]
print("login ok", flush=True)

print("=== TEST4-water: /locations/water?lat=10.0740&lon=78.7800 ===", flush=True)
try:
    w = request("/locations/water?lat=10.0740&lon=78.7800", token)
    water = w["data"]["water"]
    nearby = water.get("nearby") or []
    print(f"available={water.get('available')} primary={water.get('primary')} "
          f"nearby={len(nearby)}", flush=True)
    for n in nearby[:3]:
        print(f"  {n.get('name')} | {n.get('kind')} | {n.get('distance_km')} km", flush=True)
    print("WATER_RESULT:", "PASS" if water.get("available") and nearby else "EMPTY", flush=True)
except Exception as exc:
    print(f"WATER ERROR: {exc!r}", flush=True)

print("=== TEST3: /locations/district?q=Sivaganga ===", flush=True)
try:
    d = request("/locations/district?q=Sivaganga", token)
    data = d["data"]
    places = data.get("places")
    items = places.get("items", places) if isinstance(places, dict) else (places or [])
    print(f"places={len(items)}", flush=True)
    for p in items[:9]:
        print(f"  {p.get('name')} | {p.get('area')} | {p.get('district')}, {p.get('state')}", flush=True)
    labels = any(any(k in p for k in ("prediction", "verdict", "risk_category", "risk_level"))
                 for p in items if isinstance(p, dict))
    print("DISTRICT_RESULT:", "PASS" if items and not labels else "EMPTY_OR_LABELLED", flush=True)
except Exception as exc:
    print(f"DISTRICT ERROR: {exc!r}", flush=True)
