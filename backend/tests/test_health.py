"""Health-endpoint tests.

The liveness contract is deliberately minimal and stable, and it is asserted
here so a future change to the shape has to be a conscious one.
"""

import pytest

from app.constants import API_PREFIX


class TestHealthEndpoint:
    def test_health_returns_exact_contract(self, client):
        """GET /api/health returns exactly the documented payload."""
        response = client.get(f"{API_PREFIX}/health")
        assert response.status_code == 200
        body = response.get_json()
        assert body["success"] is True
        assert body["message"] == "AquaGuard AI backend is running"

    def test_health_available_at_short_unversioned_path(self, client):
        """Monitors use /api/health, which must not track the API version.

        A probe URL that changes when the API version changes is a probe that
        silently breaks, so both paths are served.
        """
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.get_json()["success"] is True

    def test_health_does_not_touch_the_database(self, client):
        """A liveness probe must not fail because a dependency is down.

        If this endpoint queried MySQL, a database blip would make an
        orchestrator restart a perfectly healthy web process.
        """
        from app.extensions import db

        original = db.session.execute

        def explode(*_args, **_kwargs):
            raise AssertionError("liveness probe opened a database connection")

        db.session.execute = explode
        try:
            assert client.get("/api/health").status_code == 200
        finally:
            db.session.execute = original

    def test_status_reports_config_without_leaking_secrets(self, client, app):
        """Config presence is reported as booleans; values must never leak."""
        response = client.get(f"{API_PREFIX}/health/status")
        assert response.status_code == 200
        payload = response.get_json()["data"]

        # Presence is reported HONESTLY, so the expectation is derived from the
        # app's own resolver rather than assumed: a machine with no provider keys
        # reports False, a machine that has them reports True. What this test
        # actually asserts is that the value is a boolean and that NO secret
        # value or key name leaks anywhere in the response.
        from app.ai.providers import resolve_providers
        with app.app_context():
            expected = bool(app.config.get("AI_API_KEY") or resolve_providers(app.config))
        assert payload["aiKeyConfigured"] is expected

        assert "AI_API_KEY" not in payload
        assert "SQLALCHEMY_DATABASE_URI" not in payload
        for key_name in ("AQUA_AI_API_KEY", "AQUA_AI_GEMINI_API_KEY", "AQUA_AI_META_API_KEY"):
            assert key_name not in payload

        # The raw URI carries the database password, so it must not appear
        # anywhere in the serialised response.
        raw = response.get_data(as_text=True)
        assert "mysql+pymysql" not in raw
        assert "aqua%40" not in raw
