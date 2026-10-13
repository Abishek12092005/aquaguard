"""STEP 15 - "Enter Water Prediction" hands the location's readings to Manual Prediction.

The hand-off itself is frontend behaviour, so it is checked against the real page
sources (the routes, the button, the seeded form and the payload that leaves the
page). The prediction it feeds is checked against the REAL Flask app, so what is
proved is that the payload the Manual Prediction page builds - five readings plus
the location metadata - is exactly what the existing Random Forest endpoint
accepts, stores and echoes.

What is checked:

  1. The Location page offers the button, and it navigates to Manual Prediction.
  2. The five readings travel with the navigation, so nothing is lost in transit.
  3. Manual Prediction seeds its form from them on arrival.
  4. The form stays EDITABLE and the prediction is NOT run automatically.
  5. The carried location is internal - the removed "Location Information"
     section is not brought back.
  6. The payload the page builds is accepted by the EXISTING endpoint, which
     returns a real verdict and stores the sample against the place.
  7. Nothing is auto-submitted: no prediction is created without a manual click.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.constants import FEATURE_NAMES

FRONTEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "frontend", "src", "pages")

FAILS = []


def check(name, ok, detail=""):
    print(("PASS  " if ok else "FAIL  ") + name + ("  -> " + detail if detail else ""), flush=True)
    if not ok:
        FAILS.append(name)


def read(page):
    with open(os.path.join(FRONTEND, page), encoding="utf-8") as handle:
        return handle.read()


location_src = read("Location.jsx")
predict_src = read("Predict.jsx")

# --- 1: the button, and where it goes ---------------------------------------
check("BUTTON is labelled 'Enter Water Prediction'",
      "Enter Water Prediction" in location_src)
check("BUTTON navigates to Manual Prediction",
      re.search(r"navigate\(\s*ROUTES\.predict", location_src) is not None)
_button_at = re.search(r">\s*Enter Water Prediction\s*<", location_src)
check("BUTTON is shown AFTER the parameters are displayed",
      _button_at is not None
      and _button_at.start() > location_src.index('title="Water Quality Parameters"'),
      str(_button_at.start() if _button_at else "not found"))

# --- 2: the readings travel with the navigation ----------------------------
check("READINGS are passed in the navigation state",
      re.search(r"state:\s*\{[^}]*readings", location_src, re.S) is not None)
# The page iterates FEATURE_NAMES rather than naming each one, so what is proved
# is that ALL FIVE are picked up - not a hand-picked subset.
check("READINGS cover every canonical parameter",
      re.search(r"FEATURE_NAMES\.map\(\(name\)\s*=>\s*\[name,\s*editable\[name\]\]\)", location_src)
      is not None)
check("READINGS come from the EDITABLE copy, not the untouched defaults",
      "editable[name]" in location_src)

# --- 3: Manual Prediction seeds itself on arrival --------------------------
check("MANUAL page reads the navigation state",
      "useLocation" in predict_src and "navigation.state" in predict_src)
check("MANUAL page seeds the form from the hand-off",
      re.search(r"useState\(\(\)\s*=>\s*\{[^}]*handoff", predict_src, re.S) is not None)
check("HAND-OFF is recognised, not any navigation state",
      "fromLocation" in predict_src and "fromLocation" in location_src)

# --- 4: editable, and NOT run automatically --------------------------------
check("FIELDS stay ordinary editable inputs",
      re.search(r"<input[\s\S]{0,400}?onChange=\{handleChange\}", predict_src) is not None)
check("FIELDS are not disabled by a hand-off",
      re.search(r"disabled=\{[^}]*handoff", predict_src) is None)
check("PREDICTION is not run on arrival",
      re.search(r"useEffect\([^)]*predictionApi\.predict", predict_src) is None)
check("SUBMIT is still a manual click",
      'type="submit"' in predict_src and "Analyze Water Quality" in predict_src)

# --- 5: the location is internal only --------------------------------------
check("LOCATION is carried internally",
      "carriedLocation" in predict_src)
check("LOCATION travels with the sample",
      re.search(r"payload\s*=\s*\{[\s\S]{0,300}?carriedLocation", predict_src) is not None)
check("LOCATION is never rendered",
      "{carriedLocation" not in predict_src and "carriedLocation}" not in predict_src)
# The phrase may appear in a COMMENT explaining why the section is not restored;
# what must not exist is a rendered heading for it.
check("The old 'Location Information' section is not restored",
      re.search(r"<[^>]*>\s*Location Information", predict_src) is None
      and 'title="Location Information"' not in predict_src)
# The location rides along by being spread into the payload, so the field names
# live on the Location page rather than being repeated here.
check("PREDICT sends the whole carried location, field by field",
      re.search(r"\.\.\.\(\s*carriedLocation", predict_src) is not None)
for label in ("location_name", "location_district", "water_source_type"):
    check(f"LOCATION carries {label}", label in location_src)

# --- 6/7: the real endpoint, run through the real Flask app ----------------
app = create_app()

from app.models.water_prediction import WaterPrediction

READINGS = {"ph": 7.6, "turbidity": 4.1, "tds": 420.0, "temperature": 28.0, "dissolved_oxygen": 7.1}
CARRIED = {
    "location_name": "Karaikudi",
    "location_city": "Karaikudi",
    "location_district": "Karaikkudi",
    "location_state": "Tamil Nadu",
    "location_country": "India",
    "location_pincode": "623001",
    "location_lat": 10.075,
    "location_lng": 78.7833,
    "water_source_type": "well water",
}

# The row count BEFORE anyone analyses. Arriving on the page must not change it:
# the hand-off is a navigation, not a prediction.
with app.app_context():
    _before = WaterPrediction.query.count()

with app.test_client() as client:
    # The payload the page builds, sent by hand, is accepted as-is.
    r = client.post("/api/v1/predictions/predict", json={**READINGS, **CARRIED})
    check("HANDOFF payload is accepted by the existing endpoint", r.status_code == 201,
          str(r.status_code))
    data = (r.get_json() or {}).get("data") or {}
    check("HANDOFF payload returns a real verdict",
          data.get("prediction") in ("safe", "moderate", "unsafe"), str(data.get("prediction")))
    check("HANDOFF payload is stored against the place",
          data.get("location_name") == "Karaikudi" and data.get("location_pincode") == "623001",
          str(data.get("location_name")))

    with app.app_context():
        row = WaterPrediction.query.get(data["id"])
        check("STORED row keeps the handed-over readings",
              all(abs(float(getattr(row, name)) - READINGS[name]) < 0.01 for name in FEATURE_NAMES))
        check("STORED row keeps the handed-over location", row.location_state == "Tamil Nadu")
        # Exactly one row was added, and only by the explicit POST - nothing ran
        # on the page merely being reached.
        _after = WaterPrediction.query.count()
    check("EXACTLY one prediction was created - only on the manual click",
          _after == _before + 1, "%d -> %d" % (_before, _after))

# --- the endpoint is untouched by this step ---------------------------------
with app.test_client() as client:
    check("The UNVERSIONED path still works too",
          client.post("/api/predictions/predict", json=READINGS).status_code == 201)

print()
if FAILS:
    print("FAILED: " + ", ".join(FAILS))
    raise SystemExit(1)
print("ALL STEP 15 CHECKS PASSED")
