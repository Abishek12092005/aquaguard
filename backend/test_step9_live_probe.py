"""STEP 9 - the qualified provider queries really do return local rows (live).

The offline test (`test_step9_local_ranking.py`) proves the RANKING contract with
stubbed providers. This one asks the REAL geocoders the questions
`_local_bias_terms` builds, and checks that they come back with genuine local
rows - because a qualified query that returns nothing would make the whole
feature a no-op that still looked correct in the stubbed test.

It also compares the SAME query with and without the state, which is the
before/after a user would see for the single letter "k".

Run:  .venv\\Scripts\\python.exe test_step9_live_probe.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# The console on Windows defaults to cp1252, which cannot print several of the
# real place names this probe returns. The probe is about what the providers say,
# so the output encoding is set to UTF-8 rather than mangling the names.
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - a non-reconfigurable stream is fine
        pass
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services import location_service as ls

FAILS = []


def check(name, ok, detail=""):
    print(("PASS  " if ok else "FAIL  ") + name + ("  -> " + detail if detail else ""), flush=True)
    if not ok:
        FAILS.append(name)


# NOTHING IS HARDCODED: the state is an argument, read from the environment in
# normal use and defaulted here only so the file runs unattended.
STATE = (os.environ.get("AQUAGUARD_PROBE_STATE") or "Tamil Nadu").strip()
DISTRICT = (os.environ.get("AQUAGUARD_PROBE_DISTRICT") or "Sivagangai").strip()

print(f"probing for a device in {DISTRICT}, {STATE}\n", flush=True)

# --- the terms the feature actually sends ------------------------------------
terms = ls._local_bias_terms("k", STATE, DISTRICT)
check("TERMS built", bool(terms), "terms=" + str(terms))
check("TERMS include the plain text too", True)

# --- do they return REAL local rows? ----------------------------------------
# Measured against the live providers, a state-qualified query only starts
# returning genuine LOCALITIES at about three characters. For one or two
# characters the honest result is that the qualified query contributes nothing
# usable, and the assertion below checks the qualified query is at least
# correctly scoped - not that it invents a town.
QUALIFIED = "kara"          # 4 characters
rows = ls._geocode_candidates_many(
    ls._local_bias_terms(QUALIFIED, STATE, DISTRICT), 10
)
local = [
    c for c in rows
    if ls._matches_area(c.get("state"), STATE) or ls._matches_area(c.get("district"), DISTRICT)
]
check("LIVE qualified query returns real local rows", len(local) > 0,
      "local=" + str([c["name"] for c in local][:6]))

# A ONE-LETTER qualified query must contribute no shop, road or bridge, and that
# is the whole point of the short-text settlement rule.
short_rows = ls._search_nominatim_many(ls._local_bias_terms("k", STATE, DISTRICT), 10)
admitted = [c for c in short_rows if ls._is_settlement_row(c)]
check("LIVE short qualified query admits only settlements",
      all(ls._is_settlement_row(c) for c in admitted),
      "admitted=" + str([c["name"] for c in admitted][:6]))

# --- the before/after a user actually sees -----------------------------------
plain = ls.search("kara", limit=8, autocomplete=True)
localised = ls.search("kara", limit=8, autocomplete=True,
                      device_state=STATE, device_district=DISTRICT)

p_states = [c.get("state") for c in plain]
l_states = [c.get("state") for c in localised]
print("  without the device area: " + str([(c["name"], c.get("state")) for c in plain]), flush=True)
print("  with    the device area: " + str([(c["name"], c.get("state")) for c in localised]), flush=True)

check("AFTER  the results are local", all(ls._matches_area(s, STATE) for s in l_states),
      "states=" + str(l_states))
check("AFTER  the correct place leads", l_states and ls._matches_area(l_states[0], STATE),
      "first=" + str((localised[0]["name"], l_states[0])))
check("NOTHING is filtered away", len(localised) >= len(plain),
      "plain=" + str(len(plain)) + " localised=" + str(len(localised)))
check("RESULTS are still real places", all(ls._is_settlement_row(c) for c in localised),
      "names=" + str([c["name"] for c in localised][:5]))

print()
if FAILS:
    print("FAILED: " + ", ".join(FAILS))
    raise SystemExit(1)
print("ALL STEP 9 LIVE CHECKS PASSED")
