"""STEP 30: autocomplete ranking, as a five-tier priority list.

The brief states the order and then forbids two things, and both prohibitions
are what these checks exist to defend:

  * "Do not hide valid results just because they are outside the current state"
  * "Do not hardcode Chennai or Tamil Nadu"

So the cases below are deliberately generic - the device is placed in whatever
state each test happens to name, and no place name is special-cased. A ranking
rule that only works for one city is the failure this file is shaped to catch.

The provider is NOT stubbed for the tier function itself, which is pure: it is
handed candidate rows and asked which tier each belongs to. That is the part
that decides the order, and testing it directly is what makes a regression
visible without a network.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from app.services import location_service as ls  # noqa: E402


def _row(name, state=None, district=None, area=None, label=None, country_code=None):
    return {
        "name": name, "state": state, "district": district,
        "area": area, "label": label, "country": "India",
        "country_code": country_code,
    }


def main() -> int:
    failures = []

    def check(name, condition, detail=""):
        if condition:
            print(f"  PASS  {name}")
        else:
            print(f"  FAIL  {name}  {detail}")
            failures.append(name)

    # A device somewhere real. No city is special: the same rules must hold for
    # whatever state the device is reported in.
    STATE = "Tamil Nadu"
    DISTRICT = "Karaikkudi"

    print("STEP 30: the five relevance tiers")

    # --- TIER 0: EXACT ----------------------------------------------------
    print("\n0. An exact match outranks everything")
    exact = _row("Salem", state="Kerala", district="Salem")
    local_prefix = _row("Salem Junction", state=STATE, district=DISTRICT)
    check("the exact match is tier 0",
          ls._relevance_tier(exact, "Salem", STATE, DISTRICT) == ls.RELEVANCE_EXACT)
    check("a local prefix is NOT tier 0, even though it is local",
          ls._relevance_tier(local_prefix, "Salem", STATE, DISTRICT) != ls.RELEVANCE_EXACT)
    check("exact beats a local prefix when sorted",
          ls._relevance_tier(exact, "Salem", STATE, DISTRICT)
          < ls._relevance_tier(local_prefix, "Salem", STATE, DISTRICT),
          "a local prefix must never outrank an exact name match")

    # --- TIER 1: PREFIX ---------------------------------------------------
    print("\n1. A prefix match outranks a merely-local row")
    prefix = _row("Chennai", state=STATE, district="Chennai")
    elsewhere = _row("Chandigarh", state="Punjab", district="Chandigarh")
    check("a prefix is tier 1",
          ls._relevance_tier(prefix, "chen", STATE, DISTRICT) == ls.RELEVANCE_PREFIX)
    check("a prefix outranks a non-matching local row",
          ls._relevance_tier(prefix, "chen", STATE, DISTRICT)
          < ls._relevance_tier(_row("Somewhere", state=STATE), "chen", STATE, DISTRICT))
    # The remote row still exists and still gets a tier - it is ranked, not hidden.
    check("a remote non-match is still ranked, not dropped",
          ls._relevance_tier(elsewhere, "chen", STATE, DISTRICT) == ls.RELEVANCE_OTHER)

    # --- TIER 2 vs 3: THE DISTRICT IS THE SMALLER, NEARER AREA -------------
    # The query used here is one that is NOT a prefix of these names, so the
    # state/district tiers are actually reached. A row that IS a prefix match
    # returns tier 1 and never gets this far - which is correct, because the
    # brief ranks a prefix match ABOVE a merely-local one.
    print("\n2/3. A row in the device's state is nearer than one that is not")
    in_state = _row("Erode", state=STATE, district="Erode")
    out_state = _row("Erode", state="Odisha", district="Erode")
    check("a row in the device's state is tier 3",
          ls._relevance_tier(in_state, "xyz", STATE, DISTRICT) == ls.RELEVANCE_SAME_STATE,
          ls._relevance_tier(in_state, "xyz", STATE, DISTRICT))
    check("a row outside it is tier 4",
          ls._relevance_tier(out_state, "xyz", STATE, DISTRICT) == ls.RELEVANCE_OTHER,
          ls._relevance_tier(out_state, "xyz", STATE, DISTRICT))
    check("the local row sorts above the distant one",
          ls._relevance_tier(in_state, "xyz", STATE, DISTRICT)
          < ls._relevance_tier(out_state, "xyz", STATE, DISTRICT))

    print("\n3. The device's own district is nearer than the rest of its state")
    in_district = _row("Karaikudi", state=STATE, district=DISTRICT)
    in_other_district = _row("Karaikudi", state=STATE, district="Thanjavur")
    check("the same district is tier 2",
          ls._relevance_tier(in_district, "xyz", STATE, DISTRICT) == ls.RELEVANCE_NEARBY,
          ls._relevance_tier(in_district, "xyz", STATE, DISTRICT))
    check("a different district of the same state is tier 3",
          ls._relevance_tier(in_other_district, "xyz", STATE, DISTRICT) == ls.RELEVANCE_SAME_STATE,
          ls._relevance_tier(in_other_district, "xyz", STATE, DISTRICT))
    check("the nearer district sorts first",
          ls._relevance_tier(in_district, "xyz", STATE, DISTRICT)
          < ls._relevance_tier(in_other_district, "xyz", STATE, DISTRICT))
    check("BOTH local tiers are reachable (the district is not dead code)",
          ls._relevance_tier(in_district, "xyz", STATE, DISTRICT)
          != ls._relevance_tier(in_other_district, "xyz", STATE, DISTRICT),
          "a district hit must be distinguishable from a mere state hit")

    print("\n   A PREFIX MATCH STILL OUTRANKS PROXIMITY, as the brief requires")
    check("a local prefix beats a same-state non-match",
          ls._relevance_tier(in_district, "kara", STATE, DISTRICT)
          < ls._relevance_tier(in_other_district, "xyz", STATE, DISTRICT),
          "prefix (#2) must outrank same-state (#4)")

    # --- THE TIER ORDER IS EXACTLY 0 < 1 < 2 < 3 < 4 ----------------------
    print("\nThe tiers are in the order the brief states")
    ordered = [
        ls._relevance_tier(exact, "Salem", STATE, DISTRICT),
        ls._relevance_tier(local_prefix, "Salem", STATE, DISTRICT),
        ls._relevance_tier(in_district, "xyz", STATE, DISTRICT),
        ls._relevance_tier(in_other_district, "xyz", STATE, DISTRICT),
        ls._relevance_tier(out_state, "xyz", STATE, DISTRICT),
    ]
    check("tier 0 (exact) sorts first", ordered[0] == 0, ordered[0])
    check("tier 1 (prefix) follows", ordered[1] == 1, ordered[1])
    check("tier 2 (district) precedes tier 3 (state)", ordered[2] == 2, ordered[2])
    check("tier 3 (state) precedes tier 4 (other)", ordered[3] == 3, ordered[3])
    check("tier 4 (other) is last", ordered[4] == 4, ordered[4])

    # --- A SINGLE CHARACTER -------------------------------------------------
    print("\nA single character still returns prefix matches")
    one = _row("Chennai", state=STATE)
    check('"c" is a prefix match for Chennai',
          ls._relevance_tier(one, "c", STATE, DISTRICT) == ls.RELEVANCE_PREFIX)
    # "C" is one letter; it must not be credited as a mid-word coincidence.
    check('"c" is NOT an exact match for Chennai',
          ls._relevance_tier(one, "c", STATE, DISTRICT) != ls.RELEVANCE_EXACT)
    # The mirror image of the old failure: a two-letter fragment must not be
    # credited inside an unrelated name.
    swiss = _row("Schweiz", state="Bern", country_code="CH")
    check('"c" inside "Schweiz" is not treated as a match',
          ls._relevance_tier(swiss, "c", STATE, DISTRICT) == ls.RELEVANCE_OTHER)

    # --- NO DEVICE AREA: DEGRADES, NEVER ERRORS ----------------------------
    print("\nWith no device area the ranking still works")
    check("a prefix is still tier 1 with no device area",
          ls._relevance_tier(prefix, "chen", None, None) == ls.RELEVANCE_PREFIX)
    check("everything else is tier 4 with no device area",
          ls._relevance_tier(elsewhere, "chen", None, None) == ls.RELEVANCE_OTHER)
    check("an empty query is tier 4, not an exception",
          ls._relevance_tier(prefix, "", STATE, DISTRICT) == ls.RELEVANCE_OTHER)

    # --- AN AREA FIELD CAN SUPPLY THE MATCH -------------------------------
    print("\nA locality named in the area field is matched, not missed")
    suburb = _row("Tiruvannamalai", state=STATE, district="Tiruvannamalai", area="Anna Nagar")
    check("a match in the area field counts as a match",
          ls._relevance_tier(suburb, "anna nagar", STATE, DISTRICT)
          in (ls.RELEVANCE_EXACT, ls.RELEVANCE_PREFIX))

    # --- NOTHING IS HARDCODED ---------------------------------------------
    print("\nNo place or state is special-cased")
    import inspect
    src = inspect.getsource(ls._relevance_tier)
    for banned in ("Chennai", "Tamil Nadu", "Kerala", "India"):
        check(f"'{banned}' does not appear in the tier function", banned not in src)

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {failures}")
        return 1
    print("All STEP 30 tier checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
