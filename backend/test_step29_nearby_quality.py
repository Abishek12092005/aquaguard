"""STEP 29: the nearby-source quality resolution, on its own.

The rules this file pins down are all about what the code must NOT do, so most of
the assertions are negative ones:

  * an unnamed feature stays "Unnamed <feature>" - no invented name
  * a distance is computed from real coordinates - never a round number
  * a source with no data carries NO `values` key, so a client cannot render
    an empty set of readings as if they were measurements
  * a stored sample is matched by water TYPE, so a borewell sample cannot be
    presented as a measurement of a river

The Overpass path is not exercised: it is stubbed, because these rules are about
the quality resolution and not about the network. `test_step29_quality.py`
covers the same rules through the real route.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from app.services import location_service as ls  # noqa: E402


def _complete():
    return {name: 1.0 for name in ("ph", "turbidity", "tds", "temperature", "dissolved_oxygen")}


def main() -> int:
    failures = []

    def check(name, condition, detail=""):
        if condition:
            print(f"  PASS  {name}")
        else:
            print(f"  FAIL  {name}  {detail}")
            failures.append(name)

    print("STEP 29: nearby source quality resolution")

    # --- 1. NO STORED SAMPLE -> THE REAL DATASET ESTIMATE, LABELLED ---------
    print("\n1. A source with no stored sample gets the dataset estimate")
    source = {"type": "river water", "name": "Unnamed River", "named": False,
              "distance_km": 1.2, "lat": 10.0, "lon": 78.0}
    out = ls._nearby_source_quality(source, [])
    check("status is the estimate, not measured",
          out["status"] == ls.NEARBY_QUALITY_ESTIMATED, out["status"])
    check("it is labelled an estimate",
          "estimate" in out["label"].lower(), out["label"])
    check("it is not labelled as measured",
          "measured" not in out["label"].lower(), out["label"])
    check("it carries all five values", len(out.get("values") or {}) == 5, out.get("values"))
    check("the note says it is not a measurement of this source",
          "not a measurement of this source" in out["note"], out["note"][:80])
    check("the note states the sample count",
          "measured samples in" in out["note"], out["note"][:80])

    # --- 2. A REAL STORED SAMPLE OF THE SAME TYPE -> MEASURED ---------------
    print("\n2. A real stored sample of the same type is reported as measured")
    samples = [{
        "values": _complete(), "distance_m": 400.0, "location": "Karaikudi",
        "water_type": "River Water", "created_at": "2026-09-20T10:00:00",
    }]
    out = ls._nearby_source_quality(source, samples)
    check("status is measured", out["status"] == ls.NEARBY_QUALITY_MEASURED, out["status"])
    check("it says a measured sample is available",
          "measured" in out["label"].lower(), out["label"])
    check("the values are the stored ones", out["values"] == samples[0]["values"])
    check("the distance is the real one", out["source_distance_m"] == 400.0,
          out.get("source_distance_m"))
    check("the note names where it was measured",
          "Karaikudi" in out["note"], out["note"][:80])

    # --- 3. A SAMPLE OF A DIFFERENT TYPE IS NOT BORROWED -------------------
    print("\n3. A sample of a different water type is not borrowed")
    other = [dict(samples[0], water_type="borewell water")]
    out = ls._nearby_source_quality(source, other)
    check("it falls back to the estimate", out["status"] == ls.NEARBY_QUALITY_ESTIMATED,
          out["status"])

    # --- 4. A SAMPLE BEYOND THE RADIUS IS NOT BORROWED ----------------------
    print("\n4. A sample beyond 5 km is not presented as this source's data")
    far = [dict(samples[0], distance_m=9000.0)]
    out = ls._nearby_source_quality(source, far)
    check("it falls back to the estimate", out["status"] == ls.NEARBY_QUALITY_ESTIMATED,
          out["status"])

    # --- 5. AN UNTYPED SAMPLE IS NOT EVIDENCE ABOUT THIS FEATURE -----------
    print("\n5. A sample with no recorded water type is not matched")
    untyped = [dict(samples[0], water_type=None)]
    out = ls._nearby_source_quality(source, untyped)
    check("it falls back to the estimate", out["status"] == ls.NEARBY_QUALITY_ESTIMATED,
          out["status"])

    # --- 6. NO DATA AT ALL -> NO VALUES KEY, AND IT SAYS SO -----------------
    print("\n6. With no dataset readable, a source carries no values at all")
    real_profile = ls._dataset_profile
    ls._dataset_profile = lambda: None
    try:
        out = ls._nearby_source_quality(source, [])
    finally:
        ls._dataset_profile = real_profile
    check("status is none", out["status"] == ls.NEARBY_QUALITY_NONE, out["status"])
    check("there is no `values` key to render",
          "values" not in out, sorted(out.keys()))
    check("the label says no data is available",
          "no quality data" in out["label"].lower(), out["label"])
    check("the note tells the user to test it",
          "own test results" in out["note"], out["note"][:80])

    # --- 7. THE NAME IS NEVER INVENTED --------------------------------------
    print("\n7. An unnamed feature is labelled, not named")
    check("the honest label is used",
          ls._unnamed_label("tank water") == "Unnamed Water Tank",
          ls._unnamed_label("tank water"))
    check("an unnamed source reads as 'Unnamed ...'",
          (source.get("name") or "").startswith("Unnamed"), source.get("name"))

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {failures}")
        return 1
    print("All STEP 29 quality-resolution checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
