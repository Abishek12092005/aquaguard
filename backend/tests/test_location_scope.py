"""Location access scope: the admin restriction and its backend enforcement.

Two properties matter, and they are tested separately:

  1. The console can STORE a state or country scope, and refuses a
     half-configured one.
  2. Every location lookup ENFORCES the scope on the server, so a client that
     ignores the frontend is still refused. The tests below therefore call the
     API directly with a user token, which is exactly what a tampering client
     would do.

The place data is stubbed at the service boundary rather than fetched, so these
tests do not touch the network.
"""

import uuid

import pytest

from app.constants import API_PREFIX

ADMIN = "/api/admin"
AUTH = f"{API_PREFIX}/auth"
LOCATIONS = f"{API_PREFIX}/locations"

SCOPE_MESSAGE = (
    "Water quality analysis is currently available only within the configured location area."
)

# A few resolved places, in the shape the geocoder returns.
TN_PLACE = {"name": "Karaikudi", "state": "Tamil Nadu", "country": "India", "lat": 10.07, "lon": 78.78}
KA_PLACE = {"name": "Bengaluru", "state": "Karnataka", "country": "India", "lat": 12.97, "lon": 77.59}
US_PLACE = {"name": "Austin", "state": "Texas", "country": "United States", "lat": 30.27, "lon": -97.74}


def make_account(client, label="u", role=None):
    """Create a distinct account and return its headers.

    The application has no registration, so the row is written directly and the
    token minted by the test — production issues no user tokens, because the
    console authenticates with its own credential rather than an account.
    """
    from tests.conftest import headers_for, make_test_account

    with client.application.app_context():
        user_id, _name, email = make_test_account(f"scope_{label}", role or "user")
        # Minted INSIDE the context: `create_access_token` needs `current_app`.
        return {"headers": headers_for(user_id), "id": user_id, "email": email}


@pytest.fixture()
def admin(client):
    return make_account(client, "admin", role="admin")


@pytest.fixture()
def user(client):
    return make_account(client, "user")


@pytest.fixture()
def stub_place(monkeypatch):
    """Let a test say what the geocoder would return for a query."""

    def _install(place):
        from app.services import location_service

        # The VILLAGE pre-check is stubbed too: it makes its own provider call
        # against the real network, which a unit test must never do. Returning
        # None from it means "not a village search" -- the normal path.
        monkeypatch.setattr(
            location_service, "village_disambiguation", lambda query: None
        )
        monkeypatch.setattr(location_service, "resolve", lambda query, limit=1: dict(place))
        monkeypatch.setattr(location_service, "reverse", lambda lat, lon: dict(place))

    return _install


# ---------------------------------------------------------------------------
# Storing the scope (admin console)
# ---------------------------------------------------------------------------
class TestLocationScopeSetting:
    def test_defaults_to_off(self, client, admin, unlock_console):
        """The scope is stored server-side, so reading it needs the console open."""
        unlock_console(admin["headers"])
        data = client.get(f"{ADMIN}/location-scope", headers=admin["headers"]).get_json()["data"]
        assert data["mode"] is None

    def test_a_state_scope_can_be_set(self, client, admin, unlock_console):
        unlock_console(admin["headers"])
        response = client.put(
            f"{ADMIN}/location-scope",
            json={"mode": "state", "state": "Tamil Nadu"},
            headers=admin["headers"],
        )
        assert response.status_code == 200, response.get_json()
        data = response.get_json()["data"]
        assert data["mode"] == "state"
        assert data["state"] == "Tamil Nadu"
        # A STATE scope KEEPS its country (Prompt 13 requirement 2): "Kerala"
        # exists in more than one country, so discarding the country would throw
        # away the evidence that made the stored state unambiguous.

    def test_a_country_scope_can_be_set(self, client, admin, unlock_console):
        unlock_console(admin["headers"])
        response = client.put(
            f"{ADMIN}/location-scope",
            json={"mode": "country", "country": "India"},
            headers=admin["headers"],
        )
        assert response.status_code == 200, response.get_json()
        data = response.get_json()["data"]
        assert data["mode"] == "country"
        assert data["state"] is None
        assert data["country"] == "India"

    def test_a_state_scope_without_a_state_is_refused(self, client, admin, unlock_console):
        unlock_console(admin["headers"])
        response = client.put(
            f"{ADMIN}/location-scope", json={"mode": "state"}, headers=admin["headers"]
        )
        assert response.status_code == 422, response.get_json()

    def test_an_unknown_mode_is_refused(self, client, admin, unlock_console):
        unlock_console(admin["headers"])
        response = client.put(
            f"{ADMIN}/location-scope",
            json={"mode": "galaxy", "state": "X"},
            headers=admin["headers"],
        )
        assert response.status_code == 422, response.get_json()

    def test_the_scope_can_be_cleared(self, client, admin, unlock_console):
        unlock_console(admin["headers"])
        client.put(
            f"{ADMIN}/location-scope",
            json={"mode": "state", "state": "Tamil Nadu"},
            headers=admin["headers"],
        )
        response = client.put(
            f"{ADMIN}/location-scope", json={"mode": None}, headers=admin["headers"]
        )
        assert response.status_code == 200
        assert response.get_json()["data"]["mode"] is None

    def test_a_non_admin_cannot_read_or_change_the_scope(self, client, user, unlock_console):
        assert client.get(f"{ADMIN}/location-scope", headers=user["headers"]).status_code == 403
        assert (
            client.put(
                f"{ADMIN}/location-scope",
                json={"mode": "state", "state": "Tamil Nadu"},
                headers=user["headers"],
            ).status_code
            == 403
        )


# ---------------------------------------------------------------------------
# Enforcing the scope (every location lookup, on the server)
# ---------------------------------------------------------------------------
class TestScopeEnforcement:
    def _set_scope(self, client, admin, unlock_console, **scope):
        unlock_console(admin["headers"])
        response = client.put(f"{ADMIN}/location-scope", json=scope, headers=admin["headers"])
        assert response.status_code == 200, response.get_json()

    def test_state_scope_allows_a_place_in_that_state(
        self, client, admin, user, unlock_console, stub_place
    ):
        self._set_scope(client, admin, unlock_console, mode="state", state="Tamil Nadu")
        stub_place(TN_PLACE)
        response = client.get(f"{LOCATIONS}/resolve?q=Karaikudi", headers=user["headers"])
        assert response.status_code == 200, response.get_json()
        assert response.get_json()["data"]["name"] == "Karaikudi"

    def test_state_scope_blocks_a_place_in_another_state(
        self, client, admin, user, unlock_console, stub_place
    ):
        self._set_scope(client, admin, unlock_console, mode="state", state="Tamil Nadu")
        stub_place(KA_PLACE)
        response = client.get(f"{LOCATIONS}/resolve?q=Bengaluru", headers=user["headers"])
        assert response.status_code == 403, response.get_json()
        assert response.get_json()["message"] == SCOPE_MESSAGE

    def test_country_scope_allows_any_place_in_that_country(
        self, client, admin, user, unlock_console, stub_place
    ):
        self._set_scope(client, admin, unlock_console, mode="country", country="India")
        stub_place(KA_PLACE)
        assert (
            client.get(f"{LOCATIONS}/resolve?q=Bengaluru", headers=user["headers"]).status_code
            == 200
        )

    def test_country_scope_blocks_a_place_outside_that_country(
        self, client, admin, user, unlock_console, stub_place
    ):
        self._set_scope(client, admin, unlock_console, mode="country", country="India")
        stub_place(US_PLACE)
        response = client.get(f"{LOCATIONS}/resolve?q=Austin", headers=user["headers"])
        assert response.status_code == 403
        assert response.get_json()["message"] == SCOPE_MESSAGE

    def test_country_matching_is_not_a_substring(
        self, client, admin, user, unlock_console, stub_place
    ):
        """\"India\" must not match \"Indianapolis\" — the classic substring bug."""
        self._set_scope(client, admin, unlock_console, mode="country", country="India")
        stub_place({"name": "Indianapolis", "state": "Indiana", "country": "United States"})
        response = client.get(f"{LOCATIONS}/resolve?q=Indianapolis", headers=user["headers"])
        assert response.status_code == 403, "a substring match would have wrongly allowed this"

    def test_reverse_is_also_enforced(
        self, client, admin, user, unlock_console, stub_place
    ):
        """'Use my location' must not bypass the restriction."""
        self._set_scope(client, admin, unlock_console, mode="state", state="Tamil Nadu")
        stub_place(US_PLACE)
        response = client.get(f"{LOCATIONS}/reverse?lat=30.27&lon=-97.74", headers=user["headers"])
        assert response.status_code == 403
        assert response.get_json()["message"] == SCOPE_MESSAGE

    def test_no_scope_allows_everything(self, client, user, stub_place):
        stub_place(US_PLACE)
        assert (
            client.get(f"{LOCATIONS}/resolve?q=Austin", headers=user["headers"]).status_code
            == 200
        )

    def test_an_unauthenticated_lookup_is_open(self, client, stub_place, monkeypatch):
        """The application is open: no login is required for a lookup."""
        stub_place(TN_PLACE)
        assert client.get(f"{LOCATIONS}/resolve?q=Karaikudi").status_code == 200


# ---------------------------------------------------------------------------
# Use My Location (device coordinates -> resolved place)
# ---------------------------------------------------------------------------
class TestUseMyLocation:
    """The reverse lookup that backs \"Use My Location\".

    The browser sends coordinates; the server answers with a PLACE. These tests
    assert the place fields the UI fills in, and that the same admin scope gate
    applies to a device fix as to a typed search.
    """

    def _reverse_body(self, **address):
        return {"address": address}

    def test_reverse_returns_every_displayed_field(self, client, user, monkeypatch):
        from app.services import location_service

        monkeypatch.setattr(
            location_service,
            "_get",
            lambda url, params: {
                "display_name": "Karaikudi, Sivaganga, Tamil Nadu, India",
                "address": {
                    "city": "Karaikudi",
                    "county": "Sivaganga",
                    "state": "Tamil Nadu",
                    "country": "India",
                    "postcode": "630001",
                },
            },
        )
        response = client.get(f"{LOCATIONS}/reverse?lat=10.0667&lon=78.7833", headers=user["headers"])
        assert response.status_code == 200, response.get_json()

        data = response.get_json()["data"]
        assert data["name"] == "Karaikudi"
        assert data["city"] == "Karaikudi"
        assert data["district"] == "Sivaganga"
        assert data["state"] == "Tamil Nadu"
        assert data["country"] == "India"
        assert data["pincode"] == "630001"
        # The string that goes straight into the search box.
        assert data["display_name"] == "Karaikudi, Tamil Nadu"

    def test_reverse_rejects_bad_coordinates(self, client, user):
        assert client.get(f"{LOCATIONS}/reverse?lat=abc&lon=2", headers=user["headers"]).status_code == 422
        assert client.get(f"{LOCATIONS}/reverse?lon=2", headers=user["headers"]).status_code == 422

    def test_reverse_of_an_unresolvable_point_is_a_404(self, client, user, monkeypatch):
        from app.services import location_service

        monkeypatch.setattr(location_service, "_get", lambda url, params: None)
        response = client.get(f"{LOCATIONS}/reverse?lat=0&lon=0", headers=user["headers"])
        assert response.status_code == 404

    def test_device_fix_is_subject_to_the_scope(
        self, client, admin, user, unlock_console, monkeypatch
    ):
        from app.services import location_service

        unlock_console(admin["headers"])
        client.put(
            f"{ADMIN}/location-scope",
            json={"mode": "state", "state": "Tamil Nadu"},
            headers=admin["headers"],
        )
        monkeypatch.setattr(
            location_service,
            "_get",
            lambda url, params: {"address": {"city": "Bengaluru", "state": "Karnataka", "country": "India"}},
        )
        response = client.get(f"{LOCATIONS}/reverse?lat=12.97&lon=77.59", headers=user["headers"])
        assert response.status_code == 403
        assert response.get_json()["message"] == SCOPE_MESSAGE

    def test_use_my_location_is_open(self, client, stub_place, monkeypatch):
        """A location lookup is a geocoding READ, not a gated action.

        The application is open: there is no user login, and refusing the first
        thing a visitor asks for would break the product. `location_routes.py`
        documents exactly this, so the old expectation (401 without a session)
        described a requirement that no longer exists.
        """
        from app.services import location_service

        monkeypatch.setattr(
            location_service,
            "_get",
            lambda url, params: {"address": {"city": "Karaikudi", "state": "Tamil Nadu", "country": "India"}},
        )
        response = client.get(f"{LOCATIONS}/reverse?lat=10.07&lon=78.78")
        assert response.status_code == 200, response.get_json()


# ---------------------------------------------------------------------------
# Water source identification
# ---------------------------------------------------------------------------
class TestWaterSource:
    """The water-source identification layer.

    The whole point of these tests is the HONESTY requirement: a source type is
    only reported from real mapped data, and a location with no mapped water is
    reported as unavailable rather than assigned a plausible-sounding source.
    """

    def _stub(self, monkeypatch, elements):
        from app.services import location_service

        # Stub the OVERPASS layer, not `_get`: the query is a POST, so `_get` is
        # not on this path and stubbing it would still hit the real network.
        monkeypatch.setattr(
            location_service,
            "_overpass",
            lambda query: {"elements": elements},
        )

    def test_all_categories_are_declared(self):
        from app.services.location_service import WATER_TYPES

        assert set(WATER_TYPES) == {
            "river water",
            "lake water",
            "pond water",
            "surface water",
            "tank water",
            "piped water",
            "rain water",
            "municipal water source",
            "ground water",
            "borewell water",
            "well water",
        }

    def test_a_real_source_is_reported_with_its_own_name_and_distance(
        self, client, user, monkeypatch
    ):
        self._stub(
            monkeypatch,
            [
                # Right AT the point (within EXACT_SOURCE_RADIUS_M), so it is the
                # location's own source and not merely a nearby one.
                {"type": "node", "lat": 10.0667, "lon": 78.7833,
                 "tags": {"man_made": "water_well", "name": "Sambai Oothu"}},
            ],
        )
        from app.services import location_service

        monkeypatch.setattr(
            location_service, "reverse",
            lambda lat, lon: {"name": "Karaikudi", "state": "Tamil Nadu", "country": "India",
                              "lat": lat, "lon": lon},
        )
        response = client.get(f"{LOCATIONS}/water?lat=10.0667&lon=78.7833", headers=user["headers"])
        assert response.status_code == 200, response.get_json()
        data = response.get_json()["data"]
        water = data["water"]
        assert water["available"] is True
        assert water["primary"] == "well water"
        assert water["nearby"][0]["name"] == "Sambai Oothu"
        assert water["nearby"][0]["distance_km"] >= 0

    def test_no_mapped_water_is_unavailable_and_invents_nothing(
        self, client, user, monkeypatch
    ):
        self._stub(monkeypatch, [])
        from app.services import location_service

        monkeypatch.setattr(
            location_service, "reverse",
            lambda lat, lon: {"name": "Somewhere", "state": "Tamil Nadu", "country": "India",
                              "lat": lat, "lon": lon},
        )
        response = client.get(f"{LOCATIONS}/water?lat=1&lon=1", headers=user["headers"])
        assert response.status_code == 200, response.get_json()
        water = response.get_json()["data"]["water"]
        assert water["available"] is False
        assert water["primary"] is None
        assert water["nearby"] == []
        assert water["message"] == "Water source information is unavailable for this location."

    def test_an_unnamed_feature_gets_no_fabricated_name(self, monkeypatch):
        self._stub(monkeypatch, [{"type": "way", "center": {"lat": 10.1, "lon": 78.8},
                                  "tags": {"water": "pond"}}])
        from app.services import location_service

        ctx = location_service.water_context({"lat": 10.0, "lon": 78.7})
        assert ctx["nearby"][0]["named"] is False
        assert ctx["nearby"][0]["name"].startswith("Unnamed")
        # It is never given a real-looking place name.
        assert "Unnamed" in ctx["nearby"][0]["name"]

    def test_water_lookup_is_subject_to_the_scope(
        self, client, admin, user, unlock_console, monkeypatch
    ):
        from app.services import location_service

        unlock_console(admin["headers"])
        client.put(
            f"{ADMIN}/location-scope",
            json={"mode": "state", "state": "Tamil Nadu"},
            headers=admin["headers"],
        )
        monkeypatch.setattr(
            location_service, "reverse",
            lambda lat, lon: {"name": "Bengaluru", "state": "Karnataka", "country": "India",
                              "lat": lat, "lon": lon},
        )
        response = client.get(f"{LOCATIONS}/water?lat=12.97&lon=77.59", headers=user["headers"])
        assert response.status_code == 403
        assert response.get_json()["message"] == SCOPE_MESSAGE

    def test_water_lookup_is_open(self, client, monkeypatch):
        """A water lookup is a geocoding read; the app has no login to require."""
        self._stub(monkeypatch, [])
        from app.services import location_service

        monkeypatch.setattr(
            location_service, "reverse",
            lambda lat, lon: {"name": "Somewhere", "state": "Tamil Nadu", "country": "India",
                              "lat": lat, "lon": lon},
        )
        monkeypatch.setattr(
            location_service, "search",
            lambda query, limit=6, **kw: [{"name": "Somewhere", "state": "Tamil Nadu",
                                          "country": "India", "lat": 10.0, "lon": 78.0}],
        )
        response = client.get(f"{LOCATIONS}/water?lat=10&lon=78")
        assert response.status_code == 200
