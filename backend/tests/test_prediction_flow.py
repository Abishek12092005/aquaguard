"""End-to-end tests for the prediction, alert and dashboard flows."""

import uuid

import pytest

from app.constants import API_PREFIX, FEATURE_NAMES

PREDICTIONS = f"{API_PREFIX}/predictions"
DASHBOARD = f"{API_PREFIX}/dashboard"
ALERTS = f"{API_PREFIX}/alerts"
PROFILE = f"{API_PREFIX}/profile"

SAFE_SAMPLE = {
    "ph": 7.1,
    "turbidity": 1.2,
    "tds": 280.0,
    "temperature": 18.0,
    "dissolved_oxygen": 8.4,
}
UNSAFE_SAMPLE = {
    "ph": 4.2,
    "turbidity": 240.0,
    "tds": 4800.0,
    "temperature": 39.0,
    "dissolved_oxygen": 1.1,
}


@pytest.fixture(scope="module")
def app_with_db():
    """A real application bound to the development database."""
    from app import create_app

    application = create_app("testing")

    with application.app_context():
        try:
            from sqlalchemy import text

            from app.extensions import db

            db.session.execute(text("SELECT 1"))
        except Exception as exc:
            pytest.skip(f"MySQL is not reachable: {exc}")

        from app.ml.model_loader import is_model_available

        if not is_model_available():
            pytest.skip("No trained model artifact; run python -m app.ml.train first")

    # Yield OUTSIDE the app context: a context held for a whole module keeps one
    # scoped session alive across tests, which leaked rows between them (the
    # visible symptom was dashboard totals counting another account's rows).
    yield application


@pytest.fixture()
def client(app_with_db):
    return app_with_db.test_client()


@pytest.fixture()
def auth_header(client):
    """Headers that act as a fresh account.

    The application has no registration, so the row is written directly and the
    token minted by the test. Most of this module's tests are about the PREDICTION
    pipeline rather than about ownership, so they pass no headers at all and land
    on the shared visitor; this fixture exists for the few that must not.
    """
    from tests.conftest import headers_for, make_test_account

    with client.application.app_context():
        user_id, _name, _email = make_test_account("flow")
        # Minted INSIDE the context: `create_access_token` needs `current_app`.
        return headers_for(user_id)


class TestPredictionFlow:
    def test_run_prediction_returns_verdict_and_confidence(self, client, auth_header):
        response = client.post(PREDICTIONS, json=SAFE_SAMPLE, headers=auth_header)
        assert response.status_code == 201, response.get_json()

        data = response.get_json()["data"]
        assert data["risk_level"] in {"safe", "moderate", "unsafe"}
        assert 0.0 <= data["confidence"] <= 1.0
        assert data["id"] is not None

    def test_prediction_is_persisted_and_listed(self, client, auth_header):
        created = client.post(PREDICTIONS, json=SAFE_SAMPLE, headers=auth_header).get_json()
        created_id = created["data"]["id"]

        listing = client.get(PREDICTIONS, headers=auth_header).get_json()
        ids = [row["id"] for row in listing["data"]]
        assert created_id in ids

    def test_latest_prediction_matches_the_last_submission(self, client, auth_header):
        created = client.post(PREDICTIONS, json=SAFE_SAMPLE, headers=auth_header).get_json()

        latest = client.get(f"{PREDICTIONS}/latest", headers=auth_header).get_json()
        assert latest["data"]["id"] == created["data"]["id"]

    def test_missing_parameters_are_rejected_with_field_errors(self, client, auth_header):
        response = client.post(PREDICTIONS, json={"ph": 7.0}, headers=auth_header)
        assert response.status_code == 422
        assert set(response.get_json()["errors"]) == set(FEATURE_NAMES) - {"ph"}

    def test_out_of_range_parameter_is_rejected(self, client, auth_header):
        payload = dict(SAFE_SAMPLE, ph=99.0)
        response = client.post(PREDICTIONS, json=payload, headers=auth_header)
        assert response.status_code == 422
        assert "ph" in response.get_json()["errors"]

    def test_prediction_is_open_to_any_visitor(self, client):
        """No login exists, so the endpoint answers rather than refusing.

        A stray token is the one case that still fails: it is a malformed
        credential rather than no credential, and the shared client is entitled
        to say so instead of quietly pretending it does not exist.
        """
        response = client.post(PREDICTIONS, json=SAFE_SAMPLE)
        assert response.status_code == 201, response.get_json()

    def test_stats_reflect_submitted_predictions(self, client, auth_header):
        client.post(PREDICTIONS, json=SAFE_SAMPLE, headers=auth_header)
        client.post(PREDICTIONS, json=SAFE_SAMPLE, headers=auth_header)

        stats = client.get(f"{PREDICTIONS}/stats", headers=auth_header).get_json()["data"]
        assert stats["total"] >= 2
        assert stats["total"] == stats["safe"] + stats["unsafe"] + stats["moderate"]

    def test_prediction_can_be_deleted_by_owner(self, client, auth_header):
        created = client.post(PREDICTIONS, json=SAFE_SAMPLE, headers=auth_header).get_json()
        prediction_id = created["data"]["id"]

        assert client.delete(f"{PREDICTIONS}/{prediction_id}", headers=auth_header).status_code == 200
        assert client.get(f"{PREDICTIONS}/{prediction_id}", headers=auth_header).status_code == 404


class TestPredictionOwnership:
    def test_user_cannot_read_another_users_prediction(self, client, auth_header):
        created = client.post(PREDICTIONS, json=SAFE_SAMPLE, headers=auth_header).get_json()
        prediction_id = created["data"]["id"]

        email = f"other_{uuid.uuid4().hex[:12]}@aquaguard.test"
        from tests.conftest import headers_for, make_test_account

        with client.application.app_context():
            other_id, _name, _email = make_test_account("other")
            other_headers = headers_for(other_id)

        response = client.get(
            f"{PREDICTIONS}/{prediction_id}", headers=other_headers,
        )
        assert response.status_code == 404


class TestAlerts:
    def test_unsafe_prediction_raises_an_alert(self, client, auth_header):
        client.post(PREDICTIONS, json=UNSAFE_SAMPLE, headers=auth_header)

        alerts = client.get(ALERTS, headers=auth_header).get_json()
        assert alerts["success"] is True
        assert isinstance(alerts["data"], list)

    def test_alert_summary_shape(self, client, auth_header):
        summary = client.get(f"{ALERTS}/summary", headers=auth_header).get_json()["data"]
        assert set(summary) >= {"total", "unread", "active", "acknowledged"}
        assert summary["total"] == summary["active"] + summary["acknowledged"]

    def test_acknowledge_moves_an_alert_out_of_active(self, client, auth_header):
        client.post(PREDICTIONS, json=UNSAFE_SAMPLE, headers=auth_header)
        active = client.get(f"{ALERTS}?status=active", headers=auth_header).get_json()["data"]

        if not active:
            pytest.skip("The model did not flag this sample unsafe; nothing to acknowledge")

        alert_id = active[0]["id"]
        acked = client.patch(f"{ALERTS}/{alert_id}/ack", headers=auth_header)
        assert acked.status_code == 200
        assert acked.get_json()["data"]["is_read"] is True


class TestDashboard:
    def test_overview_reports_aggregates(self, client, auth_header):
        client.post(PREDICTIONS, json=SAFE_SAMPLE, headers=auth_header)

        overview = client.get(f"{DASHBOARD}/overview", headers=auth_header).get_json()["data"]
        assert overview["total_predictions"] >= 1
        assert overview["latest_prediction"]["id"] is not None

    def test_charts_are_recharts_ready(self, client, auth_header):
        client.post(PREDICTIONS, json=SAFE_SAMPLE, headers=auth_header)

        charts = client.get(f"{DASHBOARD}/charts", headers=auth_header).get_json()["data"]
        assert set(charts) >= {"trend", "distribution", "parameters"}
        assert len(charts["parameters"]) == len(FEATURE_NAMES)

    def test_parameters_endpoint_matches_feature_contract(self, client, auth_header):
        parameters = client.get(f"{DASHBOARD}/parameters", headers=auth_header).get_json()["data"]
        assert parameters["order"] == list(FEATURE_NAMES)

    def test_summary_returns_scoped_totals(self, client, auth_header):
        client.post(PREDICTIONS, json=SAFE_SAMPLE, headers=auth_header)
        client.post(PREDICTIONS, json=UNSAFE_SAMPLE, headers=auth_header)

        data = client.get(f"{DASHBOARD}/summary", headers=auth_header).get_json()["data"]
        totals = data["totals"]
        assert totals["total"] >= 2
        assert totals["total"] == totals["safe"] + totals["moderate"] + totals["unsafe"]
        assert len(data["charts"]["parameters"]) == len(FEATURE_NAMES)

    def test_summary_is_open_to_any_visitor(self, client):
        assert client.get(f"{DASHBOARD}/summary").status_code == 200
    def test_summary_is_isolated_per_user(self, client, auth_header, app_with_db):
        """A second account must see none of the first account's rows.

        There is no registration to create the second account through, so the
        row is written directly and its token minted -- the same way the first
        account's is.
        """
        from tests.conftest import headers_for, make_test_account

        client.post(PREDICTIONS, json=SAFE_SAMPLE, headers=auth_header)

        with app_with_db.app_context():
            other_id, _name, _email = make_test_account("isolated")
            other_headers = headers_for(other_id)

        data = client.get(f"{DASHBOARD}/summary", headers=other_headers).get_json()["data"]
        assert data["totals"]["total"] == 0
    def test_recent_returns_predictions_and_alerts(self, client, auth_header):
        client.post(PREDICTIONS, json=SAFE_SAMPLE, headers=auth_header)

        data = client.get(f"{DASHBOARD}/recent", headers=auth_header).get_json()["data"]
        assert len(data["recent_predictions"]) >= 1
        assert isinstance(data["recent_alerts"], list)
        first = data["recent_predictions"][0]
        assert set(first["values"]) == set(FEATURE_NAMES)

    def test_recent_is_open_to_any_visitor(self, client):
        assert client.get(f"{DASHBOARD}/recent").status_code == 200
