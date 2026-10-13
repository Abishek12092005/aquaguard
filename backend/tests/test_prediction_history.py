"""Independent tests for prediction history, filtering and ownership.

The ownership tests are the important ones. "One user cannot read another
user's prediction by changing the ID" is a security property, so it is tested by
creating two real accounts, having each submit real predictions through the real
endpoint, and then attempting a genuine cross-account read — not by mocking the
lookup and asserting the mock was called.
"""

import uuid

import pytest

from app.constants import API_PREFIX, FEATURE_NAMES, RISK_LEVELS

HISTORY = f"{API_PREFIX}/predictions/history"
PREDICTIONS = f"{API_PREFIX}/predictions"
PREDICT = f"{API_PREFIX}/predictions/predict"

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

    # Yield OUTSIDE the app context: a context held for a whole module keeps one
    # scoped session alive across tests and leaks rows between them. The visible
    # symptom was history pages returning other accounts' rows.
    yield application


@pytest.fixture()
def client(live_app):
    return live_app.test_client()


def make_account(client, label="user"):
    """Create a distinct account and return (headers, user payload).

    The application has no registration, so the row is written directly. The
    token is minted by the test: production issues no user tokens, because the
    console authenticates with its own credential.
    """
    from tests.conftest import headers_for, make_test_account

    with client.application.app_context():
        user_id, name, email = make_test_account(f"hist_{label}")
        # Minted INSIDE the context: `create_access_token` needs `current_app`.
        return headers_for(user_id), {"id": user_id, "name": name, "email": email}


@pytest.fixture()
def user_a(client):
    headers, user = make_account(client, "a")
    return {"headers": headers, "user": user}


@pytest.fixture()
def user_b(client):
    headers, user = make_account(client, "b")
    return {"headers": headers, "user": user}


def submit(client, headers, sample):
    response = client.post(PREDICT, json=sample, headers=headers)
    assert response.status_code == 201, response.get_json()
    return response.get_json()["data"]


class TestHistoryListing:
    def test_empty_history_for_a_brand_new_account(self, client, user_a):
        response = client.get(HISTORY, headers=user_a["headers"])
        assert response.status_code == 200

        body = response.get_json()
        assert body["success"] is True
        assert body["data"] == []
        assert body["meta"]["total"] == 0

    def test_is_open_to_a_visitor_with_no_token(self, client):
        """No login exists, so history answers rather than rejecting the caller.

        A brand-new visitor is the shared visitor account, which is empty unless
        an earlier test submitted to it - so this asserts the endpoint is
        REACHABLE, not what it contains.
        """
        assert client.get(HISTORY).status_code == 200

    def test_returns_every_field_the_table_needs(self, client, user_a):
        submit(client, user_a["headers"], SAFE_SAMPLE)

        row = client.get(HISTORY, headers=user_a["headers"]).get_json()["data"][0]

        # Exactly the columns the history page renders.
        for key in ("id", "created_at", "prediction", "confidence", *FEATURE_NAMES):
            assert key in row, f"{key} missing from a history row"
        assert row["prediction"] in RISK_LEVELS
        assert row["ph"] == SAFE_SAMPLE["ph"]

    def test_newest_first(self, client, user_a):
        first = submit(client, user_a["headers"], SAFE_SAMPLE)
        second = submit(client, user_a["headers"], UNSAFE_SAMPLE)

        ids = [r["id"] for r in client.get(HISTORY, headers=user_a["headers"]).get_json()["data"]]
        assert ids[0] == second["id"]
        assert ids[1] == first["id"]

    def test_short_prefix_route_also_works(self, client, user_a):
        response = client.get("/api/predictions/history", headers=user_a["headers"])
        assert response.status_code == 200


class TestHistoryPagination:
    def test_limit_is_respected_and_meta_is_accurate(self, client, user_a):
        for _ in range(3):
            submit(client, user_a["headers"], SAFE_SAMPLE)

        body = client.get(
            f"{HISTORY}?per_page=2", headers=user_a["headers"]
        ).get_json()

        assert len(body["data"]) == 2
        assert body["meta"]["per_page"] == 2
        assert body["meta"]["total"] >= 3
        assert body["meta"]["pages"] >= 2
        assert body["meta"]["has_next"] is True

    def test_second_page_does_not_repeat_the_first(self, client, user_a):
        for _ in range(3):
            submit(client, user_a["headers"], SAFE_SAMPLE)

        first = client.get(f"{HISTORY}?per_page=2&page=1", headers=user_a["headers"]).get_json()
        second = client.get(f"{HISTORY}?per_page=2&page=2", headers=user_a["headers"]).get_json()

        first_ids = {r["id"] for r in first["data"]}
        second_ids = {r["id"] for r in second["data"]}
        assert not (first_ids & second_ids)

    def test_per_page_is_clamped(self, client, user_a):
        body = client.get(f"{HISTORY}?per_page=100000", headers=user_a["headers"]).get_json()
        assert body["meta"]["per_page"] <= 100

        body = client.get(f"{HISTORY}?per_page=-5", headers=user_a["headers"]).get_json()
        assert body["meta"]["per_page"] >= 1

    def test_malformed_pagination_falls_back_to_defaults(self, client, user_a):
        response = client.get(f"{HISTORY}?page=abc&per_page=xyz", headers=user_a["headers"])
        assert response.status_code == 200
        assert response.get_json()["meta"]["page"] == 1


class TestHistoryFiltering:
    def test_risk_level_filter_is_applied_across_the_whole_history(self, client, user_a):
        """The filter must not merely filter the page being viewed.

        Six safe records are submitted after the unsafe one, so a client-side
        filter over page 1 would miss the unsafe row entirely.
        """
        unsafe = submit(client, user_a["headers"], UNSAFE_SAMPLE)
        for _ in range(6):
            submit(client, user_a["headers"], SAFE_SAMPLE)

        body = client.get(
            f"{HISTORY}?risk_level=unsafe&per_page=50", headers=user_a["headers"]
        ).get_json()

        ids = [r["id"] for r in body["data"]]
        assert unsafe["id"] in ids
        assert all(r["prediction"] == "unsafe" for r in body["data"])

    def test_unknown_risk_level_is_ignored_not_rejected(self, client, user_a):
        submit(client, user_a["headers"], SAFE_SAMPLE)

        response = client.get(f"{HISTORY}?risk_level=banana", headers=user_a["headers"])
        assert response.status_code == 200
        assert response.get_json()["meta"]["filters"]["risk_level"] is None
        assert len(response.get_json()["data"]) >= 1

    def test_search_matches_a_parameter_value(self, client, user_a):
        submit(client, user_a["headers"], UNSAFE_SAMPLE)

        body = client.get(
            f"{HISTORY}?search=4800", headers=user_a["headers"]
        ).get_json()

        assert len(body["data"]) >= 1
        assert any(r["tds"] == 4800.0 for r in body["data"])

    def test_search_matches_the_verdict(self, client, user_a):
        submit(client, user_a["headers"], UNSAFE_SAMPLE)

        body = client.get(
            f"{HISTORY}?search=unsafe", headers=user_a["headers"]
        ).get_json()

        assert all(r["prediction"] == "unsafe" for r in body["data"])

    def test_search_with_no_match_returns_empty_not_everything(self, client, user_a):
        submit(client, user_a["headers"], SAFE_SAMPLE)

        body = client.get(
            f"{HISTORY}?search=zzz-no-such-value", headers=user_a["headers"]
        ).get_json()

        assert body["data"] == []
        assert body["meta"]["total"] == 0

    def test_like_wildcards_are_escaped(self, client, user_a):
        """A bare '%' must not match every row."""
        submit(client, user_a["headers"], SAFE_SAMPLE)

        body = client.get(f"{HISTORY}?search=%", headers=user_a["headers"]).get_json()
        assert body["data"] == []

    def test_sort_oldest_reverses_the_order(self, client, user_a):
        first = submit(client, user_a["headers"], SAFE_SAMPLE)
        second = submit(client, user_a["headers"], UNSAFE_SAMPLE)

        ids = [
            r["id"]
            for r in client.get(
                f"{HISTORY}?sort=oldest", headers=user_a["headers"]
            ).get_json()["data"]
        ]
        assert ids[0] == first["id"]
        assert ids[1] == second["id"]

    def test_sort_confidence_puts_the_strongest_first(self, client, user_a):
        submit(client, user_a["headers"], SAFE_SAMPLE)
        submit(client, user_a["headers"], UNSAFE_SAMPLE)

        rows = client.get(
            f"{HISTORY}?sort=confidence", headers=user_a["headers"]
        ).get_json()["data"]

        confidences = [r["confidence"] for r in rows]
        assert confidences == sorted(confidences, reverse=True)

    def test_applied_filters_are_echoed(self, client, user_a):
        meta = client.get(
            f"{HISTORY}?risk_level=safe&search=7&sort=oldest", headers=user_a["headers"]
        ).get_json()["meta"]

        assert meta["filters"] == {
            "risk_level": "safe",
            "search": "7",
            "sort": "oldest",
        }


class TestOwnershipIsolation:
    """A user must never see or fetch another user's prediction."""

    def test_history_only_contains_the_callers_own_rows(self, client, user_a, user_b):
        a_row = submit(client, user_a["headers"], SAFE_SAMPLE)
        b_row = submit(client, user_b["headers"], UNSAFE_SAMPLE)

        a_ids = {
            r["id"] for r in client.get(HISTORY, headers=user_a["headers"]).get_json()["data"]
        }
        b_ids = {
            r["id"] for r in client.get(HISTORY, headers=user_b["headers"]).get_json()["data"]
        }

        assert a_row["id"] in a_ids
        assert b_row["id"] not in a_ids
        assert b_row["id"] in b_ids
        assert a_row["id"] not in b_ids

    def test_fetching_another_users_prediction_by_id_is_not_found(
        self, client, user_a, user_b
    ):
        """The core check: changing the ID must not cross accounts."""
        b_row = submit(client, user_b["headers"], UNSAFE_SAMPLE)

        response = client.get(
            f"{PREDICTIONS}/{b_row['id']}", headers=user_a["headers"]
        )

        # 404 rather than 403: a caller must not be able to probe which ids
        # exist by comparing "forbidden" against "not found".
        assert response.status_code == 404
        assert "prediction" not in (response.get_json().get("data") or {})

    def test_the_owner_can_fetch_their_own_row(self, client, user_b):
        b_row = submit(client, user_b["headers"], UNSAFE_SAMPLE)

        response = client.get(
            f"{PREDICTIONS}/{b_row['id']}", headers=user_b["headers"]
        )
        assert response.status_code == 200
        assert response.get_json()["data"]["id"] == b_row["id"]

    def test_deleting_another_users_prediction_is_not_found(
        self, client, user_a, user_b
    ):
        b_row = submit(client, user_b["headers"], SAFE_SAMPLE)

        assert (
            client.delete(f"{PREDICTIONS}/{b_row['id']}", headers=user_a["headers"]).status_code
            == 404
        )
        # And it is still there for its actual owner.
        assert (
            client.get(f"{PREDICTIONS}/{b_row['id']}", headers=user_b["headers"]).status_code
            == 200
        )

    def test_search_cannot_be_used_to_reach_another_account(self, client, user_a, user_b):
        """Filters narrow the caller's rows; they must never widen them."""
        b_row = submit(client, user_b["headers"], UNSAFE_SAMPLE)

        # Search for the exact reading the other account submitted.
        body = client.get(
            f"{HISTORY}?search=4800&per_page=100", headers=user_a["headers"]
        ).get_json()

        assert b_row["id"] not in [r["id"] for r in body["data"]]

    def test_filtering_by_a_risk_level_the_other_user_has(self, client, user_a, user_b):
        submit(client, user_b["headers"], UNSAFE_SAMPLE)

        body = client.get(
            f"{HISTORY}?risk_level=unsafe&per_page=100", headers=user_a["headers"]
        ).get_json()

        assert body["data"] == []

    def test_high_per_page_cannot_leak_other_rows(self, client, user_a, user_b):
        for _ in range(5):
            submit(client, user_b["headers"], SAFE_SAMPLE)

        body = client.get(f"{HISTORY}?per_page=100", headers=user_a["headers"]).get_json()
        a_ids = {r["id"] for r in body["data"]}

        b_ids = {
            r["id"] for r in client.get(HISTORY, headers=user_b["headers"]).get_json()["data"]
        }
        assert not (a_ids & b_ids)


class TestDetailEndpoint:
    def test_unknown_id_is_404(self, client, user_a):
        response = client.get(f"{PREDICTIONS}/99999", headers=user_a["headers"])
        assert response.status_code == 404

    def test_non_numeric_id_is_404_not_500(self, client, user_a):
        response = client.get(f"{PREDICTIONS}/not-a-number", headers=user_a["headers"])
        assert response.status_code == 404

    def test_detail_is_open_to_a_visitor(self, client, user_a):
        """A record the visitor owns is readable without any sign-in.

        Anonymous callers all resolve to the shared visitor, so this submits as
        that account rather than as `user_a`.
        """
        row = submit(client, {}, SAFE_SAMPLE)
        assert client.get(f"{PREDICTIONS}/{row['id']}").status_code == 200

    def test_detail_matches_the_stored_reading(self, client, user_a):
        row = submit(client, user_a["headers"], UNSAFE_SAMPLE)

        detail = client.get(
            f"{PREDICTIONS}/{row['id']}", headers=user_a["headers"]
        ).get_json()["data"]

        assert detail["prediction"] == row["prediction"]
        assert detail["confidence"] == row["confidence"]
        for name in FEATURE_NAMES:
            assert detail[name] == UNSAFE_SAMPLE[name]
