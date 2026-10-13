"""STEP 30: the whole `search` path, with the providers stubbed.

The tier function is pure and tested directly, but that leaves the question that
actually matters open: does the tier reach the USER, and does it stop anything
from being hidden?

So the geocoders are stubbed with rows covering every tier at once - an exact
match, prefix matches, a same-state row, a same-district row, and rows in other
states and countries - and the real `search` runs on them. Two properties are
then asserted on the returned list:

  * the ordering follows the tiers
  * EVERY input row is still reachable - nothing is filtered

That second one is the brief's "do not hide valid results just because they are
outside the current state", and it is the assertion most likely to catch a
regression that a pure unit test cannot see.

The stubs deliberately include places from states the device is NOT in, in
several countries, because a ranking rule that quietly drops them is precisely
the failure being guarded against.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from app.services import location_service as ls  # noqa: E402

# Real-shaped geocoder rows covering every tier at once. The device is in
# Tamil Nadu / Karaikkudi, and the query is "salem".
#
# Each row is placed so that EXACTLY ONE tier applies to it. That matters: an
# earlier version of this file used names like "Chennai" against the query
# "salem", which are not prefix matches at all, so the code correctly ranked
# them as non-matches and the test asserted the wrong thing. A ranking test
# whose rows do not sit in the tier it claims proves nothing.
STUB_ROWS = [
    # TIER 0 - the EXACT name, deliberately in Kerala, far from the device.
    # Naming a place is an instruction; proximity must not overrule it.
    {"name": "Salem", "area": None, "city": "Salem", "district": "Salem",
     "state": "Kerala", "country": "India", "country_code": "IN",
     "pincode": "636001", "lat": 11.66, "lon": 78.14, "kind": "town",
     "feature_code": "PPLA", "label": "Salem, Kerala, India"},
    # TIER 1 - PREFIX matches. One in the device's own state, one in another
    # state. Both must sit above the merely-local rows below.
    {"name": "Salempore", "area": None, "city": "Salempore", "district": "Erode",
     "state": "Tamil Nadu", "country": "India", "country_code": "IN",
     "pincode": "638451", "lat": 11.30, "lon": 77.75, "kind": "town",
     "feature_code": "PPLA", "label": "Salempore, Tamil Nadu, India"},
    {"name": "Salem Bazar", "area": None, "city": "Salem", "district": "Salem",
     "state": "Kerala", "country": "India", "country_code": "IN",
     "pincode": "636009", "lat": 11.67, "lon": 78.15, "kind": "town",
     "feature_code": "PPL", "label": "Salem Bazar, Kerala, India"},
    # TIER 2 - the device's OWN DISTRICT, but the name does not match at all.
    {"name": "Karaikudi Town", "area": None, "city": "Karaikudi",
     "district": "Karaikkudi", "state": "Tamil Nadu", "country": "India",
     "country_code": "IN", "pincode": "630001", "lat": 9.97, "lon": 78.77,
     "kind": "town", "feature_code": "PPLA",
     "label": "Karaikudi, Karaikkudi, Tamil Nadu, India"},
    # TIER 3 - the device's STATE, a different district.
    {"name": "Erode", "area": None, "city": "Erode", "district": "Erode",
     "state": "Tamil Nadu", "country": "India", "country_code": "IN",
     "pincode": "638001", "lat": 11.34, "lon": 77.72, "kind": "town",
     "feature_code": "PPLA", "label": "Erode, Tamil Nadu, India"},
    # TIER 4 - another state entirely.
    {"name": "Bengaluru", "area": None, "city": "Bengaluru", "district": "Bengaluru Urban",
     "state": "Karnataka", "country": "India", "country_code": "IN",
     "pincode": "560001", "lat": 12.97, "lon": 77.59, "kind": "town",
     "feature_code": "PPLA", "label": "Bengaluru, Karnataka, India"},
    # TIER 4 - another country.
    {"name": "Charlotte", "area": None, "city": "Charlotte", "district": "Mecklenburg",
     "state": "North Carolina", "country": "United States", "country_code": "US",
     "pincode": None, "lat": 35.22, "lon": -80.84, "kind": "town",
     "feature_code": "PPLA", "label": "Charlotte, United States"},
]


def main() -> int:
    failures = []

    def check(name, condition, detail=""):
        if condition:
            print(f"  PASS  {name}")
        else:
            print(f"  FAIL  {name}  {detail}")
            failures.append(name)

    print("STEP 30: the full search path, providers stubbed")

    real_geocode = ls._geocode_candidates_many
    real_nominatim = ls._search_nominatim_many
    real_samples = ls._measured_samples_for

    def stub_many(terms, count):
        return [dict(row) for row in STUB_ROWS]

    ls._geocode_candidates_many = stub_many
    ls._search_nominatim_many = lambda terms, limit: []
    ls._measured_samples_for = lambda lat, lon, place, water_type: []

    STATE, DISTRICT = "Tamil Nadu", "Karaikkudi"
    try:
        # A generous limit, so the "nothing is hidden" check is meaningful: if
        # the search were filtering, the extra rows would be the ones missing.
        results = ls.search("salem", limit=20, autocomplete=True,
                            device_state=STATE, device_district=DISTRICT)
        # And the same query with no device area at all, to prove the ranking
        # degrades rather than breaks.
        no_device = ls.search("salem", limit=20, autocomplete=True)
    finally:
        ls._geocode_candidates_many = real_geocode
        ls._search_nominatim_many = real_nominatim
        ls._measured_samples_for = real_samples

    names = [r.get("name") for r in results]
    print("  returned:", names)

    # --- NOTHING IS HIDDEN -------------------------------------------------
    print("\nNothing is hidden - the brief's explicit prohibition")
    expected = {row["name"] for row in STUB_ROWS}
    missing = expected - set(names)
    check("every stubbed place is still returned", not missing, f"missing: {missing}")
    for far in ("Bengaluru", "Charlotte", "Salempore"):
        check(f"the out-of-state place '{far}' is still offered", far in names, names)

    # --- THE ORDER FOLLOWS THE TIERS --------------------------------------
    print("\nThe order follows the tiers")
    idx = {name: i for i, name in enumerate(names)}
    check("the exact match leads the list",
          idx.get("Salem") == 0, names[:3])
    check("prefix matches come next, ahead of proximity",
          idx["Salempore"] < idx["Karaikudi Town"],
          f"Salempore at {idx['Salempore']}, Karaikudi Town at {idx['Karaikudi Town']}")
    check("a remote prefix still outranks a same-district non-match",
          idx["Salem Bazar"] < idx["Karaikudi Town"],
          f"Salem Bazar at {idx['Salem Bazar']}, Karaikudi Town at {idx['Karaikudi Town']}")
    check("both prefix matches sit above every non-matching local row",
          max(idx["Salempore"], idx["Salem Bazar"])
          < min(idx["Karaikudi Town"], idx["Erode"]),
          names)
    check("the device's own district outranks the rest of its state",
          idx["Karaikudi Town"] < idx["Erode"],
          f"Karaikudi at {idx['Karaikudi Town']}, Erode at {idx['Erode']}")
    check("distant places are last, but present",
          idx["Bengaluru"] > idx["Erode"] and "Bengaluru" in names, names)

    # --- NO DEVICE AREA STILL WORKS ----------------------------------------
    print("\nWith no device area the search still returns everything")
    no_names = [r.get("name") for r in no_device]
    check("every place is still returned without a device area",
          not (expected - set(no_names)), f"missing: {expected - set(no_names)}")
    check("the exact match still leads with no device area",
          no_names and no_names[0] == "Salem", no_names[:3])

    # --- NO HARDCODING -----------------------------------------------------
    # Only the RANKING CODE is scanned, not its docstrings. The comments
    # deliberately cite real examples - "Anna Nagar", "Salem" - to explain WHY a
    # rule exists, and a comment cannot influence behaviour. What must not appear
    # is a place or state compared as a LITERAL in the logic, so the string
    # literals of the two functions are read instead of their comments.
    print("\nNo place or state is special-cased in the ranking logic")
    import ast
    import inspect
    for fn in (ls.search, ls._relevance_tier):
        tree = ast.parse(inspect.getsource(fn).lstrip())
        literals = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        for banned in ("Chennai", "Tamil Nadu", "Kerala", "Karnataka",
                        "Bengaluru", "Salem", "Karaikudi"):
            check(
                f"'{banned}' is not a literal in {fn.__name__}",
                banned not in literals,
                f"found in {sorted(literals & {banned})}",
            )

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {failures}")
        return 1
    print("All STEP 30 end-to-end ranking checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
