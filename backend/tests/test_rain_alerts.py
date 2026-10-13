"""Tests for the Rainy Alerts endpoint - `GET /api/v1/locations/rain-alert`.

THE POINT OF THESE TESTS is that the STATE is derived, never hardcoded. Most of
them therefore use coordinates in states other than the one a previous version
would have assumed, and the assertions are about the SHAPE of the answer
(named state, real forecast, honest failure) rather than about any particular
number - a number would be a different answer tomorrow and the test would be
testing the weather rather than the code.
"""

import pytest

from app.constants import API_PREFIX

RAIN_ALERT = f"{API_PREFIX}/locations/rain-alert"

# Three states in two countries, deliberately including one that is NOT Tamil
# Nadu. A hardcoded state would pass a test written only for Tamil Nadu and fail
# here, which is the whole reason these coordinates were chosen.
BENGALURU = {"lat": 12.9716, "lon": 77.5946}      # Karnataka, India
CHENNAI = {"lat": 13.0827, "lon": 80.2707}        # Tamil Nadu, India
AUSTIN = {"lat": 30.2672, "lon": -97.7431}       # Texas, United States


def get(client, coords=None, **extra):
    params = dict(coords if coords is not None else BENGALURU, **extra)
    return client.get(RAIN_ALERT, query_string=params)


class TestRainAlertContract:
    """The endpoint's shape, and its refusals.

    These do NOT need the network: they assert what happens before any weather
    call is attempted, so they run on any machine.
    """

    def test_missing_coordinates_are_refused(self, client):
        """No default position, ever.

        Defaulting to some fixed point would be the hardcoding this screen exists
        to avoid: the forecast would look right and be about somewhere the
        visitor is not.
        """
        response = client.get(RAIN_ALERT)
        assert response.status_code == 422

    def test_a_non_numeric_coordinate_is_refused(self, client):
        assert client.get(RAIN_ALERT, query_string={"lat": "abc", "lon": "77"}).status_code == 422

    def test_a_latitude_outside_the_globe_is_refused(self, client):
        assert client.get(RAIN_ALERT, query_string={"lat": "999", "lon": "0"}).status_code == 422

    def test_it_needs_no_token(self, client):
        """The application is open, so this must fail on the ARGUMENT or the
        network, never on a missing credential. A 401 would mean a gate crept
        back in.
        """
        response = client.get(RAIN_ALERT, query_string={"lat": "abc", "lon": "x"})
        assert response.status_code != 401


class TestRainAlertResolution:
    """The live path. Skipped rather than failed when the network is out."""

    @pytest.fixture()
    def online(self, app):
        """Skip unless the live geocoders are reachable.

        These tests hit real Open-Meteo / Nominatim through the application, so
        they only make sense when those services answer. They are skipped rather
        than failed when the network is out -- an outage is an environment
        condition, not a code failure.
        """
        import requests

        try:
            requests.get("https://geocoding-api.open-meteo.com/v1/search", params={"name": "Chennai", "count": 1}, timeout=5)
        except Exception:  # noqa: BLE001 - no live geocoder reachable
            pytest.skip("No live geocoding service is reachable")

    def _result(self, client, coords):
        response = client.get(RAIN_ALERT, query_string=coords)
        if response.status_code == 404:
            # Honest "no state here" - acceptable, and not what these assert.
            pytest.skip("Coordinates could not be placed in a state")
        assert response.status_code == 200, response.get_json()
        return response.get_json()["data"]

    def test_the_state_is_derived_from_the_coordinates(self, client, online):
        """A Karnataka pin must not come back as Tamil Nadu."""
        data = self._result(client, BENGALURU)
        assert data["state"]
        assert "karnataka" in data["state"].lower()

    def test_a_different_state_gives_a_different_state(self, client, online):
        """The negative control the first test alone cannot provide."""
        data = self._result(client, AUSTIN)
        assert data["state"]
        assert "karnataka" not in data["state"].lower()
        assert "tamil" not in data["state"].lower()

    def test_the_place_names_the_area_and_country(self, client, online):
        data = self._result(client, CHENNAI)
        assert data["place"]["state"] or data["place"]["city"] or data["place"]["district"]
        assert data["country"]

    def test_the_forecast_is_present_and_shaped(self, client, online):
        """The three states the UI branches on, and real numbers behind them."""
        data = self._result(client, BENGALURU)
        weather = data["weather"]
        assert weather["status"]["key"] in ("none", "occurring", "expected_soon")
        assert isinstance(weather["days"], list) and weather["days"]
        # Every day carries a real measured figure, not None.
        assert all(isinstance(row["mm"], (int, float)) for row in weather["days"])

    def test_the_heavy_flag_is_backed_by_the_thresholds(self, client, online):
        """`heavy` may only be true when a figure actually crosses the line."""
        data = self._result(client, BENGALURU)
        weather = data["weather"]
        thresholds = weather["thresholds"]
        if weather["heavy"]:
            assert (
                weather["current_mm"] is not None
                and weather["current_mm"] >= thresholds["hourly_mm"]
            ) or any(
                row["mm"] >= thresholds["daily_mm"] for row in weather["days"][:2]
            )

    def test_the_source_and_the_time_are_reported(self, client, online):
        """A forecast with no provenance is not checkable, so both are returned."""
        data = self._result(client, BENGALURU)
        assert data["source"]
        assert data["generated_at"]

    def test_the_forecast_is_taken_at_the_state_centre(self, client, online):
        """Regional, not a reading at one doorstep.

        When a centre was resolved it must actually differ from the device's own
        point - otherwise the "state" claim is cosmetic and the screen is really
        reporting the weather at one coordinate.
        """
        data = self._result(client, BENGALURU)
        if data["forecast_at_state_centre"]:
            moved = (
                abs(data["forecast_lat"] - BENGALURU["lat"]) > 0.05
                or abs(data["forecast_lon"] - BENGALURU["lon"]) > 0.05
            )
            assert moved, "the forecast must not be taken at the device's own pin"

    def test_the_device_coordinates_are_not_echoed_back(self, client, online):
        """A response that hands the position back is a privacy leak.

        The screen never displays coordinates, and it could not even if the API
        returned them - but returning them would put them in a network log and
        in any client that did display them.
        """
        data = self._result(client, BENGALURU)
        blob = str(data)
        # The resolved place and the forecast centre are legitimately present;
        # the DEVICE'S OWN PIN is what must not be handed back as a `place`.
        place = data["place"]
        assert "lat" not in place and "lon" not in place
        assert str(BENGALURU["lat"]) not in str(place)
