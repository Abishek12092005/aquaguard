"""Ad-hoc probe of the Overpass admin-level=4 enumeration (not a test file)."""
from app.services.location_service import _OVERPASS_MIRRORS, _HEADERS
import requests

query = (
    '[out:json][timeout:25];'
    'relation["ISO3166-2"~"^IN-"];'
    'out center 80;'
)
r = None
for url in _OVERPASS_MIRRORS:
    try:
        r = requests.get(url, params={"data": query}, headers=_HEADERS, timeout=35)
        print(url, r.status_code, flush=True)
        if r.status_code == 200:
            break
    except Exception as exc:
        print(url, "FAILED", type(exc).__name__, str(exc)[:160], flush=True)
        r = None
els = (r.json() if r is not None else {}).get("elements") or []
print("elements:", len(els))
names = []
for e in els:
    t = e.get("tags") or {}
    c = e.get("center")
    if t.get("name"):
        names.append((t["name"], c.get("lat") if c else None, c.get("lon") if c else None))
print(len(names), names[:5])
