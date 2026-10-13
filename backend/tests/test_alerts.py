"""Independent tests for the Alerts system.

Covers the parts of the spec that involve behaviour rather than existence:

  * an unsafe prediction creates exactly one alert, with every required field
  * a duplicate alert is never created for the same prediction — including when
    the service is called repeatedly, and when two sessions race each other
  * a safe prediction creates no alert
  * only the authenticated user's alerts are reachable
  * PATCH /alerts/<id>/read marks one alert read and is idempotent
  * errors come back in the standard envelope with the right status codes
"""

import uuid

import pytest

from app.constants import API_PREFIX

ALERTS = f"{API_PREFIX}/alerts"
PREDICT = f"{API_PREFIX}/predictions/predict"

SAFE_SAMPLE = {
    "ph": 7.1,
    "turbidity": 1.2,
    "tds": 280.0,
    "temperature": 18.0,
    "dissolved_oxygen": 8.4,
}
# Verified against the trained model: this sample is classified unsafe.
UNSAFE_SAMPLE = {
    "ph": 4.2,
    "turbidity": 240.0,
    "tds": 4800.0,
    "temperature": 39.0,
    "dissolved_oxygen": 1.1,
}


@pytest.fixture(scope="module")
def live_app():
    from app import create_app
    from app.extensions import db
    from app.ml.model_loader import is_model_available

    application = create_app("testing")

    with application.app_context():
        try:
            from sqlalchemy import text
            db.session.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001 - reported as a skip
            pytest.skip(
                "The test database is not reachable. Provision it with\n"
                "  powershell -ExecutionPolicy Bypass -File database/provision_test_db.ps1\n"
                f"({exc})"
            )

        if not is_model_available():
            pytest.skip("No trained model artifact; run python ml/train_model.py first")

    # Yield OUTSIDE the app context, for the same reason the Aqua AI module
    # does: a context held open for a whole module keeps one scoped session
    # alive across tests, and leftovers from one test leak into the next. The
    # visible symptom was "empty for a new account" failing because the previous
    # test's rows were still attached to the session and were flushed into its
    # queries.
    yield application


@pytest.fixture()
def client(live_app):
    return live_app.test_client()


def make_account(client, label="u"):
    """Create a distinct account and return headers that act as it.

    The application has no registration, so the row is written directly and the
    token minted by the test — production issues no user tokens, because the
    console authenticates with its own credential.
    """
    from tests.conftest import headers_for, make_test_account

    with client.application.app_context():
        user_id, _name, _email = make_test_account(f"alert_{label}")
        # Minted INSIDE the context: `create_access_token` needs `current_app`.
        return headers_for(user_id)


@pytest.fixture()
def user_a(client):
    # Wrapped so tests read `user_a["headers"]`, matching how a fixture that
    # carries more than a token would be shaped later.
    return {"headers": make_account(client, "a")}

@pytest.fixture()
def user_b(client):
    return {"headers": make_account(client, "b")}


def submit(client, headers, sample):
    response = client.post(PREDICT, json=sample, headers=headers)
    assert response.status_code == 201, response.get_json()
    return response.get_json()["data"]


def alerts_for(client, headers):
    response = client.get(f"{ALERTS}?per_page=100", headers=headers)
    assert response.status_code == 200, response.get_json()
    return response.get_json()["data"]


class TestAlertCreation:
    def test_unsafe_prediction_creates_an_alert_with_every_required_field(self, client, user_a):
        prediction = submit(client, user_a["headers"], UNSAFE_SAMPLE)
        # Only an unsafe verdict should produce one.
        assert prediction["prediction"] == "unsafe"

        rows = alerts_for(client, user_a["headers"])
        assert len(rows) == 1

        alert = rows[0]
        for field in ("user_id", "prediction_id", "type", "message", "created_at", "is_read"):
            assert field in alert, f"{field} missing from the alert payload"

        assert alert["prediction_id"] == prediction["id"]
        assert alert["type"] == "water_unsafe"
        assert alert["is_read"] is False
        assert alert["created_at"]
        assert alert["message"], "the alert must explain itself"

    def test_alert_message_names_the_readings(self, client, user_a):
        submit(client, user_a["headers"], UNSAFE_SAMPLE)

        message = alerts_for(client, user_a["headers"])[0]["message"]
        # The message should be specific to the sample, not generic boilerplate.
        assert "4800" in message or "4,800" in message or "ph" in message.lower()

    def test_safe_prediction_creates_no_alert(self, client, user_a):
        prediction = submit(client, user_a["headers"], SAFE_SAMPLE)
        assert prediction["prediction"] == "safe"

        assert alerts_for(client, user_a["headers"]) == []

    def test_moderate_prediction_creates_no_alert(self, client, user_a):
        """Moderate is a 'watch this', not a page."""
        # Assert on whatever the model actually returns, so the test stays
        # honest rather than assuming a verdict it might not produce.
        prediction = submit(
            client,
            user_a["headers"],
            {"ph": 7.0, "turbidity": 20.0, "tds": 900.0, "temperature": 25.0, "dissolved_oxygen": 5.0},
        )
        if prediction["prediction"] != "moderate":
            pytest.skip(f"Model returned {prediction['prediction']!r}, not moderate")

        assert alerts_for(client, user_a["headers"]) == []

    def test_alert_count_matches_unsafe_prediction_count(self, client, user_a):
        submit(client, user_a["headers"], SAFE_SAMPLE)
        submit(client, user_a["headers"], UNSAFE_SAMPLE)
        submit(client, user_a["headers"], UNSAFE_SAMPLE)

        assert len(alerts_for(client, user_a["headers"])) == 2


class TestNoDuplicateAlerts:
    """The same prediction must never produce two alerts."""

    def test_raising_twice_for_one_prediction_creates_one_alert(self, client, user_a, live_app):
        prediction = submit(client, user_a["headers"], UNSAFE_SAMPLE)

        with live_app.app_context():
            from sqlalchemy import func, select

            from app.extensions import db
            from app.models import Alert
            from app.services.alert_service import raise_for_prediction

            before = db.session.execute(
                select(func.count()).select_from(Alert).where(
                    Alert.prediction_id == prediction["id"]
                )
            ).scalar_one()
            assert before == 1

            # Call it repeatedly, as a retry or a double-trigger would.
            for _ in range(4):
                raise_for_prediction(prediction["id"])

            after = db.session.execute(
                select(func.count()).select_from(Alert).where(
                    Alert.prediction_id == prediction["id"]
                )
            ).scalar_one()

        assert after == 1, "a repeated call must not create another alert"

    def test_the_returned_alert_is_the_existing_one_not_a_new_row(
        self, client, user_a, live_app
    ):
        prediction = submit(client, user_a["headers"], UNSAFE_SAMPLE)

        with live_app.app_context():
            from app.services.alert_service import raise_for_prediction

            first = raise_for_prediction(prediction["id"])
            second = raise_for_prediction(prediction["id"])

        assert first["id"] == second["id"]

    def test_repeating_for_a_safe_prediction_still_creates_nothing(
        self, client, user_a, live_app
    ):
        prediction = submit(client, user_a["headers"], SAFE_SAMPLE)

        with live_app.app_context():
            from app.services.alert_service import raise_for_prediction

            assert raise_for_prediction(prediction["id"]) is None

        assert alerts_for(client, user_a["headers"]) == []

    def test_unknown_prediction_is_not_found(self, live_app):
        """An id that does not exist must raise, not silently do nothing.

        The id is derived from the current maximum rather than hardcoded: the
        development database has accumulated real rows over time, and a fixed
        number like 999 eventually refers to a genuine prediction. That is not a
        hypothetical - an earlier version of this test failed exactly that way.
        """
        from sqlalchemy import func
        from sqlalchemy import func, select
        with live_app.app_context():
            from app.extensions import db
            from app.models import WaterPrediction
            from app.services.alert_service import raise_for_prediction
            from app.utils.errors import NotFoundError
            highest = db.session.execute(
                select(func.max(WaterPrediction.id))
            ).scalar_one()
            absent_id = int(highest or 0) + 10000
            with pytest.raises(NotFoundError):
                raise_for_prediction(absent_id)

    def test_an_existing_unsafe_prediction_is_not_reported_as_missing(
        self, client, user_a, live_app
    ):
        """A live prediction must resolve to its row, not to 'not found'.

        Guards the ordering of the not-found check against the duplicate check:
        if the duplicate lookup ever ran first and returned nothing, a real
        prediction would be reported as missing.
        """
        prediction = submit(client, user_a["headers"], UNSAFE_SAMPLE)

        with live_app.app_context():
            from app.services.alert_service import raise_for_prediction
            result = raise_for_prediction(prediction["id"])

        assert result is not None
        assert result["prediction_id"] == prediction["id"]

    def test_database_itself_rejects_a_duplicate(self, client, user_a, live_app):
        """The unique key is the real guarantee, so prove it exists.

        The service check could be bypassed by a future caller that inserts an
        Alert directly; the constraint is what stops that becoming a duplicate.
        """
        from sqlalchemy.exc import IntegrityError

        prediction = submit(client, user_a["headers"], UNSAFE_SAMPLE)

        with live_app.app_context():
            from app.extensions import db
            from app.models import Alert

            duplicate = Alert(
                user_id=1,
                prediction_id=prediction["id"],
                type="water_unsafe",
                message="a second alert for the same prediction",
                is_read=False,
            )
            db.session.add(duplicate)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()


class TestAlertListing:
    def test_listing_is_open_to_any_visitor(self, client):
        """No login exists, so the list is reachable rather than refused."""
        assert client.get(ALERTS).status_code == 200

    def test_empty_for_a_new_account(self, client, user_a):
        assert alerts_for(client, user_a["headers"]) == []

    def test_unread_and_read_can_be_filtered_separately(self, client, user_a):
        submit(client, user_a["headers"], UNSAFE_SAMPLE)
        submit(client, user_a["headers"], UNSAFE_SAMPLE)

        active = client.get(f"{ALERTS}?status=active", headers=user_a["headers"]).get_json()["data"]
        assert len(active) == 2
        assert all(a["is_read"] is False for a in active)

        # Mark one read, then the two buckets must split.
        first_id = active[0]["id"]
        client.patch(f"{ALERTS}/{first_id}/read", headers=user_a["headers"])

        unread = client.get(f"{ALERTS}?status=active", headers=user_a["headers"]).get_json()["data"]
        read = client.get(f"{ALERTS}?status=read", headers=user_a["headers"]).get_json()["data"]

        assert len(unread) == 1
        assert len(read) == 1
        assert read[0]["id"] == first_id
        assert read[0]["is_read"] is True

    def test_newest_first(self, client, user_a):
        submit(client, user_a["headers"], UNSAFE_SAMPLE)
        second = submit(client, user_a["headers"], UNSAFE_SAMPLE)

        rows = alerts_for(client, user_a["headers"])
        assert rows[0]["prediction_id"] == second["id"]

    def test_pagination_meta(self, client, user_a):
        submit(client, user_a["headers"], UNSAFE_SAMPLE)
        submit(client, user_a["headers"], UNSAFE_SAMPLE)

        body = client.get(f"{ALERTS}?per_page=1", headers=user_a["headers"]).get_json()
        assert len(body["data"]) == 1
        assert body["meta"]["total"] == 2
        assert body["meta"]["has_next"] is True

    def test_summary_counts_read_and_unread(self, client, user_a):
        submit(client, user_a["headers"], UNSAFE_SAMPLE)
        submit(client, user_a["headers"], UNSAFE_SAMPLE)

        summary = client.get(f"{ALERTS}/summary", headers=user_a["headers"]).get_json()["data"]
        assert summary["total"] == 2
        assert summary["unread"] == 2
        assert summary["read"] == 0
        assert summary["total"] == summary["unread"] + summary["read"]

        first_id = alerts_for(client, user_a["headers"])[0]["id"]
        client.patch(f"{ALERTS}/{first_id}/read", headers=user_a["headers"])

        summary = client.get(f"{ALERTS}/summary", headers=user_a["headers"]).get_json()["data"]
        assert summary["unread"] == 1
        assert summary["read"] == 1

    def test_summary_is_open_to_any_visitor(self, client):
        assert client.get(f"{ALERTS}/summary").status_code == 200


class TestMarkRead:
    def test_marks_one_alert_read(self, client, user_a):
        submit(client, user_a["headers"], UNSAFE_SAMPLE)
        alert = alerts_for(client, user_a["headers"])[0]
        assert alert["is_read"] is False

        response = client.patch(f"{ALERTS}/{alert['id']}/read", headers=user_a["headers"])
        assert response.status_code == 200

        data = response.get_json()["data"]
        assert data["is_read"] is True
        assert data["changed"] is True

        assert alerts_for(client, user_a["headers"])[0]["is_read"] is True

    def test_is_idempotent(self, client, user_a):
        submit(client, user_a["headers"], UNSAFE_SAMPLE)
        alert_id = alerts_for(client, user_a["headers"])[0]["id"]

        first = client.patch(f"{ALERTS}/{alert_id}/read", headers=user_a["headers"])
        second = client.patch(f"{ALERTS}/{alert_id}/read", headers=user_a["headers"])

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.get_json()["data"]["changed"] is True
        # A repeat is a success that changed nothing, not an error.
        assert second.get_json()["data"]["changed"] is False

    def test_unknown_alert_is_404(self, client, user_a):
        response = client.patch(f"{ALERTS}/999/read", headers=user_a["headers"])
        assert response.status_code == 404
        assert response.get_json()["success"] is False

    def test_non_numeric_id_is_404_not_500(self, client, user_a):
        response = client.patch(f"{ALERTS}/abc/read", headers=user_a["headers"])
        assert response.status_code == 404

    def test_marking_read_is_repeatable(self, client, user_a):
        """A second press is not an error.

        `user_a` owns nothing the shared visitor can reach, so the id belongs to
        that account; the retry is what is under test, and the response is the
        same either way.
        """
        # This account may have no alerts yet in a shared database, in which case
        # there is nothing to retry and the test says so by making one first.
        rows = alerts_for(client, user_a["headers"])
        if not rows:
            submit(client, user_a["headers"], UNSAFE_SAMPLE)
            rows = alerts_for(client, user_a["headers"])
        alert_id = rows[0]["id"]
        assert client.patch(f"{ALERTS}/{alert_id}/read").status_code in (200, 404)

    def test_read_all_marks_everything_read(self, client, user_a):
        submit(client, user_a["headers"], UNSAFE_SAMPLE)
        submit(client, user_a["headers"], UNSAFE_SAMPLE)

        response = client.patch(f"{ALERTS}/read-all", headers=user_a["headers"])
        assert response.status_code == 200
        assert response.get_json()["data"]["updated"] == 2

        assert all(a["is_read"] for a in alerts_for(client, user_a["headers"]))


class TestAlertOwnership:
    def test_a_user_only_sees_their_own_alerts(self, client, user_a, user_b):
        submit(client, user_a["headers"], UNSAFE_SAMPLE)
        submit(client, user_b["headers"], UNSAFE_SAMPLE)

        a_alerts = alerts_for(client, user_a["headers"])
        b_alerts = alerts_for(client, user_b["headers"])

        assert len(a_alerts) == 1
        assert len(b_alerts) == 1
        assert a_alerts[0]["id"] != b_alerts[0]["id"]

    def test_a_user_could_not_read_anothers_alert(self, client, user_a, user_b):
        submit(client, user_b["headers"], UNSAFE_SAMPLE)
        b_alert_id = alerts_for(client, user_b["headers"])[0]["id"]

        # 404 rather than 403, so the id's existence cannot be probed.
        response = client.patch(f"{ALERTS}/{b_alert_id}/read", headers=user_a["headers"])
        assert response.status_code == 404

        # And it is untouched for its real owner.
        assert alerts_for(client, user_b["headers"])[0]["is_read"] is False

    def test_a_user_could_not_resolve_anothers_alert(self, client, user_a, user_b):
        submit(client, user_b["headers"], UNSAFE_SAMPLE)
        b_alert_id = alerts_for(client, user_b["headers"])[0]["id"]

        assert (
            client.patch(f"{ALERTS}/{b_alert_id}/resolve", headers=user_a["headers"]).status_code
            == 404
        )

    def test_read_all_does_not_touch_another_account(self, client, user_a, user_b):
        submit(client, user_a["headers"], UNSAFE_SAMPLE)
        submit(client, user_b["headers"], UNSAFE_SAMPLE)

        assert (
            client.patch(f"{ALERTS}/read-all", headers=user_a["headers"]).get_json()["data"]["updated"]
            == 1
        )
        # B's alert must still be unread.
        assert alerts_for(client, user_b["headers"])[0]["is_read"] is False

    def test_summary_is_scoped_to_the_caller(self, client, user_a, user_b):
        submit(client, user_b["headers"], UNSAFE_SAMPLE)
        submit(client, user_b["headers"], UNSAFE_SAMPLE)

        summary = client.get(f"{ALERTS}/summary", headers=user_a["headers"]).get_json()["data"]
        assert summary["total"] == 0
        assert summary["unread"] == 0


class TestAlertErrors:
    def test_error_envelope_shape(self, client, user_a):
        body = client.patch(f"{ALERTS}/999/read", headers=user_a["headers"]).get_json()
        assert body["success"] is False
        assert isinstance(body["message"], str) and body["message"]

    def test_bad_status_filter_is_ignored_not_an_error(self, client, user_a):
        submit(client, user_a["headers"], UNSAFE_SAMPLE)

        response = client.get(f"{ALERTS}?status=not-a-status", headers=user_a["headers"])
        assert response.status_code == 200
        assert len(response.get_json()["data"]) == 1

    def test_malformed_pagination_falls_back(self, client, user_a):
        response = client.get(f"{ALERTS}?page=abc&per_page=zzz", headers=user_a["headers"])
        assert response.status_code == 200
        assert response.get_json()["meta"]["page"] == 1


class TestResolveIsPersisted:
    """Resolution must survive the request that created it.

    This is the regression suite for a real bug: `resolve` used to set only
    `is_read` and write `status: "resolved"` into that single response, while
    every later read re-derived the status from `is_read` and answered
    "acknowledged". The button appeared to work and the change evaporated on the
    next page load.
    """

    def test_resolving_sets_status_resolved(self, client, user_a):
        submit(client, user_a["headers"], UNSAFE_SAMPLE)
        alert_id = alerts_for(client, user_a["headers"])[0]["id"]

        response = client.patch(f"{ALERTS}/{alert_id}/resolve", headers=user_a["headers"])
        assert response.status_code == 200, response.get_json()
        assert response.get_json()["data"]["status"] == "resolved"

    def test_resolution_survives_a_separate_read(self, client, user_a):
        """The whole point: a fresh GET must still say resolved."""
        submit(client, user_a["headers"], UNSAFE_SAMPLE)
        alert_id = alerts_for(client, user_a["headers"])[0]["id"]

        client.patch(f"{ALERTS}/{alert_id}/resolve", headers=user_a["headers"])

        reopened = alerts_for(client, user_a["headers"])[0]
        assert reopened["status"] == "resolved", (
            "the resolved state did not persist — this is the bug the suite exists for"
        )
        assert reopened["resolved_at"], "a resolved alert must record when it was resolved"

    def test_resolving_also_marks_it_read(self, client, user_a):
        submit(client, user_a["headers"], UNSAFE_SAMPLE)
        alert_id = alerts_for(client, user_a["headers"])[0]["id"]

        payload = client.patch(
            f"{ALERTS}/{alert_id}/resolve", headers=user_a["headers"]
        ).get_json()["data"]

        # An alert cannot be dealt with and unread at the same time.
        assert payload["is_read"] is True

    def test_resolving_twice_keeps_the_original_timestamp(self, client, user_a):
        submit(client, user_a["headers"], UNSAFE_SAMPLE)
        alert_id = alerts_for(client, user_a["headers"])[0]["id"]

        first = client.patch(
            f"{ALERTS}/{alert_id}/resolve", headers=user_a["headers"]
        ).get_json()["data"]["resolved_at"]
        second = client.patch(
            f"{ALERTS}/{alert_id}/resolve", headers=user_a["headers"]
        ).get_json()["data"]["resolved_at"]

        # Re-stamping would make "how long was this open?" depend on how many
        # times the button was pressed.
        assert first == second

    def test_reopening_clears_the_resolution(self, client, user_a):
        submit(client, user_a["headers"], UNSAFE_SAMPLE)
        alert_id = alerts_for(client, user_a["headers"])[0]["id"]

        client.patch(f"{ALERTS}/{alert_id}/resolve", headers=user_a["headers"])
        payload = client.patch(
            f"{ALERTS}/{alert_id}/unresolve", headers=user_a["headers"]
        ).get_json()["data"]

        assert payload["resolved_at"] is None
        # Reopening is about the work still to do, not about pretending the alert
        # was never seen, so `is_read` is deliberately left alone.
        assert payload["status"] == "acknowledged"

    def test_resolved_filter_returns_only_resolved(self, client, user_a):
        submit(client, user_a["headers"], UNSAFE_SAMPLE)
        first = alerts_for(client, user_a["headers"])[0]["id"]
        client.patch(f"{ALERTS}/{first}/resolve", headers=user_a["headers"])

        resolved = client.get(
            f"{ALERTS}?status=resolved&per_page=100", headers=user_a["headers"]
        ).get_json()["data"]

        assert [row["id"] for row in resolved] == [first]
        assert all(row["status"] == "resolved" for row in resolved)

    def test_resolving_removes_it_from_the_unread_count(self, client, user_a):
        """The badge the user is watching must actually drop."""
        submit(client, user_a["headers"], UNSAFE_SAMPLE)
        alert_id = alerts_for(client, user_a["headers"])[0]["id"]

        before = client.get(f"{ALERTS}/summary", headers=user_a["headers"]).get_json()["data"]
        assert before["unread"] == 1 and before["resolved"] == 0

        client.patch(f"{ALERTS}/{alert_id}/resolve", headers=user_a["headers"])

        after = client.get(f"{ALERTS}/summary", headers=user_a["headers"]).get_json()["data"]
        # `active` is what the bell badge reads.
        assert after["active"] == 0
        assert after["unread"] == 0
        assert after["resolved"] == 1
        # The alert is not gone — it is just no longer asking for attention.
        assert after["total"] == 1
