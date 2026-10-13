"""Probe resolve_state and the Overpass boundary queries DIRECTLY - bypass the
backend, hit the external APIs the same way the code does, print raw answers."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
from app.services.country_service import resolve_state, state_districts, resolve_district
from app.services import country_service

print("=== resolve_state('Tamil Nadu') ===", flush=True)
try:
    st = resolve_state("Tamil Nadu")
    print(json.dumps(st, ensure_ascii=False), flush=True)
    if st:
        print("=== state_districts() ===", flush=True)
        ds = state_districts(st, limit=6)
        print(f"count={len(ds)}", flush=True)
        for d in ds[:6]:
            print(json.dumps(d, ensure_ascii=False), flush=True)
except Exception as exc:
    print(f"ERROR: {exc!r}", flush=True)

print("=== resolve_district('Sivaganga') ===", flush=True)
try:
    di = resolve_district("Sivaganga")
    print(json.dumps(di, ensure_ascii=False), flush=True)
except Exception as exc:
    print(f"ERROR: {exc!r}", flush=True)

print("=== Overpass ISO3166-2 IN relations (country_states query) ===", flush=True)
try:
    from app.services.location_service import _overpass
    query = '[out:json][timeout:90];relation["ISO3166-2"~"^IN-"];out tags center 5;'
    body = _overpass(query) or {}
    elements = body.get("elements") if isinstance(body, dict) else body
    print(f"elements={len(elements or [])}", flush=True)
    for el in (elements or [])[:3]:
        print(json.dumps(el, ensure_ascii=False)[:300], flush=True)
except Exception as exc:
    print(f"ERROR: {exc!r}", flush=True)
