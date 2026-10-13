# File: backend/test_geocode_probe.py
from app.services.location_service import _get, _SEARCH_URL, _GEOCODE_URL, _overpass

print("geocode Tamil Nadu:", str(_get(_GEOCODE_URL, {"name": "Tamil Nadu", "count": 10, "language": "en", "format": "json"}))[:300], flush=True)
print("nominatim Meenakshi:", str(_get(_SEARCH_URL, {"q": "Meenakshi Temple", "format": "jsonv2", "addressdetails": 1, "limit": 5}))[:300], flush=True)
print("nominatim Tamil Nadu:", str(_get(_SEARCH_URL, {"q": "Tamil Nadu", "format": "jsonv2", "addressdetails": 1, "limit": 5}))[:400], flush=True)
print("overpass India ISO:", str(_overpass('[out:json][timeout:60];relation["ISO3166-2"~"^IN-"];out tags center 5;'))[:300], flush=True)
