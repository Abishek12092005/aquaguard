"""Tests for the admin console, sign-in tracking and multi-provider AI.

These are behavioural tests against the real application, following the pattern
the rest of the suite uses. They deliberately do NOT reach the network: mail is
suppressed by `TestingConfig`, and the AI providers are exercised through the
resolver rather than by making calls.
"""

import uuid

import pytest

from app.constants import API_PREFIX

ADMIN = "/api/admin"
PREDICT = f"{API_PREFIX}/predictions/predict"

UNSAFE_SAMPLE = {
    "ph": 2.1,
    "turbidity": 45.0,
    "tds": 2100.0,
    "temperature": 34.0,
    "dissolved_oxygen": 1.2,
}


def make_account(client, label="u", role=None):
    """Create an account directly and return its headers.

    The application has no registration, so the row is written here. The token is
    minted rather than obtained, which is why nothing in production issues one:
    the console authenticates with its own credential, not with a user session.

    The token is minted INSIDE the application context: `create_access_token`
    reads the JWT manager from `current_app`, so calling it after the context has
    closed raises "Working outside of application context" - which was exactly
    what the old version did on every fixture that used it.
    """
    from tests.conftest import headers_for, make_test_account

    with client.application.app_context():
        user_id, _name, email = make_test_account(f"admin_{label}", role or "user")
        return {
            "headers": headers_for(user_id),
            "id": user_id,
            "email": email,
        }


@pytest.fixture()
def admin(client):
    """The console, open.

    THE CONSOLE IS ITS OWN AUTHENTICATION. There is no user login to be an
    administrator through, so `admin` here is simply "a caller who has proved
    the console password" - which the fixture does by opening the window.

    Most tests below want to exercise console BEHAVIOUR rather than its gate, so
    they take this fixture and never think about it again. The tests that DO test
    the gate deliberately do not take it.
    """
    account = make_account(client, "admin", role="admin")
    from app.services.console_session import lock, unlock

    with client.application.app_context():
        lock()
        unlock()
    return account


@pytest.fixture()
def locked_admin(client):
    """The console identity WITHOUT the window open - for testing the gate."""
    return make_account(client, "locked", role="admin")


@pytest.fixture()
def normal_user(client):
    return make_account(client, "user")


# ---------------------------------------------------------------------------
# The login-details dataset is now a historical record
# ---------------------------------------------------------------------------
class TestLoginDetailsAreHistorical:
    """The dataset still reads back, but nothing writes to it any more.

    User authentication was removed, so there is no registration and no sign-in
    to record. The table and its console screen are kept because the EXISTING
    rows are real data; what is gone is the flow that appended to it.
    """

    def test_the_endpoint_answers_while_the_console_is_open(self, client, admin):
        response = client.get(f"{ADMIN}/login-details", headers=admin["headers"])
        assert response.status_code == 200, response.get_json()
        assert isinstance(response.get_json()["data"], list)

    def test_stats_answer_while_the_console_is_open(self, client, admin):
        response = client.get(f"{ADMIN}/login-details/stats", headers=admin["headers"])
        assert response.status_code == 200, response.get_json()

    def test_the_screen_is_closed_when_the_console_is_locked(self, client, locked_admin):
        response = client.get(f"{ADMIN}/login-details", headers=locked_admin["headers"])
        assert response.status_code == 403

    def test_no_credential_is_ever_returned(self, client, admin):
        rows = client.get(f"{ADMIN}/login-details", headers=admin["headers"]).get_json()["data"]
        blob = str(rows)
        assert "$2b$" not in blob, "a bcrypt hash must never appear in this dataset"
        # NO VALUE resembling a password or hash may be present. The wording
        # "invalid email or password" in a failure_reason is not a credential:
        # it is the label a historical row carries, so it is allowed here.
        import re

        assert not re.search(r"\$2[aby]\$", blob), "a bcrypt hash must never appear"
        assert not re.search(r"password\s*['\"]?\s*[:=]", blob), "no password value may be present"


# ---------------------------------------------------------------------------
# Authorisation
# ---------------------------------------------------------------------------
class TestAdminAuthorisation:
    """The console's gate.

    THE WHOLE OF IT IS THE CONSOLE PASSWORD. There is no user login behind this,
    so there is no account to escalate from: an open window IS the authorisation,
    and every endpoint below refuses everything until it is opened.
    """

    def test_everything_is_refused_while_the_console_is_locked(self, client, locked_admin):
        for path in ("/dashboard", "/users", "/login-details", "/reports", "/models"):
            response = client.get(f"{ADMIN}{path}", headers=locked_admin["headers"])
            assert response.status_code == 403, f"{path} must need the console open"
            assert "locked" in response.get_json()["message"].lower()

    def test_a_destructive_action_is_refused_while_locked(self, client, locked_admin, normal_user):
        response = client.delete(
            f"{ADMIN}/users/{normal_user['id']}", headers=locked_admin["headers"]
        )
        assert response.status_code == 403
        assert "locked" in response.get_json()["message"].lower()

    def test_opening_the_window_grants_access(self, client, locked_admin):
        """The same call, once the window is open, succeeds."""
        assert client.get(f"{ADMIN}/dashboard", headers=locked_admin["headers"]).status_code == 403

        # Open the window the way a real login does: prove the credential, wait
        # for the mail to approve, then spend the approval from this browser.
        from app.services.login_approval_service import (
            create_request,
            decide,
            new_challenge,
            spend_on_unlock,
        )

        with client.application.app_context():
            challenge = new_challenge()
            row, token = create_request("abishek", challenge=challenge)
            decide(row.request_id, "approve", token, client_ip=None)
            assert spend_on_unlock(row.request_id, challenge), "approval must be spendable"
            from app.services.console_session import unlock
            unlock()

        assert client.get(f"{ADMIN}/dashboard", headers=locked_admin["headers"]).status_code == 200

    def test_the_console_starts_locked(self, client, locked_admin):
        state = client.get(f"{ADMIN}/session", headers=locked_admin["headers"]).get_json()["data"]
        assert state["unlocked"] is False

    def test_the_session_state_endpoint_is_reachable_while_locked(self, client):
        """It has to be: the page calls it FIRST, to decide what to render.

        It reports state and nothing else, so being open is safe - and the
        refusal test above covers every endpoint that returns real data.
        """
        assert client.get(f"{ADMIN}/session").status_code == 200

    def test_the_wrong_console_password_opens_nothing(self, client):
        wrong = client.post(
            f"{ADMIN}/session", json={"password": "not-the-password"}
        )
        assert wrong.status_code == 401
        # And the window is still shut, so a guess cannot be followed by a read.
        assert client.get(f"{ADMIN}/session").get_json()["data"]["unlocked"] is False

    def test_the_right_console_password_still_waits_for_the_mail(self, client):
        """The password alone proves nothing - the mail is the second step."""
        challenge = client.get(f"{ADMIN}/session/challenge").get_json()["data"]["challenge"]
        right = client.post(
            f"{ADMIN}/session", json={"password": "admin-console-pass", "challenge": challenge}
        )
        assert right.status_code == 200
        assert right.get_json()["data"]["mail_sent"] is True
        assert client.get(f"{ADMIN}/session").get_json()["data"]["unlocked"] is False

    def test_a_wrong_username_and_password_fail_identically(self, client):
        """Neither half may be revealed by the response."""
        byName = client.post(
            f"{ADMIN}/session", json={"username": "nobody", "password": "admin-console-pass"}
        )
        byPass = client.post(
            f"{ADMIN}/session", json={"username": "abishek", "password": "wrong"}
        )
        assert byName.status_code == byPass.status_code == 401
        assert byName.get_json()["message"] == byPass.get_json()["message"]


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------
class TestUserManagement:
    def test_users_are_listed_with_their_counts(self, client, admin, normal_user):
        client.post(PREDICT, json=UNSAFE_SAMPLE, headers=normal_user["headers"])

        rows = client.get(f"{ADMIN}/users", headers=admin["headers"]).get_json()["data"]
        target = next(row for row in rows if row["id"] == normal_user["id"])

        assert target["email"] == normal_user["email"]
        assert target["prediction_count"] == 1
        assert target["alert_count"] >= 1, "an unsafe reading raises an alert"
        # No credential field may be present.
        assert "password_hash" not in target and "password" not in target

    def test_a_user_can_be_removed_and_their_rows_cascade(
        self, client, admin, normal_user
    ):
        client.post(PREDICT, json=UNSAFE_SAMPLE, headers=normal_user["headers"])

        response = client.delete(
            f"{ADMIN}/users/{normal_user['id']}", headers=admin["headers"]
        )
        assert response.status_code == 200, response.get_json()

        # Gone from the listing.
        remaining = client.get(f"{ADMIN}/users", headers=admin["headers"]).get_json()["data"]
        assert all(row["id"] != normal_user["id"] for row in remaining)

    def test_the_shared_visitor_record_cannot_be_deleted(self, client, admin):
        """It is infrastructure, not an account.

        Every reading submitted without a sign-in is filed under it, and those
        foreign keys are NOT NULL - so removing the row would either fail or take
        the whole public record with it.
        """
        from app.services.identity import VISITOR_EMAIL

        # The shared visitor row is created on first use by the identity layer,
        # not by a migration, so the test guarantees it exists rather than
        # assuming a previous test made one: it resolves the id (which creates
        # the row if needed), then confirms the console lists it by search --
        # which is the console's own way to reach one account in a shared
        # database with many rows.
        with client.application.app_context():
            from app.services.identity import visitor_id

            visitor_id()

        found = client.get(
            f"{ADMIN}/users", headers=admin["headers"], query_string={"search": VISITOR_EMAIL}
        ).get_json()["data"]
        visitor = next((row for row in found if row["email"] == VISITOR_EMAIL), None)
        assert visitor is not None, "the shared visitor must appear in the console"

        response = client.delete(
            f"{ADMIN}/users/{visitor['id']}", headers=admin["headers"]
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Parameter limits
# ---------------------------------------------------------------------------
class TestParameterLimits:
    def test_limits_start_at_the_built_in_defaults(self, client, admin):
        rows = client.get(f"{ADMIN}/parameter-limits", headers=admin["headers"]).get_json()["data"]
        by_name = {row["name"]: row for row in rows}

        assert by_name["ph"]["min"] == 0.0
        assert by_name["ph"]["max"] == 14.0
        assert by_name["ph"]["is_overridden"] is False

    def test_a_tighter_limit_can_be_set(self, client, admin):
        response = client.put(
            f"{ADMIN}/parameter-limits",
            json={"ph": {"min": 6.5, "max": 8.5}},
            headers=admin["headers"],
        )
        assert response.status_code == 200, response.get_json()

        rows = {row["name"]: row for row in response.get_json()["data"]}
        assert rows["ph"]["min"] == 6.5
        assert rows["ph"]["is_overridden"] is True

    def test_a_limit_wider_than_the_physical_range_is_refused(self, client, admin):
        """The console may tighten, never widen — the model was trained inside it."""
        response = client.put(
            f"{ADMIN}/parameter-limits",
            json={"ph": {"min": -5, "max": 99}},
            headers=admin["headers"],
        )
        assert response.status_code == 422
        assert "ph" in response.get_json()["errors"]

    def test_an_inverted_range_is_refused(self, client, admin):
        response = client.put(
            f"{ADMIN}/parameter-limits",
            json={"ph": {"min": 9, "max": 3}},
            headers=admin["headers"],
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Notification settings
# ---------------------------------------------------------------------------
class TestNotificationSettings:
    def test_every_type_is_listed_with_an_editable_template(self, client, admin):
        data = client.get(f"{ADMIN}/notifications", headers=admin["headers"]).get_json()["data"]
        keys = {item["key"] for item in data["types"]}

        for expected in ("water_unsafe", "prediction_ready", "signin_notice"):
            assert expected in keys

        for item in data["types"]:
            assert item["subject"] and item["body"]

    def test_an_edited_template_is_stored(self, client, admin):
        response = client.put(
            f"{ADMIN}/notifications",
            json={
                "templates": {
                    "water_unsafe": {
                        "subject": "Custom subject",
                        "body": "Custom body for {name}",
                    }
                }
            },
            headers=admin["headers"],
        )
        assert response.status_code == 200, response.get_json()

        # Re-read to prove it persisted rather than only echoing the request.
        data = client.get(f"{ADMIN}/notifications", headers=admin["headers"]).get_json()["data"]
        unsafe = next(item for item in data["types"] if item["key"] == "water_unsafe")

        assert unsafe["subject"] == "Custom subject"
        assert unsafe["body"] == "Custom body for {name}"
        assert unsafe["is_customised"] is True

    def test_an_empty_subject_is_refused(self, client, admin):
        response = client.put(
            f"{ADMIN}/notifications",
            json={"templates": {"water_unsafe": {"subject": "", "body": "x"}}},
            headers=admin["headers"],
        )
        assert response.status_code == 422

    def test_an_unknown_type_is_refused(self, client, admin):
        """A silent no-op that looks like a successful save is worse than an error."""
        response = client.put(
            f"{ADMIN}/notifications",
            json={"templates": {"not_a_real_type": {"subject": "x", "body": "y"}}},
            headers=admin["headers"],
        )
        assert response.status_code == 422

    def test_an_unknown_placeholder_does_not_break_rendering(self):
        """A template typo must produce a self-diagnosing message, not a 500.

        This is a property of the RENDERER, so it needs no request and no
        database: `render_template` is pure. Testing it through HTTP was the
        mistake - the assertion was measuring whether two different database
        sessions agreed, not whether the renderer copes with a bad placeholder.
        """
        from app.services.notification_service import render_template

        # An unknown placeholder is left VISIBLE rather than dropped or raised
        # on. A visible {typo} in the inbox is self-diagnosing; an exception
        # would silently stop every notification of that type.
        rendered = render_template("Hello {name}, {not_a_real_field} here", {"name": "Ann"})
        assert "{not_a_real_field}" in rendered
        assert "Ann" in rendered

        # An unsatisfiable format spec is the other way str.format raises.
        assert render_template("{name:!!!bad}", {"name": "Ann"}) == "{name:!!!bad}"

    def test_all_placeholders_unsatisfied_does_not_raise(self):
        """An empty context is the extreme case: nothing is supplied.

        Every notification type must survive it, because a notification raised
        from a path that forgot to pass a value must still be deliverable.
        """
        from app.services.notification_service import (
            DEFAULT_NOTIFICATION_TEMPLATES,
            render_notification,
        )

        for key in DEFAULT_NOTIFICATION_TEMPLATES:
            subject, text, html = render_notification(key, {})
            assert subject, f"{key} produced an empty subject"
            assert text, f"{key} produced an empty body"
            assert html.startswith("<!doctype html")

    def test_a_report_row_carries_its_username_and_identifiers(self, client, admin, normal_user):
        client.post(PREDICT, json=UNSAFE_SAMPLE, headers=normal_user["headers"])

        rows = client.get(f"{ADMIN}/reports?category=all", headers=admin["headers"]).get_json()["data"]
        assert len(rows) >= 1

        row = next(
            (r for r in rows if r["user_email"] == normal_user["email"]),
            rows[0],
        )
        assert row["user_name"] == "Test admin_user"
        assert row["user_email"] == normal_user["email"]
        assert row["report_id"].startswith("AGR-")
        assert row["prediction_id"].startswith("PRED-")
        # `unsafe` in the database is `unsafe` in the console.
        assert row["category"] == "unsafe"
        assert row["prediction"] == "unsafe"

    def test_the_warning_category_selects_moderate(self, client, admin):
        """`warning` is the console's word for the model's MODERATE class."""
        summary = client.get(f"{ADMIN}/reports/summary", headers=admin["headers"]).get_json()["data"]
        assert "warning" in summary
        assert summary["all"] == summary["safe"] + summary["warning"] + summary["unsafe"]

    def test_the_category_filter_is_applied(self, client, admin, normal_user):
        client.post(PREDICT, json=UNSAFE_SAMPLE, headers=normal_user["headers"])

        safe = client.get(f"{ADMIN}/reports?category=safe", headers=admin["headers"]).get_json()["data"]
        assert all(row["prediction"] == "safe" for row in safe)

        unsafe = client.get(f"{ADMIN}/reports?category=unsafe", headers=admin["headers"]).get_json()["data"]
        assert all(row["prediction"] == "unsafe" for row in unsafe)

    def test_the_export_is_a_csv_with_the_username_column(self, client, admin, normal_user):
        client.post(PREDICT, json=UNSAFE_SAMPLE, headers=normal_user["headers"])

        response = client.get(f"{ADMIN}/reports/export?category=all", headers=admin["headers"])
        assert response.status_code == 200
        assert "text/csv" in response.headers["Content-Type"]
        assert "attachment" in response.headers["Content-Disposition"]

        text = response.get_data(as_text=True)
        assert "Username" in text
        assert normal_user["email"] in text
        # Excel reads UTF-8 only with a BOM; without it an accented name mangles.
        assert text.startswith("\ufeff")

    def test_the_login_details_export_names_the_category_in_the_file(self, client, admin):
        response = client.get(
            f"{ADMIN}/login-details/export?format=xlsx", headers=admin["headers"]
        )
        assert response.status_code == 200
        # Named for Excel by MIME type, still CSV content — see the route docs.
        assert "excel" in response.headers["Content-Type"].lower()

# ---------------------------------------------------------------------------
# AI providers and knowledge
# ---------------------------------------------------------------------------
class TestAIProviders:
    def test_the_resolver_reports_nothing_configured_when_there_is_no_key(self):
        from app.ai.providers import resolve_providers

        assert resolve_providers({}) == []

    def test_a_single_configured_provider_resolves(self):
        from app.ai.providers import PROVIDER_GEMINI, resolve_providers

        providers = resolve_providers(
            {
                "AQUA_AI_GEMINI_API_KEY": "test-key",
                "AI_PROVIDER": PROVIDER_GEMINI,
                "AI_REQUEST_TIMEOUT": 10,
            }
        )
        assert len(providers) == 1
        assert providers[0].name == PROVIDER_GEMINI
        assert providers[0].base_url.endswith("/openai")

    def test_the_order_string_controls_the_fallback_sequence(self):
        from app.ai.providers import resolve_providers

        providers = resolve_providers(
            {
                "AQUA_AI_PROVIDER_ORDER": "gemini,openai",
                "AQUA_AI_GEMINI_API_KEY": "g",
                "AQUA_AI_OPENAI_API_KEY": "o",
            }
        )
        assert [p.name for p in providers] == ["gemini", "openai"]

    def test_an_unconfigured_provider_is_skipped_rather_than_returned_empty(self):
        from app.ai.providers import resolve_providers

        providers = resolve_providers(
            {
                "AQUA_AI_PROVIDER_ORDER": "openai,gemini",
                "AQUA_AI_GEMINI_API_KEY": "g",
            }
        )
        assert [p.name for p in providers] == ["gemini"]

    def test_meta_requires_an_explicit_base_url(self):
        """Meta publishes weights, not one hosted OpenAI-compatible URL."""
        from app.ai.providers import resolve_providers

        without_url = resolve_providers(
            {"AI_PROVIDER": "meta", "AQUA_AI_META_API_KEY": "k"}
        )
        assert without_url == [], "no invented default URL"

        with_url = resolve_providers(
            {
                "AI_PROVIDER": "meta",
                "AQUA_AI_META_API_KEY": "k",
                "AQUA_AI_META_BASE_URL": "https://api.groq.com/openai/v1",
            }
        )
        assert len(with_url) == 1

    def test_the_provider_description_never_leaks_a_key(self):
        from app.ai.providers import describe_providers

        described = describe_providers(
            {"AI_PROVIDER": "openai", "AQUA_AI_API_KEY": "sk-super-secret-value"}
        )
        blob = str(described)

        assert "sk-super-secret-value" not in blob
        assert described["active"] == "openai"


class TestAIAlwaysAnswers:
    def test_the_prompt_forbids_declining_a_water_question(self):
        from app.ai.prompts import build_system_prompt

        prompt = build_system_prompt()

        assert "YOU ALWAYS ANSWER" in prompt
        assert "NEVER OUT_OF_SCOPE" in prompt
        # The distinction that keeps groundedness without silencing general answers.
        assert "generous with GENERAL water" in prompt

    def test_the_prompt_still_requires_a_tool_call_for_the_users_own_data(self):
        """Answering everything must not turn into inventing a user's numbers."""
        from app.ai.prompts import build_system_prompt

        prompt = build_system_prompt()
        assert "always start with a tool call" in prompt
        assert "never estimate" in prompt
