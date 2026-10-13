"""Which lookup actually finds coordinates for a district name?"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.location_service import resolve, search

for name in ("Ariyalur", "Chengalpattu", "Chennai", "Coimbatore", "Madurai",
             "Kallakurichi", "Virudhunagar", "Tenkasi", "Mayiladuthurai"):
    t = time.perf_counter()
    p = resolve("%s, Tamil Nadu" % name)
    dt = time.perf_counter() - t
    if p:
        print("%-14s %5.2fs -> %-24s d=%-14s s=%-12s lat=%.3f lon=%.3f" % (
            name, dt, p.get("name"), p.get("district"), p.get("state"),
            p["lat"], p["lon"]))
    else:
        hits = search("%s, Tamil Nadu" % name, limit=1)
        print("%-14s %5.2fs -> resolve None, search=%s" % (name, dt, hits))
