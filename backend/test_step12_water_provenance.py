"""STEP 12 - water-quality values are shown for any selected location, and are
NEVER presented as measurements they are not.

The database and the CSV files are stubbed, so the precedence logic is proved
deterministically rather than depending on what happens to be stored today.
What is checked:

  1. The five provenances are all reachable, in the required order.
  2. A sample AT the location wins, and is labelled `measured`.
  3. A sample at a named NEARBY source wins next, and is labelled `nearby_source`.
  4. An earlier sample for this location is labelled `historical`.
  5. The measured corpus is used before the hand-written estimate.
  6. The hand-written estimate is the LAST resort and is labelled `estimated`.
  7. When nothing is available: NO values at all, and `user_input_required`.
  8. A value is NEVER promoted to a stronger provenance than it really is.
  9. Every result is marked editable, and carries the five parameters.
 10. The corpus figures are REAL: taken from the shipped CSV, never invented.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.constants import FEATURE_NAMES
from app.services import location_service as ls

FAILS = []


def check(name, ok, detail=""):
    print(("PASS  " if ok else "FAIL  ") + name + ("  -> " + detail if detail else ""), flush=True)
    if not ok:
        FAILS.append(name)


def readings(value):
    return {name: value for name in FEATURE_NAMES}


REAL = {"ph": 7.4, "turbidity": 3.2, "tds": 310.0, "temperature": 26.5, "dissolved_oxygen": 6.8}


def use_samples(samples, primary="river water", named_source=None):
    """Point the resolver at a fixed set of stored samples."""
    ls._measured_samples_for = lambda lat, lon, place, water_type: list(samples)
    ls._nearby_source_samples = (
        lambda lat, lon, water: [
            s for s in samples
            if s["distance_m"] <= ls.NEARBY_SAMPLE_RADIUS_M
            and (named_source is None or _fold(s.get("water_type")) == _fold(named_source))
        ]
    )
    water = {"available": True, "primary": primary} if primary else {"available": False, "primary": None}
    return water


def _fold(v):
    return "".join(ch for ch in str(v or "").lower() if ch.isalnum())


PLACE = {"lat": 10.0750, "lon": 78.7833}

# --- 10: the corpus figures are real and readable ----------------------------
profile = ls._dataset_profile()
check("DATASET corpus is readable", bool(profile), str(list(profile)[:2]))
check("DATASET has real rows behind it", profile.get("sample_count", 0) > 1000,
      "rows=%s" % profile.get("sample_count"))
check("DATASET covers all five parameters",
      len(profile.get("values", {})) == len(FEATURE_NAMES))
# The medians must be physically plausible - a guard against a column being
# parsed from the wrong field, which is the realistic way this goes wrong.
ph = profile.get("values", {}).get("ph", 0)
tds = profile.get("values", {}).get("tds", 0)
check("DATASET pH is a real pH, not the SAFE/UNSAFE verdict", 4.0 < ph < 10.0, "ph=%.2f" % ph)
check("DATASET TDS is a real value, not the 0/1 Potability flag", 50 < tds < 5000, "tds=%.0f" % tds)

# --- 1 + 2: MEASURED wins when a sample is at this exact point --------------
use_samples([{"values": dict(REAL), "distance_m": 20.0, "location": "Karaikudi",
              "water_type": "river water", "created_at": "2026-01-15T00:00:00"}])
d = ls.default_parameters_detail("river water", available=True, place=PLACE,
                                 water={"available": True, "primary": "river water"})
check("MEASURED is chosen first", d["source"] == ls.DATA_SOURCE_MEASURED, d["source"])
check("MEASURED carries the real sample values", d["values"] == REAL)
check("MEASURED is labelled 'Measured data'", d["label"] == "Measured data", d["label"])

# --- 3: NEARBY SOURCE wins when nothing is at this point --------------------
use_samples([{"values": dict(REAL), "distance_m": 2400.0, "location": "Karaikudi river",
              "water_type": "river water", "created_at": "2026-02-01T00:00:00"}],
             named_source="river water")
d = ls.default_parameters_detail("river water", available=True, place=PLACE,
                                 water={"available": True, "primary": "river water"})
check("NEARBY is chosen when no exact sample", d["source"] == ls.DATA_SOURCE_NEARBY, d["source"])
check("NEARBY is labelled 'Nearby source data'", d["label"] == "Nearby source data", d["label"])
check("NEARBY states it is not this exact spot",
      "not a reading of this exact spot" in d["note"].lower(), d["note"][:80])

# --- 4: HISTORICAL for a sample that is not at a named nearby source --------
use_samples([{"values": dict(REAL), "distance_m": 800.0, "location": "Karaikudi",
              "water_type": None, "created_at": "2025-06-01T00:00:00"}],
             named_source="river water")
d = ls.default_parameters_detail("river water", available=True, place=PLACE,
                                 water={"available": True, "primary": "river water"})
check("HISTORICAL is used for an older local sample", d["source"] == ls.DATA_SOURCE_HISTORICAL, d["source"])
check("HISTORICAL is labelled 'Historical data'", d["label"] == "Historical data", d["label"])
check("HISTORICAL says it is not current", "not a current one" in d["note"].lower())

# A sample far away is not used at all.
use_samples([{"values": dict(REAL), "distance_m": 90000.0, "location": "Delhi",
              "water_type": "river water", "created_at": "2025-06-01T00:00:00"}],
             named_source="river water")
d = ls.default_parameters_detail("river water", available=True, place=PLACE,
                                 water={"available": True, "primary": "river water"})
check("A sample 90 km away is NOT used", d["source"] != ls.DATA_SOURCE_MEASURED
      and d["source"] != ls.DATA_SOURCE_NEARBY
      and d["source"] != ls.DATA_SOURCE_HISTORICAL, d["source"])

# --- 5: DATASET before the hand-written estimate ----------------------------
use_samples([])
d = ls.default_parameters_detail("river water", available=True, place=PLACE,
                                 water={"available": True, "primary": "river water"})
check("DATASET is chosen when no sample exists", d["source"] == ls.DATA_SOURCE_DATASET, d["source"])
check("DATASET is labelled 'Dataset-based estimate'",
      d["label"] == "Dataset-based estimate", d["label"])
check("DATASET values equal the real corpus medians",
      all(abs(d["values"][k] - profile["values"][k]) < 1e-9 for k in FEATURE_NAMES))
check("DATASET says how many real samples it used", d.get("sample_count", 0) > 1000)
check("DATASET says it is not this location", "not a reading taken at this location" in d["note"])

# --- 6: the plain estimate is the last resort -------------------------------
# With the corpus unreadable, the hand-written table is what remains - and it
# must say so.
real_loader = ls._dataset_profile
ls._dataset_profile = lambda: {}
d = ls.default_parameters_detail("river water", available=True, place=PLACE,
                                 water={"available": True, "primary": "river water"})
check("ESTIMATED is the last resort", d["source"] == ls.DATA_SOURCE_ESTIMATED, d["source"])
check("ESTIMATED is labelled as an estimate", "Estimated" in d["label"], d["label"])
check("ESTIMATED says it is not measured",
      "not a measurement" in d["note"].lower(), d["note"][:70])
ls._dataset_profile = real_loader

# --- 7: nothing available -> NO values, user input required ------------------
use_samples([])
d = ls.default_parameters_detail(None, available=False, place=PLACE,
                                 water={"available": False, "primary": None})
check("NO SOURCE: the dataset estimate is still offered",
      d["source"] == ls.DATA_SOURCE_DATASET, d["source"])
check("NO SOURCE: it still carries all five parameters", len(d["values"]) == len(FEATURE_NAMES))
check("NO SOURCE: it admits the source is unknown",
      d.get("water_source_known") is False)
check("NO SOURCE: it says these are not readings from it",
      "not readings from it" in d["note"])

# With no source AND no corpus there is genuinely nothing to show.
ls._dataset_profile = lambda: {}
d = ls.default_parameters_detail(None, available=False, place=PLACE,
                                 water={"available": False, "primary": None})
check("NOTHING AT ALL: no values are invented", d["values"] == {}, str(d["values"]))
check("NOTHING AT ALL: labelled 'User input required'",
      d["label"] == "User input required", d["label"])
ls._dataset_profile = real_loader

# --- 8: a value is never promoted to a stronger provenance -----------------
# A 2 km sample is NOT "measured" for this location, however good the data is.
use_samples([{"values": dict(REAL), "distance_m": 2000.0, "location": "x",
              "water_type": "river water", "created_at": "2026-01-01T00:00:00"}],
             named_source="river water")
d = ls.default_parameters_detail("river water", available=True, place=PLACE,
                                 water={"available": True, "primary": "river water"})
check("NOT promoted to 'measured' from 2 km away", d["source"] != ls.DATA_SOURCE_MEASURED, d["source"])

# A partial sample is not used at all - a blank card beats a half-filled one.
use_samples([{"values": {"ph": 7.0}, "distance_m": 10.0, "location": "y",
              "water_type": "river water", "created_at": "2026-01-01T00:00:00"}])
d = ls.default_parameters_detail("river water", available=True, place=PLACE,
                                 water={"available": True, "primary": "river water"})
check("A partial sample is not used", d["source"] != ls.DATA_SOURCE_MEASURED, d["source"])
check("A partial sample does not leak into the values",
      set(d["values"]) == set(FEATURE_NAMES), str(sorted(d["values"])))

# --- 9: every result is reviewable and complete -----------------------------
use_samples([{"values": dict(REAL), "distance_m": 20.0, "location": "z",
              "water_type": "river water", "created_at": "2026-01-01T00:00:00"}])
for water_type, available in [("river water", True), ("borewell water", True), (None, False)]:
    d = ls.default_parameters_detail(water_type, available=available, place=PLACE,
                                     water={"available": available, "primary": water_type})
    check(f"EDITABLE for {water_type}", d.get("editable") is True)
    check(f"PARAMETERS listed for {water_type}", list(d.get("parameters") or []) == list(FEATURE_NAMES))
    check(f"NOTE present for {water_type}", bool(d.get("note")) and len(d["note"]) > 20)
    check(f"LABEL present for {water_type}", bool(d.get("label")))

# Every provenance the brief names has a distinct label.
labels = {
    ls.DATA_SOURCE_MEASURED: "Measured data",
    ls.DATA_SOURCE_HISTORICAL: "Historical data",
    ls.DATA_SOURCE_DATASET: "Dataset-based estimate",
    ls.DATA_SOURCE_NEARBY: "Nearby source data",
    ls.DATA_SOURCE_REQUIRED: "User input required",
}
for source, expected in labels.items():
    check(f"LABEL '{expected}'", ls._DATA_SOURCE_LABELS.get(source) == expected,
          str(ls._DATA_SOURCE_LABELS.get(source)))

print()
if FAILS:
    print("FAILED: " + ", ".join(FAILS))
    raise SystemExit(1)
print("ALL STEP 12 CHECKS PASSED")
