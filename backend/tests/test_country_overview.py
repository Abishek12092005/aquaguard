"""Step-19: the country overview's state risk aggregation, without the network.

The property that matters: the state indicator is CALCULATED from mapped water
data through the same derivation as a single place's risk — never randomly
assigned. The Overpass/rain lookups are stubbed at the service boundary so the
aggregation logic itself is what is under test.
"""

import pytest

from app.services import country_service, location_service


@pytest.fixture()
def _isolate_shared_config():
    """Override the conftest autouse fixture.

    These tests are PURE aggregation logic — they take no fixtures and touch no
    database — so they must not be dragged through the shared test-MySQL health
    check the conftest's autouse fixture performs for every endpoint test.
    Overriding the name locally is the supported way to opt a module out.
    """
    yield


def test_state_risk_uses_worst_source_baseline():
    river = {"available": True, "types": ["river water", "piped water"]}
    level = country_service._state_risk_from_samples(river, rain=None)
    assert level["level"] == "high"  # river water is the worst baseline
    assert any("river water" in f["detail"] for f in level["factors"])


def test_state_risk_raises_with_rain():
    piped = {"available": True, "types": ["piped water"]}
    no_rain = {"status": {"key": "none"}, "will_rain": False}
    raining = {"status": {"key": "expected_soon", "label": "Rain expected soon"}, "will_rain": True}
    assert country_service._state_risk_from_samples(piped, no_rain)["level"] == "low"
    assert country_service._state_risk_from_samples(piped, raining)["level"] == "moderate"


def test_no_water_data_is_unknown_never_invented():
    """No mapped water must produce `unknown` and an explanation, never a colour.

    STEP 36: this assertion used to compare against the exact string
    "Water source information is unavailable for this location." and had been
    failing for some time. That was a STALE ASSERTION, not a regression.

    `country_service._state_risk_from_samples` deliberately does NOT pass the
    water lookup's message through. The lookup's wording says "this location",
    while these rows are a STATE (Step 18) or a DISTRICT (Step 19), so the service
    writes its own "this area" phrasing - see the comment directly above the
    message it returns. That behaviour is intentional and is what the brief asks
    for.

    So this now asserts the invariant the test actually exists to protect: the
    level is `unknown`, no factors are invented, and a message explains why. Pinning
    an exact sentence here would re-break the moment the wording is improved, which
    is the same mistake in a different place.
    """
    level = country_service._state_risk_from_samples(
        {"available": False, "message": "Water source information is unavailable for this location."},
        rain=None,
    )
    assert level["level"] == "unknown"
    assert level["label"] == "Insufficient data"
    # Nothing is invented: no risk factors are manufactured for a place with no data.
    assert level["factors"] == []
    # And the reason is stated, in the service's own wording.
    assert "Insufficient data" in level["message"]
    assert "no risk could be calculated" in level["message"]


def test_state_risk_matches_single_place_derivation():
    """The aggregation is the SAME function the single-place risk_level uses."""
    water = {"available": True, "types": ["tank water"]}
    rain = {"status": {"key": "none"}, "will_rain": False}
    assert country_service._state_risk_from_samples(water, rain) == location_service.risk_level(water, rain)
