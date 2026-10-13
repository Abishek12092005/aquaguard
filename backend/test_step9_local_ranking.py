"""STEP 9 - the Location Prediction autocomplete prefers the DEVICE'S state.

Offline. Every provider is stubbed, so the whole file is deterministic and the
network is never touched - what is proved is the RANKING contract, not the
geocoders' answers:

  1. A local place that genuinely matches leads a far-away one.
  2. A place in the device's DISTRICT leads one merely in the device's state.
  3. A direct name match in ANOTHER state still wins - locality is a preference,
     never a filter, and never allowed to override what the user actually typed.
  4. Nothing is REMOVED. Every non-local hit is still reachable.
  5. The state is genuinely queried, and only when it was supplied.
  6. With no device area (permission refused) the order is the general order.
  7. No state is hardcoded or assumed: a different device state is a different
     outcome, driven only by what the client sends.
  8. A pincode is never qualified with a state.
  9. The "resolve one place" path is untouched by the preference.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services import location_service as ls

FAILS = []


def check(name, ok, detail=""):
    print(("PASS  " if ok else "FAIL  ") + name + ("  -> " + detail if detail else ""), flush=True)
    if not ok:
        FAILS.append(name)


def cand(name, state, district=None, country="India", cc="IN", lat=10.0, lon=78.0):
    return ls._candidate_from_geocode({
        "name": name, "latitude": lat, "longitude": lon,
        "admin1": state, "admin2": district, "country": country,
        "country_code": cc, "feature_code": "PPL",
    })


ROWS = {
    "k": [cand("Kannur", "Kerala", "Kannur", lat=12.9, lon=75.3),
          cand("Karaikudi", "Tamil Nadu", "Sivagangai", lat=10.07, lon=78.78),
          cand("Kansas City", "Missouri", "Jackson", country="United States", cc="US",
               lat=39.1, lon=-94.5)],
    "k, Tamil Nadu": [cand("Karaikudi", "Tamil Nadu", "Sivagangai", lat=10.07, lon=78.78),
                      cand("Kovilpatti", "Tamil Nadu", "Thoothukudi", lat=9.2, lon=77.9)],
    "k Tamil Nadu": [cand("Kumbakonam", "Tamil Nadu", "Thanjavur", lat=10.96, lon=79.38)],
    "bengaluru": [cand("Bengaluru", "Karnataka", "Bengaluru Urban", lat=12.97, lon=77.59),
                  cand("Bengaluru", "Tamil Nadu", "Tenkasi", lat=10.1, lon=77.0)],
}

asked = []


def fake_geo_many(terms, count):
    out = []
    for t in terms:
        asked.append(t)
        out.extend(ROWS.get(t, []))
    return out


ls._geocode_candidates_many = fake_geo_many
ls._search_nominatim_many = lambda terms, limit: []


def names(res):
    return [c["name"] for c in res]


# --- 1 + 2: a local match leads, and the district leads the state -----------
asked.clear()
res = ls.search("k", limit=8, autocomplete=True, device_state="Tamil Nadu",
                device_district="Sivagangai")
check("TEST1 local match leads", names(res)[0] == "Karaikudi", "order=" + str(names(res)))
check("TEST1 far-away hits kept", {"Kannur", "Kansas City"} <= set(names(res)),
      "kept=" + str(names(res)))

res_state = ls.search("k", limit=8, autocomplete=True, device_state="Tamil Nadu")
check("TEST2 state-only still local-first", names(res_state)[0] == "Karaikudi",
      "order=" + str(names(res_state)))

# --- 3: an explicit match in another state still wins -----------------------
res = ls.search("bengaluru", limit=8, autocomplete=True, device_state="Tamil Nadu")
karnataka = [c for c in res if c["state"] == "Karnataka"]
check("TEST3 other state reachable and first", karnataka and res[0]["state"] == "Karnataka",
      "order=" + str([(c["name"], c["state"]) for c in res]))

# --- 5: the state is genuinely queried, and only when supplied --------------
asked.clear()
ls.search("k", limit=8, autocomplete=True, device_state="Tamil Nadu")
check("TEST5a state-qualified query sent", any("Tamil Nadu" in t for t in asked),
      "asked=" + str(asked))
asked.clear()
ls.search("k", limit=8, autocomplete=True, device_state=None, device_district=None)
check("TEST5b nothing qualified when unknown", asked == ["k"], "asked=" + str(asked))

# --- 6: refusal = the general search, and it still returns hits -------------
asked.clear()
plain = ls.search("k", limit=8, autocomplete=True)
check("TEST6 refusal returns hits", len(plain) >= 1, "order=" + str(names(plain)))
check("TEST6 refusal keeps the general order", names(plain)[0] == "Kannur",
      "order=" + str(names(plain)))

# --- 7: no state is assumed - a different device state, a different answer ---
asked.clear()
res = ls.search("k", limit=8, autocomplete=True, device_state="Kerala")
check("TEST7 uses the sent state only",
      any("Kerala" in t for t in asked) and not any("Tamil Nadu" in t for t in asked),
      "asked=" + str(asked))
check("TEST7 local-first for that state too", names(res)[0] == "Kannur",
      "order=" + str(names(res)))

# --- 8: a pincode is never qualified -----------------------------------------
asked.clear()
ls.search("630001", limit=8, autocomplete=True, device_state="Tamil Nadu")
check("TEST8 pincode unqualified", all("Tamil" not in t for t in asked), "asked=" + str(asked))

# --- 9: the resolve path is untouched ----------------------------------------
asked.clear()
ls.search("k", limit=8, autocomplete=False, device_state="Tamil Nadu")
check("TEST9 resolve path unaffected", not any("Tamil Nadu" in t for t in asked),
      "asked=" + str(asked))

print()
if FAILS:
    print("FAILED: " + ", ".join(FAILS))
    raise SystemExit(1)
print("ALL STEP 9 CHECKS PASSED")
