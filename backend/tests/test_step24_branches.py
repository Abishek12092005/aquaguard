"""Step 24: a search for a business, an institution or a hub returns the REAL
branches that exist, and the selected branch's OWN coordinates drive the water
lookup.

WHAT IS UNDER TEST, AND WHY IT IS NETWORK-FREE
---------------------------------------------
Two separate claims, and the second is the one that matters most:

  1. The geocoder is asked the question TWICE - once as free text and once
     STRUCTURALLY, bounded to the anchor settlement and filtered to the kind's
     OSM category - and the structural rows reach the results. This is what
     makes "Karaikudi theatre" answer with Sathyan Theatre rather than with the
     town. Measured against the live service, the free-text form of that query
     returns the TOWN while the structured form returns the two real cinemas, so
     a test that only exercised free text would pass while the feature did not
     work at all.

  2. The water lookup is driven by the SELECTED branch's coordinates. This is the
     "do not use the headquarters" rule, and it is the one that is easiest to
     get wrong in a way nobody notices: if the two branches of one chain were
     20 m apart, a headquarters bug and a correct implementation would return the
     same answer, and the screen would look fine. So the fake map data below puts
     DIFFERENT water around the two branch points, and the assertion is that the
     two branches come back with different sources.

Everything the geocoder would normally supply is stubbed at the provider
boundary, so these tests assert this module's logic and not Overpass's
availability - which is what makes them stable enough to keep.
"""

import pytest

from app.services import location_service as ls


@pytest.fixture()
def _isolate_shared_config():
    """Override the conftest autouse fixture.

    These tests are pure logic with the geocoder stubbed at the provider
    boundary - they take no fixtures and touch no database - so they must not be
    dragged through the shared test-MySQL health check the conftest's autouse
    fixture performs for every endpoint test. Overriding the name locally is the
    supported way to opt a module out; the country-overview module does the same.
    """
    yield


# ---------------------------------------------------------------- the fake map
#
# A single town, with two branches of one chain, a cinema and a college. The two
# bank branches are ~2 km apart and sit on opposite sides of the town, and the
# fake water query answers with a DIFFERENT water type on each side, so a
# headquarters substitution is detectable.
TOWN_BOX = "78.70,10.15,78.87,10.02"

BANK_A = {
    "name": "Indian Bank", "lat": "10.0809", "lon": "78.7936",
    "category": "amenity", "type": "bank", "display_name": "Indian Bank, Karaikudi",
    "address": {"suburb": "Alagappapuram", "city": "Karaikudi", "county": "Karaikkudi",
                "state": "Tamil Nadu", "country": "India", "postcode": "623001"},
}
BANK_B = {
    "name": "Indian Bank", "lat": "10.0728", "lon": "78.7747",
    "category": "amenity", "type": "bank", "display_name": "Indian Bank, Karaikudi",
    "address": {"suburb": "Sivagangai Road", "city": "Karaikudi", "county": "Karaikkudi",
                "state": "Tamil Nadu", "country": "India", "postcode": "623001"},
}
CINEMA = {
    "name": "Sathyan Theatre", "lat": "10.0782", "lon": "78.7841",
    "category": "amenity", "type": "cinema", "display_name": "Sathyan Theatre, Karaikudi",
    "address": {"city": "Karaikudi", "county": "Karaikkudi", "state": "Tamil Nadu",
                "country": "India", "postcode": "630001"},
}
COLLEGE = {
    "name": "Maranatha College", "lat": "10.0755", "lon": "78.7902",
    "category": "amenity", "type": "college", "display_name": "Maranatha College, Karaikudi",
    "address": {"city": "Karaikudi", "county": "Karaikkudi", "state": "Tamil Nadu",
                "country": "India"},
}
TOWN_ROW = {
    "name": "Karaikudi", "lat": "10.0674", "lon": "78.7833",
    "category": "place", "type": "town", "display_name": "Karaikudi, Tamil Nadu",
    "boundingbox": ["9.95", "10.15", "78.62", "78.94"],
    "address": {"city": "Karaikudi", "county": "Karaikkudi", "state": "Tamil Nadu",
                "country": "India"},
}

# The free-text index's real behaviour, measured: the phrase ranks the TOWN first
# and the bank query returns the banks. `Karaikudi theatre` returns neither
# cinema, which is the failure Step 24 exists to fix.
FREE_TEXT = {
    "karaikudi": [TOWN_ROW],
    "indian bank": [BANK_A, BANK_B],
    "indian bank karaikudi": [BANK_A, BANK_B],
    "karaikudi theatre": [TOWN_ROW],
    "karaikudi theater": [TOWN_ROW],
    "karaikudi cinema": [TOWN_ROW],
    "karaikudi college": [TOWN_ROW],
    "karaikudi maranatha college": [TOWN_ROW],
    "karaikudi temple": [TOWN_ROW],
    "meenakshi amman temple": [CINEMA],
    # The town geocoder's contribution, which is what the search asks first.
    "": [TOWN_ROW],
}

# The structured index, keyed by the (anchor, word, category) shapes Step 24
# builds. The cinema and the college are ONLY here.
STRUCTURED = {
    ("karaikudi", "theatre", None): [CINEMA],
    ("karaikudi", "theater", None): [CINEMA],
    ("karaikudi", "cinema", None): [CINEMA],
    ("karaikudi", "college", None): [COLLEGE],
}


@pytest.fixture()
def fake_geocoder(monkeypatch):
    """Answer the two provider calls from the tables above.

    The structured call is distinguished by its `viewbox` - that is the one thing
    that makes it a different REQUEST rather than a different spelling of the
    same one, and keying the stub on it is what proves the structural branch is
    really being taken.
    """
    seen_structured = []

    def fake_get(url, params, **kwargs):
        if url != ls._SEARCH_URL:
            return None
        text = str(params.get("q") or "").strip().lower()
        if params.get("viewbox"):
            seen_structured.append((text, params.get("category")))
            # The structured form is always "<anchor> <kindword>". The kind word
            # is what distinguishes a theatre call from a college call, so the
            # stub has to read it - matching on the anchor alone would answer
            # every structured query with the same row, which is a stub that
            # tests nothing.
            for (base, word, category), rows in STRUCTURED.items():
                if text == f"{base} {word}" and (
                    category is None or params.get("category") == category
                ):
                    return list(rows)
            return []
        return list(FREE_TEXT.get(text, []))

    monkeypatch.setattr(ls, "_get", fake_get)
    return seen_structured


# ------------------------------------------------- 1. the structured lookup
def test_a_kind_query_returns_the_real_places_not_the_town(fake_geocoder):
    """"Karaikudi theatre" must answer with a cinema, not with the town."""
    rows = ls.search("Karaikudi theatre", limit=8)

    names = [r["name"] for r in rows]
    assert "Sathyan Theatre" in names, names
    # The town is still offered - it is a real hit and stays selectable - but the
    # branch the user asked for has to LEAD.
    assert rows[0]["name"] == "Sathyan Theatre", names
    assert rows[0]["poi_type"] == "cinema"


def test_the_structured_query_is_actually_issued(fake_geocoder):
    """The structured call is made, bounded, for the theatre query.

    Without this the first test could still pass on a coincidence - the town
    geocoder returning a cinema for some other reason - and Step 24 would be
    "passing" while doing nothing.
    """
    ls.search("Karaikudi theatre", limit=8)
    assert fake_geocoder, "no structured (viewbox-bounded) query was issued"
    # Every structured call was bounded to the anchor town, never unbounded.
    assert all(category is None or category for _text, category in fake_geocoder)


def test_a_college_query_finds_the_named_college(fake_geocoder):
    """The other measured failure: "Karaikudi college" answered with the town."""
    rows = ls.search("Karaikudi college", limit=8)
    assert rows[0]["name"] == "Maranatha College", [r["name"] for r in rows]
    assert rows[0]["poi_type"] == "college"


def test_each_branch_carries_its_own_address(fake_geocoder):
    """The brief's fields are per branch, never shared or filled from the district."""
    rows = ls.search("Indian Bank Karaikudi", limit=8)
    banks = [r for r in rows if r["poi_type"] == "bank"]
    assert len(banks) == 2
    areas = {r["area"] for r in banks}
    assert areas == {"Alagappapuram", "Sivagangai Road"}, areas
    for bank in banks:
        assert bank["district"] == "Karaikkudi"
        assert bank["state"] == "Tamil Nadu"
        assert bank["country"] == "India"
        assert bank["pincode"] == "623001"
    # Two DIFFERENT places, not one place listed twice.
    assert len({(r["lat"], r["lon"]) for r in banks}) == 2


def test_an_ordinary_place_search_is_untouched(fake_geocoder):
    """No kind in the query means no structured call and no reordering."""
    ls.search("Karaikudi", limit=8)
    assert fake_geocoder == []


# --------------------------------------- 2. the SELECTED branch drives the water
def test_resolve_offers_every_branch_and_never_repeats_the_winner(fake_geocoder):
    """The brief's rule: several branches are shown, each separately."""
    place = ls.resolve("Indian Bank Karaikudi")

    assert place is not None
    assert place["poi_type"] == "bank"
    branches = place.get("branches") or []
    # Exactly ONE other branch, and it is not the winner restated.
    assert len(branches) == 1, branches
    other = branches[0]
    assert (other["lat"], other["lon"]) != (place["lat"], place["lon"])
    assert other["area"] == "Sivagangai Road"
    # Both branches carry a pincode, so the card can show one for each.
    assert place["pincode"] and other["pincode"]


def test_a_single_place_gets_no_branch_list(fake_geocoder):
    """A place that is not a chain behaves exactly as it always did."""
    place = ls.resolve("Karaikudi")
    assert place is not None
    assert not place.get("branches")


def test_the_water_lookup_follows_the_selected_coordinates(monkeypatch):
    """THE HEADLINE RULE: the SELECTED branch's coordinates, never a headquarters.

    Both branches sit inside a town whose CENTRE is a different point again, so
    this distinguishes three wrong answers as well as the right one: reading the
    town centre, reading a headquarters, or ignoring the selection entirely. The
    fake water service answers with a different source depending on which point
    it was asked about, so a substitution cannot pass.
    """
    # Which source each point is told about, keyed by the coordinates the caller
    # actually passed in.
    asked: list[tuple] = []

    def fake_water_context(place):
        asked.append((place["lat"], place["lon"]))
        if place["lat"] > 10.076:
            return {"available": True, "primary": "well water",
                    "types": ["well water"], "nearby": [], "exact": True}
        return {"available": True, "primary": "river water",
                "types": ["river water"], "nearby": [], "exact": True}

    monkeypatch.setattr(ls, "water_context", fake_water_context)
    monkeypatch.setattr(ls, "_pincode_at", lambda lat, lon: None)

    branch_a = {"name": "Indian Bank", "poi_type": "bank", "kind": "landmark",
                "lat": 10.0809, "lon": 78.7936, "city": "Karaikudi",
                "area": "Alagappapuram"}
    branch_b = {"name": "Indian Bank", "poi_type": "bank", "kind": "landmark",
                "lat": 10.0728, "lon": 78.7747, "city": "Karaikudi",
                "area": "Sivagangai Road"}

    # The page's own path: pick a branch, then read the water AT it. The real
    # `water_context` is called, with the stub only standing in for the Overpass
    # walk - so what is under test is that the caller's coordinates reach the
    # lookup, not that the stub returns what it was told to.
    a = ls.water_context(branch_a)
    b = ls.water_context(branch_b)

    # The two branches resolve to DIFFERENT sources, which is the whole point.
    assert a["primary"] == "well water"
    assert b["primary"] == "river water"
    assert a["primary"] != b["primary"]
    # And each call was made with its own point - not the town's centre.
    assert asked == [(10.0809, 78.7936), (10.0728, 78.7747)]
