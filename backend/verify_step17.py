"""STEP 17 - end-to-end check: type a state, get its districts."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.services.district_service import (canonical_state, district_names,
                                           bundled_states)

print("bundled states:", len(bundled_states()))
for q in ("Tamil Nadu", "tamil nadu", "Tamil  Nadu", "Kerala", "Uttar Pradesh",
          "Maharashtra", "Delhi", "Ladakh", "Odisha"):
    names = district_names(q)
    print("%-16s -> canonical=%-22s %3d districts" % (q, canonical_state(q), len(names)))

print()
print("Tamil Nadu first 6:", district_names("Tamil Nadu")[:6])

app = create_app()
with app.test_client() as c:
    t = time.perf_counter()
    r = c.get("/api/v1/locations/state",
              query_string={"q": "Tamil Nadu", "risk": "false"})
    dt = time.perf_counter() - t
    print("\nGET /locations/state -> %s in %.2fs" % (r.status_code, dt))
    data = (r.get_json() or {}).get("data") or {}
    print("  available:", data.get("available"))
    print("  state:", (data.get("state") or {}).get("name"),
          "| country:", (data.get("state") or {}).get("country"))
    rows = data.get("districts") or []
    print("  districts:", len(rows))
    for row in rows[:6]:
        print("   ", row["rank"], row["district"], "|", row["state"], "|",
              row["country"], "|", row["risk_tone"])
    print("  summary:", data.get("summary"))
