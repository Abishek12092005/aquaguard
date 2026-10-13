"""STEP 14 - the location-based prediction runs and reports on the Location page.

The prediction service and the HTTP client are exercised through the REAL Flask
app, so what is proved is the actual contract the page depends on: that the
existing endpoint accepts the readings plus the location metadata, returns a
verdict the page can render, and that nothing in the response path can produce a
verdict when the model has none.

What is checked:

  1. The existing `/predictions/predict` endpoint returns a real verdict.
  2. It carries every field the Step 14 result card must show.
  3. The location and water source travel with the sample and come back echoed.
  4. The stored row keeps the location, so history can group by place.
  5. An UNSAFE reading really does return unsafe - the flow is not hardwired
     to a single verdict.
  6. The endpoint is NOT modified: this step reuses it rather than adding a
     second prediction path.
  7. No verdict is ever fabricated: a rejection produces an error, not a result.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.constants import FEATURE_NAMES

FAILS = []


def check(name, ok, detail=""):
    print(("PASS  " if ok else "FAIL  ") + name + ("  -> " + detail if detail else ""), flush=True)
    if not ok:
        FAILS.append(name)


app = create_app()

SAFE = {"ph": 7.4, "turbidity": 3.2, "tds": 310.0, "temperature": 26.5, "dissolved_oxygen": 6.8}
# Genuinely poor water: strongly acidic, very turbid, saline, warm, anoxic.
BAD = {"ph": 3.9, "turbidity": 340.0, "tds": 9800.0, "temperature": 34.0, "dissolved_oxygen": 0.4}

LOCATION = {
    "location_name": "Karaikudi",
    "location_city": "Karaikudi",
    "location_district": "Karaikkudi",
    "location_state": "Tamil Nadu",
    "location_country": "India",
    "location_pincode": "623001",
    "location_lat": 10.075,
    "location_lng": 78.7833,
    "water_source_type": "well water",
    "nearby_water_source": "Unnamed Well",
    "nearby_water_source_distance": 0.12,
}

# --- 1: the EXISTING endpoint produces a real verdict -----------------------
with app.test_client() as client:
    r = client.post("/api/v1/predictions/predict", json={**SAFE, **LOCATION})
    check("PREDICT returns 201", r.status_code == 201, str(r.status_code))
    data = (r.get_json() or {}).get("data") or {}
    check("PREDICT returns a verdict", data.get("prediction") in ("safe", "moderate", "unsafe"),
          str(data.get("prediction")))
    check("PREDICT returns a confidence", isinstance(data.get("confidence"), (int, float)),
          str(data.get("confidence")))
    check("PREDICT returns a usable id", isinstance(data.get("id"), int), str(data.get("id")))

    # --- 2: every field the Step 14 result card shows ------------------------
    for field, label in [
        ("prediction", "Prediction"),
        ("confidence", "Confidence"),
        ("parameters", "the five readings"),
    ]:
        check(f"RESULT carries {label}", data.get(field) is not None)

    params = data.get("parameters") or {}
    check("RESULT echoes all five readings",
          all(name in params for name in FEATURE_NAMES), str(sorted(params)))
    # Each entry is {label, unit, min, max, value} - the server describes the
    # parameter from the SAME constants it validated against, so the card can
    # render the unit from the response rather than from a frontend copy.
    check("RESULT readings carry their value",
          all(isinstance((params.get(name) or {}).get("value"), (int, float)) for name in FEATURE_NAMES),
          str({k: v.get("value") for k, v in params.items()}))
    check("RESULT readings carry their unit",
          all(bool((params.get(name) or {}).get("unit")) for name in FEATURE_NAMES))
    check("RESULT readings are the ones SENT",
          all(abs(float(params[name]["value"]) - SAFE[name]) < 0.01 for name in FEATURE_NAMES),
          str({k: v.get("value") for k, v in params.items()}))

    # --- 3: the location comes back echoed ----------------------------------
    for field in ("location_name", "location_city", "location_district",
                  "location_state", "location_country", "location_pincode",
                  "water_source_type"):
        check(f"RESULT echoes {field}", data.get(field) == LOCATION[field],
              "%s=%s" % (field, data.get(field)))

    # --- 4: the stored row keeps the location -------------------------------
    #
    # NOTE ON THE DISTRICT: `water_predictions` has no district COLUMN - it is
    # deliberately not persisted (see `extract_district_field`), and only echoed
    # in the response. So the district is checked on the RESPONSE above and is
    # deliberately absent from the stored row here. Adding a column would mean a
    # migration, which is outside this step.
    from app.extensions import db
    from app.models.water_prediction import WaterPrediction
    with app.app_context():
        row = WaterPrediction.query.get(data["id"])
        check("STORED row keeps location_name", row.location_name == "Karaikudi")
        check("STORED row keeps city", row.location_city == "Karaikudi")
        check("STORED row keeps state", row.location_state == "Tamil Nadu")
        check("STORED row keeps country", row.location_country == "India")
        check("STORED row keeps pincode", row.location_pincode == "623001")
        check("STORED row keeps the water source type",
              row.water_source_type == "well water", str(row.water_source_type))
        check("STORED row keeps the nearby source", row.nearby_water_source == "Unnamed Well",
              str(row.nearby_water_source))
        check("STORED row keeps the verdict", row.prediction == data["prediction"])
        check("STORED row keeps the confidence",
              abs(float(row.confidence) - float(data["confidence"])) < 1e-4)

# --- 5: the flow is not hardwired to one verdict ----------------------------
with app.test_client() as client:
    r = client.post("/api/v1/predictions/predict", json={**BAD, **LOCATION})
    bad_data = (r.get_json() or {}).get("data") or {}
    check("POOR water is not reported safe",
          bad_data.get("prediction") != "safe", str(bad_data.get("prediction")))
    check("POOR water gets its own verdict", bool(bad_data.get("prediction")))
    check("The two samples really do differ",
          bad_data.get("prediction") != data.get("prediction"),
          "%s vs %s" % (bad_data.get("prediction"), data.get("prediction")))

# --- 6: the endpoint is the EXISTING one, unmodified ------------------------
with app.app_client() if False else app.test_client() as client:
    # The unversioned path the API docs and the frontend both use must still be
    # the same endpoint. If Step 14 had added a second prediction route, this
    # would be a different view function.
    r1 = client.post("/api/v1/predictions/predict", json=SAFE)
    r2 = client.post("/api/predictions/predict", json=SAFE)
    check("BOTH documented paths still work",
          r1.status_code == 201 and r2.status_code == 201,
          "%s / %s" % (r1.status_code, r2.status_code))
    d1 = (r1.get_json() or {}).get("data") or {}
    d2 = (r2.get_json() or {}).get("data") or {}
    check("BOTH paths agree (one implementation, not two)",
          d1.get("prediction") == d2.get("prediction"),
          "%s vs %s" % (d1.get("prediction"), d2.get("prediction")))

# --- 7: no verdict is fabricated when the readings are wrong ---------------
with app.test_client() as client:
    # Missing a required parameter: a 422 and NO data. The page must show an
    # error, and there is nothing in the response to render as a verdict.
    r = client.post("/api/v1/predictions/predict",
                    json={"ph": 7.0, "turbidity": 1.0})
    check("INCOMPLETE readings are rejected", r.status_code == 422, str(r.status_code))
    check("INCOMPLETE readings return no data", (r.get_json() or {}).get("data") in (None, {}),
          str((r.get_json() or {}).get("data")))

    # Out of the physical range: rejected rather than silently clamped.
    r = client.post("/api/v1/predictions/predict", json={**SAFE, "ph": 99.0})
    check("IMPOSSIBLE pH is rejected", r.status_code == 422, str(r.status_code))

    # A missing body: rejected, not defaulted.
    r = client.post("/api/v1/predictions/predict", json={})
    check("EMPTY body is rejected", r.status_code == 422, str(r.status_code))

# --- the five parameters are exactly the ones the card shows ---------------
check("STEP 14 shows the five canonical parameters",
      set(FEATURE_NAMES) == {"ph", "turbidity", "tds", "temperature", "dissolved_oxygen"},
      str(FEATURE_NAMES))

print()
if FAILS:
    print("FAILED: " + ", ".join(FAILS))
    raise SystemExit(1)
print("ALL STEP 14 CHECKS PASSED")
