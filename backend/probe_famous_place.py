"""TEST7 direct: famous place search (Meenakshi Temple) - raw API answers."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import json

print("=== location_service.search('Meenakshi Temple') ===", flush=True)
try:
    from app.services.location_service import search
    rows = search("Meenakshi Temple", limit=5)
    print(f"rows={len(rows)}", flush=True)
    for r in rows:
        print(json.dumps(r, ensure_ascii=False)[:300], flush=True)
except Exception as exc:
    print(f"ERROR: {exc!r}", flush=True)

print("=== Nominatim raw ===", flush=True)
try:
    from app.services.location_service import _get, _SEARCH_URL
    body = _get(_SEARCH_URL, {
        "q": "Meenakshi Temple",
        "format": "jsonv2",
        "addressdetails": 1,
        "limit": 5,
    })
    for row in (body if isinstance(body, list) else [])[:3]:
        print(json.dumps({k: row.get(k) for k in ("name", "addresstype", "lat", "lon")}, ensure_ascii=False), flush=True)
except Exception as exc:
    print(f"ERROR: {exc!r}", flush=True)

print("=== Open-Meteo geocode raw ===", flush=True)
try:
    from app.services.location_service import _get, _GEOCODE_URL
    body = _get(_GEOCODE_URL, {"name": "Meenakshi Temple", "count": 5, "language": "en", "format": "json"})
    for row in ((body or {}).get("results") or [])[:3]:
        print(json.dumps({k: row.get(k) for k in ("name", "feature_code", "country", "latitude", "longitude")}, ensure_ascii=False), flush=True)
except Exception as exc:
    print(f"ERROR: {exc!r}", flush=True)
