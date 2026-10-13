# File: backend/_check_water.py
"""Standalone checks for the water-source identification logic.

Run with the backend's virtualenv:

    backend/.venv/Scripts/python.exe backend/_check_water.py

It exercises `app.services.location_service` with a mocked HTTP layer, so it makes
no network calls. What it proves: every canonical water category is reachable from
a realistic OpenStreetMap tag set, no non-water feature is ever classified, the
"unavailable" state is reached honestly (never a fabricated source), and real
names / real distances survive the shaping.
"""
import sys

sys.path.insert(0, r'c:\Users\abishek\OneDrive\Desktop\aquagaurd\backend')

from app.services import location_service as ls

# Every category maps from a realistic OSM tag set.
cases = [
    ({"waterway": "river"}, "river water"),
    ({"water": "lake"}, "lake water"),
    ({"water": "pond"}, "pond water"),
    ({"waterway": "stream"}, "surface water"),
    ({"water": "reservoir"}, "tank water"),
    ({"man_made": "water_tap"}, "piped water"),
    ({"man_made": "water_well"}, "well water"),
    ({"man_made": "borehole"}, "borewell water"),
    ({"amenity": "drinking_water"}, "piped water"),
    ({"landuse": "reservoir"}, "tank water"),
]
for tags, expected in cases:
    got = ls._classify_osm_feature(tags)
    assert got == expected, f"{tags} -> {got}, expected {expected}"
    print(f"{tags} -> {got}")

# A non-water feature is dropped, never guessed.
assert ls._classify_osm_feature({"building": "yes"}) is None
print("non-water -> None OK")

# All canonical categories are declared.
assert set(ls.WATER_TYPES) == {
    "river water", "lake water", "pond water", "surface water", "tank water",
    "piped water", "rain water", "municipal water source", "ground water",
    "borewell water", "well water",
}
print("11 WATER_TYPES OK")

# --- water_context with real mapped sources ---
ls._overpass = lambda query: {
    "elements": [
        {"type": "node", "lat": 10.07, "lon": 78.79, "tags": {"man_made": "water_well", "name": "Sambai Oothu"}},
        {"type": "way", "center": {"lat": 10.09, "lon": 78.80}, "tags": {"water": "reservoir", "name": "Nearby Tank"}},
        {"type": "way", "center": {"lat": 10.12, "lon": 78.82}, "tags": {"water": "pond"}},
        {"type": "node", "lat": 10.20, "lon": 78.90, "tags": {"building": "yes"}},
    ],
}
ctx = ls.water_context({"lat": 10.0667, "lon": 78.7833})
print("\nprimary:", ctx["primary"], "| available:", ctx["available"])
print("types:", ctx["types"])
for row in ctx["nearby"]:
    print(f"  - {row['name']} ({row['type']}) {row['distance_km']} km named={row['named']}")
assert ctx["available"] is True
assert ctx["primary"] == "well water", ctx["primary"]
assert ctx["nearby"][0]["name"] == "Sambai Oothu"
assert ctx["nearby"][0]["distance_km"] <= ctx["nearby"][1]["distance_km"]
# The unnamed pond must NOT get a fabricated name.
unnamed = [r for r in ctx["nearby"] if not r["named"]]
assert unnamed and unnamed[0]["name"].startswith("Unnamed"), unnamed
print("real names + real distances OK; no fabricated names OK")

# --- no mapped water -> unavailable, and NO fabricated source ---
ls._overpass = lambda query: {"elements": []}
ctx2 = ls.water_context({"lat": 0.0, "lon": 0.0})
print("\nempty ->", ctx2["available"], "|", ctx2["message"])
assert ctx2["available"] is False
assert ctx2["primary"] is None and ctx2["nearby"] == []
assert ctx2["message"] == "Water source information is unavailable for this location."
print("unavailable state OK (no invented source)")

# --- network failure -> unavailable, not a guess ---
ls._overpass = lambda query: None
ctx3 = ls.water_context({"lat": 1.0, "lon": 2.0})
assert ctx3["available"] is False
print("network failure -> unavailable OK")

print("\nALL WATER-SOURCE CHECKS PASSED")

# --- STEP 6: rain status (3 states) ----------------------------------------
# Rain is reported from a WEATHER SOURCE only, in the three states the flow
# names. Nothing is inferred from the season or the place.
ls._get = lambda url, params: {
    "current": {"precipitation": 0.0},
    "daily": {"time": ["d1", "d2", "d3"], "precipitation_sum": [0.0, 0.0, 0.0]},
}
r0 = ls.rain_forecast(1.0, 2.0)
assert r0["status"]["key"] == "none", r0["status"]
assert r0["alert"] is False and r0["message"] is None
print("\nrain none OK ->", r0["status"]["label"])

ls._get = lambda url, params: {
    "current": {"precipitation": 3.2},
    "daily": {"time": ["d1", "d2"], "precipitation_sum": [3.2, 0.0]},
}
r1 = ls.rain_forecast(1.0, 2.0)
assert r1["status"]["key"] == "occurring", r1["status"]
assert r1["alert"] is True and r1["message"] == ls.RAIN_ALERT_MESSAGE
print("rain occurring OK ->", r1["status"]["label"])

ls._get = lambda url, params: {
    "current": {"precipitation": 0.0},
    "daily": {"time": ["d1", "d2", "d3"], "precipitation_sum": [4.0, 2.0, 0.0]},
}
r2 = ls.rain_forecast(1.0, 2.0)
assert r2["status"]["key"] == "expected_soon", r2["status"]
assert r2["alert"] is True
print("rain expected soon OK ->", r2["status"]["label"])

# --- STEP 6: risk category (low / moderate / high) -------------------------
low = ls.risk_level({"available": True, "types": ["piped water"]})
assert low["level"] == "low", low
high = ls.risk_level({"available": True, "types": ["river water"]})
assert high["level"] == "high", high
# Rain raises a treated source one step, and never lowers a source's own level.
raised = ls.risk_level(
    {"available": True, "types": ["piped water"]},
    {"will_rain": True, "status": {"key": "occurring", "label": "Rain currently occurring"}},
)
assert raised["level"] == "moderate", raised
assert all(f["source"] in ("source type", "weather") for f in raised["factors"])
print("\nrisk low/high/raised OK ->", low["level"], high["level"], raised["level"])

# No mapped water -> no risk category is invented.
unknown = ls.risk_level({"available": False, "types": [], "message": ls.WATER_UNAVAILABLE_MESSAGE})
assert unknown["level"] == "unknown" and unknown["factors"] == []
print("risk unknown (no invented reason) OK")

print("\nALL STEP 6 CHECKS PASSED")

# --- STEP 7: prefill provenance (estimated / dataset / user input) ----------
# The readings handed to the Predict form must SAY where they came from, so a
# representative value is never presented as a measurement.
d_est = ls.default_parameters_detail("ground water", available=True)
assert d_est["source"] == ls.DATA_SOURCE_ESTIMATED
assert d_est["label"] == "Estimated"
assert set(d_est["values"]) == {"ph", "turbidity", "tds", "temperature", "dissolved_oxygen"}
assert d_est["note"]
print("\nprefill estimated OK ->", d_est["label"])

# No identified source -> NO values, and the field is the user's to fill.
d_req = ls.default_parameters_detail(None, available=False)
assert d_req["source"] == ls.DATA_SOURCE_REQUIRED
assert d_req["label"] == "User input required"
assert d_req["values"] == {}
print("prefill user-input-required OK ->", d_req["label"], "| values:", d_req["values"])

# The pre-fill and the plain default must agree, so the two payload fields the
# Predict form may read cannot disagree.
assert ls.default_parameters("well water") == ls.default_parameters_detail("well water")["values"]
print("prefill matches default parameters OK")

print("\nALL STEP 7 CHECKS PASSED")

# --- STEP 8: location metadata on a prediction request ---------------------
# The Predict form sends the identified location alongside the five readings.
# `extract_location_fields` is what reads it off the body; it must map the
# frontend's names onto the model's columns and never let a bad label raise.
from app.services.prediction_service import extract_location_fields
fields = extract_location_fields(
    {
        "ph": 7.1,
        "location_name": "Karaikudi",
        "location_city": "Karaikudi",
        "location_state": "Tamil Nadu",
        "location_country": "India",
        "location_pincode": "630001",
        "location_lat": 10.0667,
        "location_lng": 78.7833,
        "water_source_type": "ground water",
    }
)
assert fields["location_name"] == "Karaikudi"
assert fields["location_state"] == "Tamil Nadu"
assert fields["water_source_type"] == "ground water"
assert fields["location_lat"] == 10.0667 and fields["location_lng"] == 78.7833
# The measured parameters are NOT location fields and must not be swept in.
assert "ph" not in fields
print("\nlocation metadata extracted OK ->", sorted(fields))

# A prediction WITHOUT a location stays valid: no fields, no error.
assert extract_location_fields({"ph": 7.1}) == {}
print("location-less prediction OK")

# A malformed label is DROPPED, never raised - it must not hide the verdict.
bad = extract_location_fields(
    {"location_name": {"nested": "object"}, "location_lat": "not-a-number", "location_state": "  Kerala  "}
)
assert "location_name" not in bad and "location_lat" not in bad
assert bad["location_state"] == "Kerala"
print("malformed location label dropped OK")

print("\nALL STEP 8 CHECKS PASSED")

# --- STEP 9: location everywhere, WITHOUT leaking exact coordinates --------
# The admin console reads report rows. It must see WHERE a prediction came from
# as a PLACE ("Karaikudi, Tamil Nadu") and the water source, but NOT the user's
# exact latitude/longitude - that is private position data.
from app.models import WaterPrediction
from app.services.report_service import _row_to_dict

pred = WaterPrediction(
    user_id=1,
    ph=7.1, turbidity=1.2, tds=280.0, temperature=18.0, dissolved_oxygen=8.4,
    prediction="moderate", confidence=0.78,
    location_name="Karaikudi", location_city="Karaikudi", location_state="Tamil Nadu",
    location_country="India", location_pincode="630001",
    location_lat=10.0667, location_lng=78.7833,
    water_source_type="ground water",
)
row = _row_to_dict(pred, "Abishek", "abishek@aquaguard.test")
# The place labels ARE present, so the admin can see where results came from.
assert row["location_name"] == "Karaikudi"
assert row["location_state"] == "Tamil Nadu"
assert row["water_source_type"] == "ground water"
assert row["user_name"] == "Abishek"
# The EXACT coordinates are NOT: they were stripped for this reader.
assert "location_lat" not in row and "location_lng" not in row
print("\nadmin row: place kept, coordinates scrubbed OK ->", row["user_name"], ",", row["location_name"])

# `place_dict` is the boundary itself: never coordinates, always the labels.
place = pred.place_dict()
assert "location_lat" not in place and "location_lng" not in place
assert place["location_name"] == "Karaikudi" and place["water_source_type"] == "ground water"
print("place_dict excludes coordinates OK ->", sorted(place))

# The OWNER's own serialization keeps the coordinates (their own position).
owner = pred.to_dict()
assert owner["location_lat"] is not None and owner["location_lng"] is not None
assert owner["location_name"] == "Karaikudi"
print("owner to_dict keeps coordinates OK")

print("\nALL STEP 9 CHECKS PASSED")

# --- STEP 10: auth email location, without raw coordinates ------------------
# The admin's sign-up / sign-in notices name WHERE the event came from, as an
# APPROXIMATE PLACE. No coordinate may appear, and a missing place must read as
# the exact sentence "Location unavailable" without being invented.
from app.services.login_tracking_service import _client_location
from app.services.mail_service import admin_signin_notice, admin_signup_notice

sample_place = {
    "name": "Karaikudi",
    "city": "Karaikudi",
    "state": "Tamil Nadu",
    "country": "India",
    "pincode": "630001",
    # A coordinate is deliberately present in the INPUT to prove it is dropped.
    "lat": 10.0667,
    "lng": 78.7833,
}

# The tracker sanitizes the place down to its labels only.
sanitized = _client_location(sample_place)
assert set(sanitized) == {"name", "city", "state", "country", "pincode"}
assert "lat" not in sanitized and "lng" not in sanitized
print("\ntracker drops coordinates OK ->", sorted(sanitized))

# A malformed place degrades to nothing rather than raising.
assert _client_location(None) == {}
assert _client_location("not a dict") == {}
assert _client_location({"name": {"nested": 1}}) == {}
print("malformed client location dropped OK")

# The sign-up notice carries the place and no coordinate.
_, signup_text, _ = admin_signup_notice(
    "Abishek", "user@example.com", "2026-01-15T10:30:45+00:00", sample_place
)
assert "Location: Karaikudi" in signup_text
assert "State: Tamil Nadu" in signup_text
assert "Country: India" in signup_text
assert "Pincode: 630001" in signup_text
for banned in ("lat", "lng", "latitude", "longitude"):
    assert banned not in signup_text.lower(), banned
print("signup notice has place, no coordinates OK")

# The sign-in notice carries the place too.
_, login_text, _ = admin_signin_notice(
    "Abishek", "user@example.com", "2026-01-15T10:30:45+00:00", "Windows · Chrome", sample_place
)
assert "Location: Karaikudi" in login_text and "State: Tamil Nadu" in login_text
assert "longitude" not in login_text.lower()
print("login notice has place, no coordinates OK")

# No place -> the exact sentence, and never an invented one.
_, empty_text, _ = admin_signup_notice("Bob", "b@e.com", "2026-01-15T10:30:45+00:00", {})
assert "Location unavailable" in empty_text
assert "Location unavailable:" not in empty_text  # not doubled
print("missing place -> 'Location unavailable' OK")

# The notice accepts EITHER the client shape (name) or a stored row shape
# (location_name), so it cannot silently show 'unavailable' for a known place.
stored_shape = {
    "location_name": "Karaikudi", "location_city": "Karaikudi",
    "location_state": "Tamil Nadu", "location_country": "India",
    "location_pincode": "630001",
}
_, stored_text, _ = admin_signup_notice("Abishek", "u@e.com", "2026-01-15T10:30:45+00:00", stored_shape)
assert "Location: Karaikudi" in stored_text and "State: Tamil Nadu" in stored_text
print("notice accepts stored-row shape OK")

print("\nALL STEP 10 CHECKS PASSED")
