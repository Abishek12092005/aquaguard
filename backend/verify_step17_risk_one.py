"""Do districts now reach a real sampled point, or still fail to locate?"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.country_service import _district_risk

rows = []
for name in ("Chennai", "Coimbatore", "Madurai", "Erode", "Kallakurichi"):
    t = time.perf_counter()
    r = _district_risk({"name": name, "state": "Tamil Nadu",
                        "country": "India"})
    rows.append((name, r, time.perf_counter() - t))

for name, r, dt in rows:
    print("%-14s %5.2fs risk=%-9s msg=%s" % (
        name, dt, r["risk_level"], (r["message"] or "sampled OK")[:60]))
located = sum(1 for _, r, _ in rows
              if "could not be located" not in (r["message"] or ""))
print("located %d/%d" % (located, len(rows)))
