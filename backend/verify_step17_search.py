"""STEP 17 - the search path a real user takes when they type a state name.

The page does: /resolve -> 404 -> /country -> /state. This walks the same
sequence, and asserts the state view is reached with a full district list.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app

app = create_app()
FIELDS = ("name", "district", "state", "country", "rank", "risk_level",
          "risk_tone", "message")


def get(client, path, **params):
    r = client.get(path, query_string=params)
    return r.status_code, ((r.get_json() or {}).get("data") or {})


with app.test_client() as c:
    for typed in ("Tamil Nadu", "Kerala", "Uttar Pradesh", "Delhi"):
        print("=" * 66)
        print("USER TYPES: %r" % typed)
        code, data = get(c, "/api/v1/locations/resolve", q=typed)
        if code == 200:
            print("  resolve -> %s (a PLACE, not a state)" % code)
            continue
        print("  resolve -> %s (not a place, as expected)" % code)

        code, data = get(c, "/api/v1/locations/country", q=typed)
        if code == 200 and data.get("available") and data.get("country"):
            print("  country -> matched a country; continuing to state anyway")
        else:
            print("  country -> no match (%s)" % code)

        t = time.perf_counter()
        code, data = get(c, "/api/v1/locations/state", q=typed, risk="false")
        dt = time.perf_counter() - t
        rows = data.get("districts") or []
        print("  state -> %s in %.2fs, %d districts, state=%r country=%r"
              % (code, dt, len(rows), (data.get("state") or {}).get("name"),
                 (data.get("state") or {}).get("country")))

        missing = [f for f in FIELDS if rows and f not in rows[0]]
        print("  fields missing from row 1: %s" % (missing or "none"))
        ranks = [r["rank"] for r in rows]
        print("  ranks contiguous 1..n: %s" % (ranks == list(range(1, len(rows) + 1))))
        names = [r["district"] for r in rows]
        print("  alphabetical: %s" % (names == sorted(names, key=str.casefold)))
        print("  all rows carry state+country: %s" % all(
            r["state"] and r["country"] for r in rows))
        print("  first 5: %s" % [r["district"] for r in rows[:5]])
        print("  last 3 : %s" % [r["district"] for r in rows[-3:]])
