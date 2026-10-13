"""STEP 8 probe: what do the REAL providers actually return right now?

The requirement is a list of place kinds a user must be able to search. Before
changing any code, this asks the live search path for each of them and reports
what came back, so the work is driven by the provider's real behaviour rather
than by an assumption about it.

Every row is printed with its coordinates and its Nominatim category, so a hit
can be confirmed as a genuine mapped feature rather than a near-miss on name.

Usage:  python step8_probe.py
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from app.services.location_service import search  # noqa: E402

# (label, query) - the kinds the search bar must support.
CASES = [
    ("Country", "India"),
    ("State", "Tamil Nadu"),
    ("District", "Sivaganga"),
    ("City", "Chennai"),
    ("Town", "Karaikudi"),
    ("Village", "Athur"),
    ("Area", "Anna Nagar"),
    ("Nagar", "Karaikudi Anna Nagar"),
    ("Colony", "Anna Nagar Colony"),
    ("Street", "Karaikudi Main Street"),
    ("Pincode", "630001"),
    ("College", "Thiagarajar College"),
    ("School", "Karaikudi school"),
    ("Company", "TCS Karaikudi"),
    ("Shop", "Indian Bank Karaikudi"),
    ("Hotel", "Karaikudi hotel"),
    ("Hospital", "Karaikudi hospital"),
    ("Theatre", "Karaikudi theatre"),
    ("Temple", "Meenakshi Amman Temple"),
    ("Railway Station", "Karaikudi railway station"),
    ("Bus Stand", "Chennai bus stand"),
    ("Landmark", "Marina Beach"),
]

print("=" * 78)
print("PROVIDER PROBE  (live Open-Meteo + Nominatim, nothing stubbed)")
print("=" * 78)

summary = []
for label, query in CASES:
    started = time.perf_counter()
    try:
        results = search(query, limit=8)
    except Exception as exc:  # noqa: BLE001
        print(f"{label:<17} {query:<28} ERROR {exc}")
        summary.append((label, query, 0, "error"))
        continue
    elapsed = (time.perf_counter() - started) * 1000

    kinds = sorted({r.get("poi_type") or r.get("kind") or "?" for r in results})
    top = results[0] if results else None
    detail = f"{len(results):2d} hits  {elapsed:6.0f}ms  kinds={','.join(kinds)}"
    if top:
        detail += f"\n{'':>21}top: {top.get('name')} [{top.get('poi_label') or top.get('kind')}] {top.get('state') or ''}"
    print(f"{label:<17} {query:<28} {detail}")
    summary.append((label, query, len(results), ",".join(kinds)))

print("\n" + "=" * 78)
print("SUMMARY")
print("=" * 78)
empty = [s for s in summary if s[2] == 0]
thin = [s for s in summary if 0 < s[2] < 3]
for label, query, count, kinds in summary:
    mark = "OK " if count >= 3 else ("THIN" if count else "EMPTY")
    print(f"   {mark:<6} {label:<17} {query:<28} {count:2d} hits  {kinds}")
print(f"\n   empty: {len(empty)}   thin(<3): {len(thin)}   healthy: {len(summary) - len(empty) - len(thin)}")
