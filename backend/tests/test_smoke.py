"""Smoke tests — the app must build, import cleanly and route correctly.

These run without a live database: they verify the architecture itself
(application factory, blueprint registration, error envelope, validation
rules), which is exactly what Phase 1 delivers.
"""

import pytest

from app.constants import API_PREFIX, API_SHORT_PREFIX, FEATURE_NAMES


class TestAppFactory:
    def test_app_builds(self, app):
        assert app is not None
        assert app.name == "app"

    def test_config_is_loaded(self, app):
        assert app.config["SQLALCHEMY_DATABASE_URI"]
        assert app.config["JWT_SECRET_KEY"]
        assert app.config["BCRYPT_LOG_ROUNDS"] >= 4

    def test_root_endpoint_is_discoverable(self, client):
        response = client.get("/")
        assert response.status_code == 200
        data = response.get_json()
        assert data["name"] == "AquaGuard AI API"
        assert data["api_prefix"] == API_PREFIX


class TestBlueprintRegistration:
    """Every feature blueprint must be mounted under the API prefix."""

    EXPECTED_ROUTES = [
        (f"{API_PREFIX}/health", "GET"),
        (f"{API_PREFIX}/predictions", "POST"),
        (f"{API_PREFIX}/predictions", "GET"),
        # The step-8 predict endpoint, mounted at both the versioned prefix and
        # the stable unversioned one the frontend and the API docs use.
        (f"{API_PREFIX}/predictions/predict", "POST"),
        (f"{API_SHORT_PREFIX}/predictions/predict", "POST"),
        (f"{API_PREFIX}/predictions/history", "GET"),
        (f"{API_PREFIX}/predictions/latest", "GET"),
        (f"{API_PREFIX}/predictions/stats", "GET"),
        (f"{API_PREFIX}/dashboard/overview", "GET"),
        (f"{API_PREFIX}/dashboard/charts", "GET"),
        (f"{API_PREFIX}/dashboard/summary", "GET"),
        (f"{API_PREFIX}/dashboard/recent", "GET"),
        (f"{API_PREFIX}/dashboard/parameters", "GET"),
        (f"{API_PREFIX}/alerts", "GET"),
        (f"{API_PREFIX}/alerts/summary", "GET"),
        (f"{API_PREFIX}/alerts/read-all", "PATCH"),
        (f"{API_PREFIX}/locations/rain-alert", "GET"),
        (f"{API_SHORT_PREFIX}/locations/rain-alert", "GET"),
        (f"{API_PREFIX}/ai/chat", "POST"),
        (f"{API_PREFIX}/ai/conversations", "GET"),
        (f"{API_PREFIX}/ai/tools", "GET"),
    ]

    @pytest.mark.parametrize("rule,method", EXPECTED_ROUTES)
    def test_route_registered(self, app, rule, method):
        rules = {
            (r.rule, m)
            for r in app.url_map.iter_rules()
            for m in r.methods
            if m not in {"HEAD", "OPTIONS"}
        }
        assert (rule, method) in rules, f"{method} {rule} is not registered"


class TestErrorEnvelope:
    def test_unknown_route_returns_json_404(self, client):
        response = client.get(f"{API_PREFIX}/does-not-exist")
        assert response.status_code == 404
        body = response.get_json()
        assert body["success"] is False
        assert "message" in body

    def test_the_application_is_open(self, client):
        """No login exists, so an ordinary data route answers a bare call."""
        assert client.get(f"{API_PREFIX}/predictions").status_code == 200


class TestRemovedUserAuth:
    """The user-auth surface is GONE, not merely unused.

    Asserting the 404s matters as much as the routes above: an endpoint that is
    merely no longer called is still an endpoint, and a register URL that still
    answers 201 is a live registration flow no UI has been built to reach.
    """

    @pytest.mark.parametrize(
        "path,method",
        [
            ("/auth/register", "POST"),
            ("/auth/login", "POST"),
            ("/auth/logout", "POST"),
            ("/auth/me", "GET"),
            ("/auth/password/forgot", "POST"),
            ("/auth/password/reset", "POST"),
            ("/profile", "GET"),
            ("/profile", "PATCH"),
            ("/profile/change-password", "POST"),
        ],
    )
    def test_removed_user_auth_route_is_gone(self, app, path, method):
        rule = f"{API_PREFIX}{path}"
        for existing in app.url_map.iter_rules():
            if rule in {existing.rule} and method in (existing.methods or set()):
                pytest.fail(f"{rule} [{method}] is still mounted; user auth was removed")

    def test_the_admin_console_login_survives(self, app):
        """The one login that must remain, at BOTH console prefixes."""
        # `/api/...` and `/api/v1/...` are the two mounts the console actually
        # lives at (see `_register_blueprints`, which mounts the blueprint under
        # both deliberately). A bare `/admin/session` mount was never part of
        # the contract, so requiring it here failed a correct application.
        for prefix in (API_PREFIX, API_SHORT_PREFIX):
            rule = f"{prefix}/admin/session"
            mounted = [
                r for r in app.url_map.iter_rules()
                if r.rule == rule and "POST" in (r.methods or set())
            ]
            assert mounted, f"admin console sign-in must remain at {rule}"


class TestValidation:
    def test_valid_payload_is_coerced_and_ordered(self):
        from app.utils.validators import validate_water_quality_payload

        payload = {name: 1.0 for name in FEATURE_NAMES}
        result = validate_water_quality_payload(payload)
        assert list(result.keys()) == list(FEATURE_NAMES)
        assert all(isinstance(v, float) for v in result.values())

    def test_missing_parameters_are_reported(self):
        from app.utils.errors import ValidationError
        from app.utils.validators import validate_water_quality_payload

        with pytest.raises(ValidationError) as exc:
            validate_water_quality_payload({"ph": 7.0})

        errors = exc.value.errors
        assert "ph" not in errors
        assert len(errors) == len(FEATURE_NAMES) - 1

    def test_out_of_range_value_is_rejected(self):
        from app.utils.errors import ValidationError
        from app.utils.validators import validate_water_quality_payload

        payload = {name: 1.0 for name in FEATURE_NAMES}
        payload["ph"] = 99.0  # pH max is 14

        with pytest.raises(ValidationError) as exc:
            validate_water_quality_payload(payload)
        assert "ph" in exc.value.errors

    def test_non_numeric_value_is_rejected(self):
        from app.utils.errors import ValidationError
        from app.utils.validators import validate_water_quality_payload

        payload = {name: 1.0 for name in FEATURE_NAMES}
        payload["turbidity"] = "not-a-number"

        with pytest.raises(ValidationError) as exc:
            validate_water_quality_payload(payload)
        assert "turbidity" in exc.value.errors

    def test_email_validation(self):
        from app.utils.errors import ValidationError
        from app.utils.validators import validate_email

        assert validate_email("  User@Example.COM ") == "user@example.com"
        with pytest.raises(ValidationError):
            validate_email("not-an-email")

    def test_password_policy(self):
        from app.utils.errors import ValidationError
        from app.utils.validators import validate_password_strength

        assert validate_password_strength("aqua12345") == "aqua12345"
        with pytest.raises(ValidationError):
            validate_password_strength("short")
        with pytest.raises(ValidationError):
            validate_password_strength("nodigitshere")


class TestMLContracts:
    def test_preprocess_returns_canonical_order(self):
        from app.ml.preprocessing import preprocess_input

        # Deliberately shuffled input order.
        payload = {name: 1.0 for name in reversed(FEATURE_NAMES)}
        frame = preprocess_input(payload)
        assert list(frame.columns) == list(FEATURE_NAMES)

    def test_preprocessing_rejects_missing_features(self):
        from app.ml.preprocessing import preprocess_input
        from app.utils.errors import ValidationError

        with pytest.raises(ValidationError):
            preprocess_input({"ph": 7.0})

    def test_predictor_reports_missing_artifact_honestly(self, app_context):
        """With no trained model yet, the API must fail loudly — never guess."""
        from app.ml.model_loader import is_model_available
        from app.ml.predictor import predict
        from app.utils.errors import MLModelError

        if is_model_available():
            pytest.skip("A trained model artifact is present")

        with pytest.raises(MLModelError):
            predict({name: 1.0 for name in FEATURE_NAMES})

class TestWaterQualityPipeline:
    """The standalone ml/ 3-class pipeline must be callable from Flask."""

    def test_bridge_is_importable(self):
        from app.ml import water_quality
        assert hasattr(water_quality, "predict")
        assert hasattr(water_quality, "is_available")

    def test_predict_returns_a_known_category(self, app_context):
        from app.ml import water_quality
        if not water_quality.is_available():
            pytest.skip("Train the pipeline first: python ml/train_model.py")

        result = water_quality.predict(
            {"ph": 7.1, "turbidity": 1.2, "tds": 280.0, "temperature": 18.0, "dissolved_oxygen": 8.4}
        )
        assert result["risk_level"] in {"safe", "moderate", "unsafe"}
        assert 0.0 <= result["confidence"] <= 1.0
        assert set(result["probabilities"]) == {"safe", "moderate", "unsafe"}

class TestAquaAITools:
    def test_tool_catalogue_is_well_formed(self):
        from app.utils.ai_tools import get_ai_tool_specs, get_tool_names

        specs = get_ai_tool_specs()
        assert len(specs) > 0
        for spec in specs:
            assert {"name", "description", "parameters"} <= set(spec)
            assert "type" in spec["parameters"]

        assert len(get_tool_names()) == len(specs)

    def test_unknown_tool_is_rejected(self):
        from app.ai.tool_runner import resolve_tool
        from app.utils.errors import ForbiddenError

        with pytest.raises(ForbiddenError):
            resolve_tool("drop_all_tables")

    def test_system_prompt_mentions_every_parameter(self):
        from app.ai.prompts import build_system_prompt

        prompt = build_system_prompt()
        for name in FEATURE_NAMES:
            assert name in prompt
