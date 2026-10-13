"""STEP 13 - water source information for every identified location.

Offline: Overpass is stubbed with real-shaped OSM elements, so the classification,
naming and distance rules are proved deterministically. What is checked:

  1. All eleven supported water types are declared and reachable.
  2. Real OSM tags classify to the RIGHT one of those eleven.
  3. A source WITHIN the exact radius is the location's own source.
  4. A source BEYOND it is NOT — the answer becomes the nearby list instead.
  5. An unnamed feature gets an honest "Unnamed <feature>" label.
  6. A name is NEVER invented: the map's name, or the Unnamed label, only.
  7. A distance is NEVER invented: it comes from real coordinates.
  8. No mapped water at all => unavailable, and no type is asserted.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services import location_service as ls

FAILS = []


def check(name, ok, detail=""):
    print(("PASS  " if ok else "FAIL  ") + name + ("  -> " + detail if detail else ""), flush=True)
    if not ok:
        FAILS.append(name)


# --- 1: the eleven supported types ------------------------------------------
ELEVEN = {
    "river water", "lake water", "pond water", "surface water", "tank water",
    "piped water", "rain water", "municipal water source", "ground water",
    "borewell water", "well water",
}
check("ALL ELEVEN types are declared", set(ls.WATER_TYPES) == ELEVEN,
      "declared=%d" % len(ls.WATER_TYPES))
check("No extra types are declared", len(ls.WATER_TYPES) == 11)

# --- 2: real OSM tags map to the right canonical type ------------------------
# Each case is a tag combination that genuinely appears in OpenStreetMap.
CASES = [
    ({"waterway": "river"}, "river water"),
    ({"waterway": "stream"}, "surface water"),
    ({"waterway": "canal"}, "surface water"),
    ({"natural": "water", "water": "lake"}, "lake water"),
    ({"water": "oxbow"}, "lake water"),
    ({"water": "lagoon"}, "lake water"),
    ({"natural": "bay"}, "lake water"),
    ({"water": "pond"}, "pond water"),
    ({"water": "fishpond"}, "pond water"),
    ({"water": "reservoir"}, "tank water"),
    ({"landuse": "reservoir"}, "tank water"),
    ({"landuse": "basin"}, "tank water"),
    ({"water": "basin"}, "tank water"),
    ({"man_made": "water_tap"}, "piped water"),
    ({"amenity": "drinking_water"}, "piped water"),
    ({"amenity": "water_point"}, "piped water"),
    ({"man_made": "water_tower"}, "piped water"),
    ({"man_made": "water_cistern"}, "piped water"),
    ({"man_made": "water_well"}, "well water"),
    ({"man_made": "borehole"}, "borewell water"),
    ({"natural": "spring"}, "surface water"),
    ({"water": "ditch"}, "surface water"),
    ({"water": "moat"}, "surface water"),
]
for tags, expected in CASES:
    got = ls._classify_osm_feature(tags)
    check(f"CLASSIFY {tags} -> {expected}", got == expected, f"got {got}")

# Anything that is not water at all is dropped rather than guessed at.
for tags in [{"building": "yes"}, {"highway": "residential"}, {}, {"landuse": "farmland"}]:
    check(f"DROP non-water {tags or '{}'}", ls._classify_osm_feature(tags) is None)

# Every type produced by the classifier is one of the eleven.
for tags, _ in CASES:
    got = ls._classify_osm_feature(tags)
    check(f"TYPE {got} is one of the eleven", got in ELEVEN)

# --- 5: unnamed features get an honest label --------------------------------
for kind, expected in [
    ("tank water", "Unnamed Water Tank"),
    ("pond water", "Unnamed Pond"),
    ("lake water", "Unnamed Lake"),
    ("river water", "Unnamed River"),
    ("well water", "Unnamed Well"),
    ("borewell water", "Unnamed Borewell"),
    ("piped water", "Unnamed Water Tap"),
]:
    check(f"LABEL {expected}", ls._unnamed_label(kind) == expected, ls._unnamed_label(kind))
    check(f"LABEL {expected} says 'Unnamed'", ls._unnamed_label(kind).startswith("Unnamed "))

# --- 3, 4, 6, 7: the real pipeline over stubbed OSM elements ----------------
# 0.0009 degrees of latitude is about 100 m.
def elements_at(offset_deg, tags):
    return {"type": "node", "id": 1, "lat": 10.075 + offset_deg, "lon": 78.7833,
            "tags": tags}


def run(elements):
    ls._overpass = lambda query: {"elements": elements} if elements is not None else None
    return ls.nearby_sources(10.075, 78.7833)


# A well ~100 m away IS this location's source.
rows = run([elements_at(0.0009, {"man_made": "water_well"})])
check("WELL 100m away is returned", len(rows) == 1, str(rows))
check("WELL 100m is typed 'well water'", rows[0]["type"] == "well water")
check("WELL 100m is flagged unnamed", rows[0]["named"] is False)
check("WELL 100m label is 'Unnamed Well'", rows[0]["name"] == "Unnamed Well", rows[0]["name"])
check("WELL distance is real and ~0.1km", 0.05 < rows[0]["distance_km"] < 0.15,
      str(rows[0]["distance_km"]))

ctx = None
ls._overpass = lambda query: {"elements": [elements_at(0.0009, {"man_made": "water_well"})]}
ctx = ls.water_context({"lat": 10.075, "lon": 78.7833})
check("WITHIN radius: exact is True", ctx["exact"] is True)
check("WITHIN radius: primary is the source type", ctx["primary"] == "well water", str(ctx["primary"]))
check("WITHIN radius: exact_match is returned", (ctx["exact_match"] or {}).get("name") == "Unnamed Well")

# A pond ~2 km away is NOT this location's source - it is a nearby source.
ls._overpass = lambda query: {"elements": [elements_at(0.018, {"water": "pond"})]}
ctx = ls.water_context({"lat": 10.075, "lon": 78.7833})
check("BEYOND radius: exact is False", ctx["exact"] is False)
check("BEYOND radius: primary is None (no source claimed)", ctx["primary"] is None, str(ctx["primary"]))
check("BEYOND radius: exact_match is None", ctx["exact_match"] is None)
check("BEYOND radius: nearest_type still reported", ctx["nearest_type"] == "pond water")
check("BEYOND radius: the nearby list IS returned", len(ctx["nearby"]) == 1)
check("BEYOND radius: the nearby list has name/type/distance",
      all(ctx["nearby"][0].get(k) is not None for k in ("name", "type", "distance_km")))
check("BEYOND radius: supported types are published", len(ctx["supported_types"]) == 11)

# A named feature keeps the MAP'S name, never a generated one.
ls._overpass = lambda query: {"elements": [elements_at(0.0009, {"water": "lake", "name": "Kaveri"})]}
ctx = ls.water_context({"lat": 10.075, "lon": 78.7833})
check("NAMED feature keeps the map's own name", ctx["nearest"]["name"] == "Kaveri",
      ctx["nearest"]["name"])
check("NAMED feature is flagged named", ctx["nearest"]["named"] is True)

# --- 6: a name is never invented --------------------------------------------
# Every returned name is either the map's own name or an Unnamed label.
for tags in [
    {"water": "pond"},
    {"man_made": "borehole"},
    {"amenity": "water_point"},
    {"natural": "spring"},
    {"water": "reservoir"},
    {"man_made": "water_tap"},
]:
    rows = run([elements_at(0.0009, tags)])
    got = rows[0]["name"]
    check(f"NO invented name for {tags}", got.startswith("Unnamed ") or got in ("", None) or got == tags.get("name"),
          got)

# Even a feature whose name tag is an empty string is Unnamed, not blank.
ls._overpass = lambda query: {"elements": [elements_at(0.0009, {"water": "pond", "name": "  "})]}
rows = ls.nearby_sources(10.075, 78.7833)
check("A blank name tag becomes 'Unnamed Pond'", rows[0]["name"] == "Unnamed Pond", rows[0]["name"])

# --- 7: a distance is never invented ----------------------------------------
# Two features at known separations get the right order and real distances.
ls._overpass = lambda query: {"elements": [
    elements_at(0.0009, {"man_made": "water_well"}),   # ~100 m
    {"type": "node", "id": 2, "lat": 10.075 + 0.018, "lon": 78.7833, "tags": {"water": "pond"}},  # ~2 km
]}
rows = ls.nearby_sources(10.075, 78.7833)
check("DISTANCES are ordered nearest first", rows[0]["distance_km"] < rows[1]["distance_km"],
      str([r["distance_km"] for r in rows]))
check("DISTANCES are real values", all(r["distance_km"] > 0 for r in rows))
check("DISTANCES are plausible (0.1 then 2.0 km)",
      0.05 < rows[0]["distance_km"] < 0.15 and 1.8 < rows[1]["distance_km"] < 2.2,
      str([r["distance_km"] for r in rows]))

# --- 8: nothing mapped => unavailable, and NO type is asserted ---------------
ls._overpass = lambda query: None
ctx = ls.water_context({"lat": 10.075, "lon": 78.7833})
check("NO DATA: available is False", ctx["available"] is False)
check("NO DATA: no source type is asserted", ctx["primary"] is None, str(ctx["primary"]))
check("NO DATA: the nearby list is empty", ctx["nearby"] == [])
check("NO DATA: an honest message is given", bool(ctx["message"]), str(ctx["message"]))
check("NO DATA: exact is False", ctx["exact"] is False)

ls._overpass = lambda query: {"elements": []}
ctx = ls.water_context({"lat": 10.075, "lon": 78.7833})
check("EMPTY response behaves as no data", ctx["available"] is False and ctx["primary"] is None)

# --- the exact radius is a real, documented constant ------------------------
check("EXACT radius is defined and sane", 50 < ls.EXACT_SOURCE_RADIUS_M <= 1000,
      str(ls.EXACT_SOURCE_RADIUS_M))

print()
if FAILS:
    print("FAILED: " + ", ".join(FAILS))
    raise SystemExit(1)
print("ALL STEP 13 CHECKS PASSED")
