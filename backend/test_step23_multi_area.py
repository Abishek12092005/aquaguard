"""STEP 23: does the multi-area branch work when the data DOES have several?

Measured across 32 real pincodes, the provider returns exactly one Indian postal
row per number, so the "one pincode covers several areas" branch never fires on
live data. That is a fact about this dataset, not a reason to ship the branch
untested: a pincode covering several areas is real, and when it happens the user
must be offered the choice rather than have one picked for them.

This drives the REAL service with a stubbed provider that returns two genuine
postal rows for one pincode, and asserts the outcome is the full list plus
`reason: multiple_areas` - with the coordinates each area carries, because the
chosen one is what the water lookup runs against.
"""
import sys
from unittest import mock

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import app.services.location_service as ls

PIN = "630001"


def row(area, town, county, state, lat, lon):
    return {
        "lat": str(lat), "lon": str(lon), "type": "postcode",
        "category": "place", "name": PIN,
        "address": {
            "postcode": PIN, "suburb": area, "town": town, "county": county,
            "state": state, "country": "India", "country_code": "in",
        },
    }


TWO = [
    row("Sekkalai", "Karaikudi", "Karaikkudi", "Tamil Nadu", 10.0745, 78.7727),
    row("Muthiahpuram", "Karaikudi", "Karaikkudi", "Tamil Nadu", 10.1010, 78.8100),
]
THREE = TWO + [
    row("Puthanai", "Karaikudi", "Sivaganga", "Tamil Nadu", 10.2000, 78.9000),
]

failures = []


def check(name, ok, detail=""):
    print("%s  %s%s" % ("PASS" if ok else "FAIL", name, ("  " + detail) if detail else ""))
    if not ok:
        failures.append(name)


# --- two areas --------------------------------------------------------------
with mock.patch.object(ls, "_get", return_value=TWO):
    out = ls.resolve_pincode(PIN)
check("two areas: both are returned", bool(out) and len(out.get("areas") or []) == 2,
      "areas=%d" % len((out or {}).get("areas") or []))
check("two areas: flagged as a choice, not resolved", (out or {}).get("reason") == "multiple_areas",
      "reason=%s" % (out or {}).get("reason"))
check("two areas: the top card still shows the best-ranked one",
      (out or {}).get("area") == "Sekkalai", "area=%s" % (out or {}).get("area"))
for i, a in enumerate((out or {}).get("areas") or []):
    check("two areas: area %d is complete" % i,
          bool(a.get("area") and a.get("city") and a.get("district")
               and a.get("state") and a.get("country") and a.get("pincode")
               and a.get("lat") is not None and a.get("lon") is not None),
          "%s / %s / %s pc=%s @%s,%s" % (a.get("area"), a.get("city"),
                                          a.get("district"), a.get("pincode"),
                                          a.get("lat"), a.get("lon")))

# --- three areas, one in a different district -------------------------------
with mock.patch.object(ls, "_get", return_value=THREE):
    out3 = ls.resolve_pincode(PIN)
check("three areas: all three are returned", bool(out3) and len(out3.get("areas") or []) == 3,
      "areas=%d" % len((out3 or {}).get("areas") or []))
check("three areas: the different district is distinguishable",
      any(a.get("district") == "Sivaganga" for a in (out3 or {}).get("areas") or []),
      " | ".join("%s/%s" % (a.get("area"), a.get("district")) for a in out3.get("areas")))

# --- a single area must NOT be presented as a choice ------------------------
with mock.patch.object(ls, "_get", return_value=TWO[:1]):
    one = ls.resolve_pincode(PIN)
check("single area: not a multi-area prompt", one.get("reason") == "resolved"
      and not one.get("areas"), "reason=%s areas=%s" % (one.get("reason"), one.get("areas")))

# --- foreign rows must never become options ---------------------------------
FOREIGN = TWO + [
    {"lat": "55", "lon": "82", "type": "postcode", "category": "place", "name": PIN,
     "address": {"postcode": PIN, "city": "Novosibirsk", "state": "Novosibirsk Oblast",
                 "country": "Russia", "country_code": "ru"}},
    {"lat": "4", "lon": "-75", "type": "postcode", "category": "place", "name": PIN,
     "address": {"postcode": PIN, "city": "Armenia", "county": "Armenia",
                 "state": "Quindío", "country": "Colombia", "country_code": "co"}},
]
with mock.patch.object(ls, "_get", return_value=FOREIGN):
    f = ls.resolve_pincode(PIN)
check("foreign postal rows are excluded", len(f.get("areas") or []) == 2,
      "areas=%d countries=%s" % (len(f.get("areas") or []),
                                 [a.get("country") for a in f.get("areas") or []]))

# --- non-postal features sharing the number are not areas -------------------
NOISE = TWO + [
    {"lat": "10", "lon": "78", "type": "bus_stop", "category": "highway", "name": PIN,
     "address": {"postcode": PIN, "suburb": "Bus Stop Area", "country": "India",
                 "country_code": "in"}},
]
with mock.patch.object(ls, "_get", return_value=NOISE):
    n = ls.resolve_pincode(PIN)
check("a same-number bus stop is not offered as an area",
      all(a.get("area") != "Bus Stop Area" for a in n.get("areas") or []),
      "areas=%s" % [a.get("area") for a in n.get("areas") or []])

# --- duplicate rows for the SAME place collapse to one ----------------------
DUP = [TWO[0], dict(TWO[0], lat="10.5", lon="78.9"), TWO[1]]
with mock.patch.object(ls, "_get", return_value=DUP):
    d = ls.resolve_pincode(PIN)
check("duplicate rows for one place collapse to a single area",
      len(d.get("areas") or []) == 2,
      "areas=%d" % len(d.get("areas") or []))

print("\n%s" % ("ALL PASS" if not failures else "FAILED: %s" % failures))
sys.exit(1 if failures else 0)
