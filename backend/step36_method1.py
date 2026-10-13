"""STEP 36 - METHOD 1: LOCATION PREDICTION, end to end against the live API.

search -> identify location -> water source -> water parameters ->
Analyze Water Quality -> result

Nothing is stubbed and no water-quality value is invented: every parameter
printed here is echoed back by the model endpoint from the request the real
location pipeline produced. A missing source, a missing quality reading or a
provider failure is reported as the failure it is, not filled in.
"""

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:5000/api/v1"
FAILS = []
N = 0


def check(label, ok, detail=""):
    global N
    N += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   -> {detail}" if detail else ""))
    if not ok:
        FAILS.append(label)
    return ok


def call(path, params=None, body=None, timeout=45):
    """Call the API. Returns (status, body_dict_or_text, seconds)."""
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST" if data else "GET"
    )
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        status = exc.code
    except Exception as exc:  # noqa: BLE001 - a transport failure is a result
        return 0, {"transport_error": str(exc)}, time.time() - started
    elapsed = time.time() - started
    try:
        return status, json.loads(raw), elapsed
    except json.JSONDecodeError:
        return status, raw, elapsed


def section(title):
    print("\n" + "-" * 78)
    print(title)
    print("-" * 78)


def unwrap(body, key=None):
    """Return the useful part of an API response.

    The handlers wrap some payloads in {"data": ...} and return others bare, so
    the shape is resolved here rather than assumed at each call site.
    """
    if isinstance(body, list):
        return {key: body} if key else body
    if isinstance(body, dict) and "data" in body:
        return body["data"]
    return body


def place_list(body):
    """The list of places, whichever envelope the endpoint used."""
    data = unwrap(body)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("results", "places", "locations", "items"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def show(label, value, width=1500):
    text = value if isinstance(value, str) else json.dumps(value, indent=2, default=str)
    print(f"  {label}")
    for line in str(text).splitlines():
        print("      " + line[:width])


# ---------------------------------------------------------------- 1. search
section("STEP 1  search / select a location")
status, search, s_time = call("/locations/search", {"q": "Chennai", "limit": 5})
check("search responds 200", status == 200, f"code={status} in {s_time:.2f}s")
results = place_list(search)
if not check("search returned places", bool(results), f"n={len(results or [])}"):
    show("search body", search)
    sys.exit(1)
show("first result", results[0])
place = results[0]
# The API's coordinate key is `lon` (matching the frontend contract), not `lng`.
lat, lng = place.get("lat"), place.get("lon")

# ---------------------------------------------------- 2. identify the location
section("STEP 2  identify the location")
status, resolved, r_time = call(
    "/locations/resolve", {"lat": lat, "lon": lng, "query": place.get("name")}
)
check("resolve responds 200", status == 200, f"code={status} in {r_time:.2f}s")
loc = unwrap(resolved)
if isinstance(loc, list):
    loc = loc[0] if loc else {}
show("resolved location", loc)
check("resolution carries a place name", bool(loc.get("name") or place.get("name")),
      str(loc.get("name")))
check("resolution carries coordinates", loc.get("lat") is not None and loc.get("lon") is not None,
      f"{loc.get('lat')},{loc.get('lon')}")

# ------------------------------------------------------- 3. the water source
section("STEP 3  water source")
status, water, w_time = call("/locations/water", {"lat": lat, "lon": lng})
check("water source responds 200", status == 200, f"code={status} in {w_time:.2f}s")
water_data = unwrap(water)
water_block = water_data.get("water", water_data) if isinstance(water_data, dict) else {}
source = water_block.get("primary") or {}
nearby = water_block.get("nearby") or water_block.get("nearby_sources") or []
check("a water source was identified", bool(source) or bool(nearby),
      f"primary={source!r} nearby={len(nearby)}")
show("primary source", source)
check("nearby sources were listed (fallback candidates)", len(nearby) > 0, f"n={len(nearby)}")
if nearby:
    show("first nearby source", nearby[0])
# The water lookup rides on a free shared Overpass instance, so it is measured
# against its own ceiling rather than the ~5 s the local steps fit inside.
check("the water lookup completed", w_time <= 30.0, f"{w_time:.2f}s (Overpass-backed)")

# ------------------------------------------------------ 4. the water readings
section("STEP 4  water parameters")
status, params, p_time = call(
    "/locations/parameters", {"lat": lat, "lon": lng, "type": (source or {}).get("type")}
)
check("parameters respond 200", status == 200, f"code={status} in {p_time:.2f}s")
param_data = unwrap(params)
readings = param_data.get("parameters") or param_data.get("values") or {}
check("five parameters were supplied", len(readings) >= 5, f"keys={sorted(readings)}")
show("parameters", readings)

# ----------------------------------------------- 5. Analyze Water Quality
section("STEP 5  Analyze Water Quality")
payload = {
    "ph": readings.get("ph"),
    "turbidity": readings.get("turbidity"),
    "tds": readings.get("tds"),
    "temperature": readings.get("temperature"),
    "dissolved_oxygen": readings.get("dissolved_oxygen"),
    "location_name": loc.get("name") or place.get("name"),
    "location_city": loc.get("city"),
    "location_state": loc.get("state"),
    "location_country": loc.get("country"),
    "location_district": loc.get("district"),
    "water_source_type": source or nearby[0].get("type") if (source or nearby) else None,
}
status, prediction, a_time = call("/predictions", body=payload)
check("Analyze Water Quality responds 201", status == 201, f"code={status} in {a_time:.2f}s")
if status != 201:
    show("body", prediction)
    sys.exit(1)

# ------------------------------------------------------------- 6. the result
section("STEP 6  result")
result = unwrap(prediction)
verdict = result.get("prediction") or result.get("risk_level")
confidence = result.get("confidence")
show("verdict / confidence / model", {
    "prediction": verdict, "confidence": confidence,
    "model_name": result.get("model_name"), "model_version": result.get("model_version"),
    "is_safe": result.get("is_safe"), "label": result.get("label"),
    "id": result.get("id"),
})
check("a verdict came back", verdict in ("safe", "moderate", "unsafe"), str(verdict))
check("a confidence came back", confidence is not None and 0 < float(confidence) <= 1, str(confidence))
check("the model named itself", result.get("model_name") == "random_forest_water_quality",
      str(result.get("model_name")))
check("the location came back with the result", bool(result.get("location_name")),
      str(result.get("location_name")))
check("the water source type came back with the result", bool(result.get("water_source_type")),
      str(result.get("water_source_type")))

# The Analyze step is the one the brief's ~3 s / ~5 s budget is about: it is
# pure local inference over the trained forest, with no external provider.
check("the Analyze step is inside the ~5s ceiling", a_time <= 5.0, f"{a_time:.2f}s")
check("the Analyze step is near the ~3s target", a_time <= 3.0, f"{a_time:.2f}s")
check("every non-provider step is inside ~5s", max(
    s_time, r_time, p_time, a_time) <= 5.0,
    f"max local step {max(s_time, r_time, p_time, a_time):.2f}s")
print(f"    step timings: search={s_time:.2f}s resolve={r_time:.2f}s water={w_time:.2f}s "
      f"params={p_time:.2f}s analyze={a_time:.2f}s")
print(f"    (water={w_time:.2f}s is the Overpass-backed lookup; it is cached for 1 h per place)")

# ----------------------------------------- 7. the flow is deterministic
section("STEP 7  the same place asked twice gives the same verdict")
status2, second, _ = call("/predictions", body=payload)
second_result = unwrap(second)
check("repeat verdict matches", (second_result.get("prediction") or
      second_result.get("risk_level")) == verdict, str(second_result.get("prediction")))
check("repeat confidence matches",
      abs(float(second_result.get("confidence")) - float(confidence)) < 1e-6,
      f"{second_result.get('confidence')} vs {confidence}")

print("\n" + "=" * 78)
print(f"{N - len(FAILS)}/{N} checks passed")
for name in FAILS:
    print("  FAILED:", name)
print("ALL CHECKS PASSED" if not FAILS else "FAILURES PRESENT")
print("=" * 78)
sys.exit(1 if FAILS else 0)