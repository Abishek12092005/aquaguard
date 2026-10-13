"""Debug the geocoder rows for one state (ad-hoc)."""
from app.services.location_service import _get, _GEOCODE_URL

for q in ("Tamil Nadu, India", "Chennai, Tamil Nadu, India", "Chennai, India"):
    body = _get(_GEOCODE_URL, {"name": q, "count": 5, "language": "en", "format": "json"})
    rows = (body or {}).get("results") or []
    print(q, "->")
    for r in rows:
        print("   ", repr(r.get("name")), "admin1=", repr(r.get("admin1")), "fc=", r.get("feature_code"), r.get("latitude"), r.get("longitude"))
