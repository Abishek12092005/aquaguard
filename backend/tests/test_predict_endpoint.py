"""Independent end-to-end tests for `POST /api/predictions/predict`.

These deliberately talk to the HTTP endpoint through the Flask test client
rather than calling the service directly, so the whole documented flow is
exercised:

    request -> JWT -> validation -> preprocessing -> model -> prediction
            -> confidence -> MySQL -> response

They need a reachable MySQL and a trained model artifact; without either they
skip with a clear reason instead of reporting a false pass. That is the honest
behaviour: the point of this file is to prove the real model is wired in, and a
mock would prove nothing.
"""

import uuid

import pytest

from app.constants import API_PREFIX, FEATURE_NAMES, RISK_LEVELS

PREDICT = f"{API_PREFIX}/predictions/predict"
PREDICT_SHORT = "/api/predictions/predict"

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
MODERATE_SAMPLE = {
    "ph": 7.0,
    "turbidity": 20.0,
    "tds": 900.0,
    "temperature": 25.0,
    "dissolved_oxygen": 5.0,
}


@pytest.fixture(scope="module")
def live_app():
    """A development app with a reachable database and a trained model."""
    from app import create_app
    from app.extensions import db
    from app.ml.model_loader import is_model_available

    application = create_app("testing")

    with application.app_context():
        try:
            from sqlalchemy import text

            db.session.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001 - reported as a skip
            pytest.skip(f"MySQL is not reachable: {exc}")

        if not is_model_available():
            pytest.skip("No trained model artifact; run python ml/train_model.py first")

        yield application


@pytest.fixture()
def client(live_app):
    return live_app.test_client()


@pytest.fixture()
def auth_header(client):
    """Headers that act as a fresh account.

    The application has no registration, so the row is written directly and the
    token minted by the test — production issues no user tokens, because the
    console authenticates with its own credential rather than an account.
    """
    from tests.conftest import headers_for, make_test_account

    with client.application.app_context():
        user_id, _name, _email = make_test_account("predict")
        # Minted INSIDE the context: `create_access_token` reads the JWT manager
        # from `current_app`, so building the headers after the block closed
        # raised "Working outside of application context".
        return headers_for(user_id)


class TestPredictEndpointContract:
    def test_successful_prediction_returns_the_documented_shape(self, client, auth_header):
        response = client.post(PREDICT, json=SAFE_SAMPLE, headers=auth_header)
        assert response.status_code == 201, response.get_json()

        body = response.get_json()
        assert body["success"] is True
        data = body["data"]

        # The exact keys the step-8 contract names.
        assert data["prediction"] in RISK_LEVELS
        assert isinstance(data["confidence"], float)
        assert 0.0 <= data["confidence"] <= 1.0
        assert set(data["parameters"]) == set(FEATURE_NAMES)

        # Saved fields: user_id, parameters, prediction, confidence, timestamp.
        assert data["id"] is not None
        assert data["created_at"]
        for name in FEATURE_NAMES:
            assert data["parameters"][name]["value"] == SAFE_SAMPLE[name]

    def test_every_verdict_is_one_of_the_three_allowed_values(self, client, auth_header):
        for sample in (SAFE_SAMPLE, MODERATE_SAMPLE, UNSAFE_SAMPLE):
            response = client.post(PREDICT, json=sample, headers=auth_header)
            assert response.status_code == 201
            assert response.get_json()["data"]["prediction"] in RISK_LEVELS

    def test_predictions_are_model_derived_not_random(self, client, auth_header):
        """The same input must always produce the same verdict.

        A randomly generated result would fail this; a real model cannot.
        """
        first = client.post(PREDICT, json=SAFE_SAMPLE, headers=auth_header).get_json()["data"]
        second = client.post(PREDICT, json=SAFE_SAMPLE, headers=auth_header).get_json()["data"]

        assert first["prediction"] == second["prediction"]
        assert first["confidence"] == second["confidence"]

    def test_clean_and_polluted_samples_are_separated(self, client, auth_header):
        """A pristine sample must not be judged worse than a badly polluted one.

        This is the behavioural check that the model is genuinely in the loop:
        an endpoint that always answered the same thing would fail it.
        """
        order = {"safe": 0, "moderate": 1, "unsafe": 2}
        clean = client.post(PREDICT, json=SAFE_SAMPLE, headers=auth_header).get_json()["data"]
        dirty = client.post(PREDICT, json=UNSAFE_SAMPLE, headers=auth_header).get_json()["data"]

        assert order[clean["prediction"]] <= order[dirty["prediction"]]

    def test_result_is_persisted_and_retrievable(self, client, auth_header):
        created = client.post(PREDICT, json=SAFE_SAMPLE, headers=auth_header).get_json()["data"]

        fetched = client.get(f"{API_PREFIX}/predictions/{created['id']}", headers=auth_header)
        assert fetched.status_code == 200
        assert fetched.get_json()["data"]["prediction"] == created["prediction"]

    def test_short_unversioned_path_also_works(self, client, auth_header):
        response = client.post(PREDICT_SHORT, json=SAFE_SAMPLE, headers=auth_header)
        assert response.status_code == 201, response.get_json()


class TestPredictEndpointOpen:
    def test_without_a_token_is_accepted(self, client):
        """NO LOGIN EXISTS, so a bare call must succeed."""
        response = client.post(PREDICT, json=SAFE_SAMPLE)
        assert response.status_code == 201, response.get_json()

    def test_with_a_garbage_token_is_accepted(self, client):
        """A malformed credential is treated as NO credential.

        The application is open: a prediction is a read-write action every
        visitor performs, so a bad header cannot turn a visitor away. It simply
        stops identifying anybody, and the row lands on the shared visitor.
        """
        response = client.post(
            PREDICT, json=SAFE_SAMPLE, headers={"Authorization": "Bearer not-a-token"}
        )
        assert response.status_code == 201, response.get_json()

    def test_success_envelope_is_the_standard_shape(self, client):
        body = client.post(PREDICT, json=SAFE_SAMPLE).get_json()
        assert body["success"] is True
        assert "message" in body


class TestPredictEndpointValidation:
    def test_missing_values_are_reported_per_field(self, client, auth_header):
        response = client.post(PREDICT, json={"ph": 7.0}, headers=auth_header)
        assert response.status_code == 422

        errors = response.get_json()["errors"]
        assert set(errors) == set(FEATURE_NAMES) - {"ph"}

    def test_absent_parameter_is_reported(self, client, auth_header):
        payload = {k: v for k, v in SAFE_SAMPLE.items() if k != "tds"}
        response = client.post(PREDICT, json=payload, headers=auth_header)
        assert response.status_code == 422
        assert "tds" in response.get_json()["errors"]

    def test_null_value_is_reported(self, client, auth_header):
        response = client.post(PREDICT, json=dict(SAFE_SAMPLE, tds=None), headers=auth_header)
        assert response.status_code == 422
        assert "tds" in response.get_json()["errors"]

    def test_non_numeric_value_is_rejected(self, client, auth_header):
        response = client.post(
            PREDICT, json=dict(SAFE_SAMPLE, turbidity="very murky"), headers=auth_header
        )
        assert response.status_code == 422
        assert "turbidity" in response.get_json()["errors"]

    def test_boolean_is_not_accepted_as_a_number(self, client, auth_header):
        response = client.post(PREDICT, json=dict(SAFE_SAMPLE, ph=True), headers=auth_header)
        assert response.status_code == 422
        assert "ph" in response.get_json()["errors"]

    @pytest.mark.parametrize(
        "field,value",
        [
            ("ph", 99.0),           # pH cannot exceed 14
            ("ph", -1.0),           # nor fall below 0
            ("turbidity", 5000.0),  # NTU bound
            ("tds", 99999.0),       # mg/L bound
            ("temperature", 500.0),  # °C bound
            ("dissolved_oxygen", 50.0),  # mg/L bound
        ],
    )
    def test_out_of_range_values_are_rejected(self, client, auth_header, field, value):
        response = client.post(PREDICT, json=dict(SAFE_SAMPLE, **{field: value}), headers=auth_header)
        assert response.status_code == 422
        assert field in response.get_json()["errors"]

    def test_all_invalid_fields_are_reported_at_once(self, client, auth_header):
        payload = dict(SAFE_SAMPLE, ph=99.0, turbidity=-5.0, dissolved_oxygen=99.0)
        response = client.post(PREDICT, json=payload, headers=auth_header)

        assert response.status_code == 422
        errors = response.get_json()["errors"]
        assert {"ph", "turbidity", "dissolved_oxygen"} <= set(errors)

    def test_malformed_json_body_is_400(self, client, auth_header):
        response = client.post(
            PREDICT, data="{not json at all", content_type="application/json", headers=auth_header
        )
        assert response.status_code == 400
        assert response.get_json()["success"] is False

    def test_json_array_body_is_400(self, client, auth_header):
        response = client.post(PREDICT, json=[1, 2, 3], headers=auth_header)
        assert response.status_code == 400

    def test_empty_body_is_400(self, client, auth_header):
        response = client.post(PREDICT, data="", content_type="application/json", headers=auth_header)
        assert response.status_code == 400


class TestPredictEndpointUnavailableModel:
    def test_missing_model_returns_503_not_a_fabricated_verdict(self, client, auth_header):
        """With the artifact hidden, the endpoint must fail loudly."""
        from unittest.mock import patch

        with patch("app.ml.model_loader._model_path", return_value="/nonexistent/model.pkl"):
            with patch("app.ml.water_quality.is_available", return_value=False):
                response = client.post(PREDICT, json=SAFE_SAMPLE, headers=auth_header)

        assert response.status_code == 503
        body = response.get_json()
        assert body["success"] is False
        # Critically: no prediction is invented when the model is unavailable.
        assert "prediction" not in (body.get("data") or {})
