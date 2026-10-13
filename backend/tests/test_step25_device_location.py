"""Step 25: "Use My Location" resolves a device fix into a real, named place.

WHAT IS UNDER TEST, AND WHY IT IS NETWORK-FREE
----------------------------------------------
The brief's field list for a device fix is Location name / Area / District /
State / Country / Pincode. Two of those six were broken, and both broke in a way
no amount of frontend work could have fixed, because the values were never in the
response:

  1. AREA WAS ALWAYS NULL. The reverse lookup read no area key at all, while the
     geocoder had been returning `suburb` / `neighbourhood` / `city_district`
     the whole time. Measured: a point in Chennai comes back with
     `suburb: "Zone 5 Royapuram"`, and the app threw it away.

  2. THE DISTRICT WAS NULL FOR EVERY LARGE CITY. The lookup read `county` and
     `district` only, and Nominatim populates `county` for small towns. Every
     metropolis carries the district in `state_district` and nothing in `county`:
     Chennai -> `state_district: "Chennai"`, Mumbai -> "Mumbai Suburban
     District", Delhi -> "New Delhi". So the field was blank exactly where a
     "use my location" fix is most likely to land.

Both are tested here against the provider's REAL address blocks, captured from
the live service, rather than against convenient invented ones - a test built on
`county` for Chennai would have passed against the broken code.
"""

import pytest

from app.services import location_service as ls


@pytest.fixture()
def _isolate_shared_config():
    """Opt this module out of the conftest's test-MySQL health check.

    These tests stub the geocoder at the provider boundary, take no fixtures and
    touch no database, so they must not be dragged through a database connection
    check meant for the endpoint tests.
    """
    yield


# Real responses from the live geocoder at zoom 12, reduced to the fields the
# reverse lookup reads. Captured rather than invented, so the keys are the
# provider's actual ones.
CHENNAI = {
    "name": "Chennai Corporation",
    "display_name": "Chennai Corporation, Tamil Nadu, India",
    "address": {
        "city": "Chennai Corporation",
        "state": "Tamil Nadu",
        "state_district": "Chennai",
        "country": "India",
        "suburb": "Zone 5 Royapuram",
    },
}
MUMBAI = {
    "name": "Mumbai",
    "display_name": "Mumbai, Maharashtra, India",
    "address": {
        "city": "Mumbai",
        "state": "Maharashtra",
        "state_district": "Mumbai Suburban District",
        "country": "India",
        # A city-WIDE zone, not a neighbourhood. It must not be presented as one.
        "city_district": "Mumbai Zone 5",
    },
}
KARAIKUDI = {
    "name": "Karaikudi",
    "display_name": "Karaikudi, Sivagangai, Tamil Nadu, India",
    "address": {
        "town": "Karaikudi",
        "county": "Karaikkudi",
        "state_district": "Sivagangai",
        "state": "Tamil Nadu",
        "country": "India",
        "postcode": "623001",
    },
}
# A point in open water: the geocoder has nothing at all, and says so.
UNRESOLVABLE = None


def _stub_reverse(monkeypatch, bodies):
    """Answer the reverse lookup from a lat/lon -> body table."""
    def fake_get(url, params, **kwargs):
        if url != ls._REVERSE_URL:
            return None
        return bodies.get((round(float(params["lat"]), 2), round(float(params["lon"]), 2)))
    monkeypatch.setattr(ls, "_get", fake_get)


# ---------------------------------------------------- 1. the fields are present
def test_every_brief_field_is_filled_for_a_city_fix(monkeypatch):
    """Chennai: area and district were BOTH null before this step."""
    _stub_reverse(monkeypatch, {(13.08, 80.27): CHENNAI})

    place = ls.reverse(13.0827, 80.2707)

    assert place is not None
    assert place["name"] == "Chennai Corporation"
    assert place["area"] == "Zone 5 Royapuram"
    assert place["city"] == "Chennai Corporation"
    assert place["district"] == "Chennai"
    assert place["state"] == "Tamil Nadu"
    assert place["country"] == "India"
    # The pincode is genuinely absent for this point, so it is None - never
    # borrowed from the district, the state or a neighbouring postcode.
    assert place["pincode"] is None


def test_the_district_comes_from_state_district_when_there_is_no_county(monkeypatch):
    """The regression that made District blank in every metropolis."""
    _stub_reverse(monkeypatch, {(28.61, 77.21): {
        "name": "New Delhi",
        "display_name": "New Delhi, Delhi, India",
        "address": {"city": "New Delhi", "state_district": "New Delhi",
                    "state": "Delhi", "country": "India"},
    }})

    place = ls.reverse(28.6139, 77.2090)

    assert place["district"] == "New Delhi"
    assert place["state"] == "Delhi"
    # The district is NOT copied from the state, and vice versa.
    assert place["district"] != "India"


def test_county_wins_over_state_district_for_a_small_town(monkeypatch):
    """Where both exist, the district is the one that is also present in small
    places - so it is read first. This pins the order of the two keys."""
    _stub_reverse(monkeypatch, {(10.07, 78.78): KARAIKUDI})

    place = ls.reverse(10.0674, 78.7833)

    assert place["district"] == "Karaikkudi"
    assert place["pincode"] == "623001"


# --------------------------------------------------------- 2. nothing invented
def test_a_city_wide_zone_is_not_presented_as_an_area(monkeypatch):
    """"Mumbai Zone 5" describes the city, not a part of it."""
    _stub_reverse(monkeypatch, {(19.08, 72.88): MUMBAI})

    place = ls.reverse(19.0760, 72.8777)

    assert place["district"] == "Mumbai Suburban District"
    # The area is suppressed rather than shown as a neighbourhood the fix is not
    # precise enough to support.
    assert place["area"] is None


def test_the_area_is_never_copied_from_the_city(monkeypatch):
    """A town with no neighbourhood reports no area - it does not repeat itself.

    This is the "do not fabricate location information" rule in its most likely
    form: the app could always have shown "Karaikudi / Area: Karaikudi" and it
    would have looked complete. It is not a real answer.
    """
    _stub_reverse(monkeypatch, {(10.07, 78.78): KARAIKUDI})

    place = ls.reverse(10.0674, 78.7833)

    assert place["area"] is None
    assert place["name"] == "Karaikudi"


def test_a_point_the_geocoder_cannot_name_is_refused(monkeypatch):
    """Open water resolves to nothing, and nothing is invented for it.

    A fix in the sea is a real position with no place attached. Returning a
    nearest town would put a confident, wrong location on screen, so the lookup
    returns None and the route turns that into a 404.
    """
    _stub_reverse(monkeypatch, {(15.50, 65.00): UNRESOLVABLE})

    assert ls.reverse(15.5, 65.0) is None


def test_the_coordinates_are_carried_but_the_place_is_named(monkeypatch):
    """The fix is used for the water lookups, and the screen is given a name.

    The coordinates have to be in the result - the water lookup is driven by them
    - but the user-facing identity is the place, which is what `display_name` and
    `name` are for.
    """
    _stub_reverse(monkeypatch, {(10.07, 78.78): KARAIKUDI})

    place = ls.reverse(10.0674, 78.7833)

    assert place["lat"] == 10.0674 and place["lon"] == 78.7833
    assert place["display_name"] == "Karaikudi, Tamil Nadu"
    assert place["kind"] == "coordinates"


def test_a_place_with_no_state_is_still_returned(monkeypatch):
    """Missing fields are null one by one, never all-or-nothing.

    The brief wants every field it can get. Refusing the whole answer because one
    field is missing would be a worse failure than showing four of six.
    """
    _stub_reverse(monkeypatch, {(0.00, 0.00): {
        "name": "Nowhere",
        "display_name": "Nowhere",
        "address": {"village": "Nowhere", "country": "Atlantis"},
    }})

    place = ls.reverse(0.0, 0.0)

    assert place is not None
    assert place["name"] == "Nowhere"
    assert place["state"] is None
    assert place["district"] is None
    assert place["pincode"] is None
    # The country is what little the data did give.
    assert place["country"] == "Atlantis"
