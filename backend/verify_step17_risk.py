"""STEP 17 - the full risk path: sampling every district of a state."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app

app = create_app()
with app.test_client() as c:
    t = time.perf_counter()
    r = c.get("/api/v1/locations/state", query_string={"q": "Tamil Nadu"})
    dt = time.perf_counter() - t
    data = (r.get_json() or {}).get("data") or {}
    rows = data.get("districts") or []
    print("GET /locations/state (with risk) -> %s in %.1fs" % (r.status_code, dt))
    print("  districts:", len(rows))
    print("  summary:", data.get("summary"))
    for row in rows[:12]:
        print("   %2d %-22s | %-10s | %-6s | src=%s pts=%s" % (
            row["rank"], row["district"], row["state"], row["country"],
            row["worst_source"], row["sampled_points"]))
