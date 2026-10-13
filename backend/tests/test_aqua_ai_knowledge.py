"""Tests for the Aqua AI project knowledge base.

The two guarantees worth protecting here are:

  1. Coverage — every fact the spec names is actually in the reference, so the
     assistant is not left guessing about purpose, workflow, advantages, the
     parameters, the model, the screens, testing, hardware or the roadmap.
  2. Honesty — the reference says plainly what does NOT exist. A language model
     asked about "the sensor module" will describe one unless it is told
     otherwise, so the absence is asserted, not assumed.
"""

import pytest

from app.constants import FEATURE_NAMES

TOPIC_BLOCKS = [
    "identity",
    "project_purpose",
    "project_workflow",
    "advantages",
    "tech_stack",
    "parameters",
    "water_quality",
    "machine_learning",
    "prediction",
    "dashboard",
    "history",
    "alerts",
    "not_implemented",
    "testing",
    "future",
    "capabilities",
]


@pytest.fixture(scope="module")
def app_ctx():
    from app import create_app

    application = create_app("testing")
    with application.app_context():
        yield application


@pytest.fixture()
def topics(app_ctx):
    from app.ai.knowledge import get_topics

    return get_topics()


@pytest.fixture()
def prompt(app_ctx):
    from app.ai.prompts import build_system_prompt

    return build_system_prompt()


class TestTopicRegistry:
    def test_every_expected_topic_exists(self, topics):
        missing = [name for name in TOPIC_BLOCKS if name not in topics]
        assert missing == [], f"missing topics: {missing}"

    def test_no_topic_is_empty(self, topics):
        for name, body in topics.items():
            assert body and body.strip(), f"{name} is empty"

    def test_every_advertised_topic_resolves(self, app_ctx, topics):
        """What the tool offers must be what the registry can answer."""
        from app.utils.ai_tools import get_ai_tool_specs

        spec = {t["name"]: t for t in get_ai_tool_specs()}["explain_concept"]
        advertised = spec["parameters"]["properties"]["topic"]["enum"]

        missing = [name for name in advertised if name not in topics]
        assert missing == [], f"advertised but unanswerable: {missing}"

    @pytest.mark.parametrize(
        "alias,expected",
        [
            ("purpose", "project_purpose"),
            ("overview", "project_purpose"),
            ("workflow", "project_workflow"),
            ("benefits", "advantages"),
            ("technology", "tech_stack"),
            ("random_forest", "machine_learning"),
            ("ml", "machine_learning"),
            ("confidence", "prediction"),
            ("hardware", "not_implemented"),
            ("limitations", "not_implemented"),
            ("software_testing", "testing"),
            ("roadmap", "future"),
            ("dashboard", "dashboard"),
            ("history", "history"),
            ("alerts", "alerts"),
        ],
    )
    def test_aliases_resolve(self, app_ctx, alias, expected):
        """The assistant may pass the user's own wording, not just canonical keys."""
        from app.ai.knowledge import resolve_topic

        assert resolve_topic(alias) == expected

    def test_alias_resolution_is_case_and_space_tolerant(self, app_ctx):
        from app.ai.knowledge import resolve_topic

        assert resolve_topic("Random Forest") == "machine_learning"
        assert resolve_topic("  HARDWARE  ") == "not_implemented"
        assert resolve_topic("future-enhancements") == "future"

    def test_unknown_alias_returns_empty(self, app_ctx):
        from app.ai.knowledge import resolve_topic

        assert resolve_topic("how to build a bomb") == ""


class TestIdentity:
    def test_the_exact_identity_sentence_is_present(self, topics):
        assert (
            "You are Aqua AI, the built-in intelligent assistant of AquaGuard AI."
            in topics["identity"]
        )

    def test_identity_reaches_the_prompt(self, prompt):
        assert "You are Aqua AI, the built-in intelligent assistant of AquaGuard AI." in prompt


class TestSpecFactsAreGrounded:
    """Each fact the spec lists must be answerable from the reference."""

    def test_purpose(self, topics):
        body = topics["project_purpose"].lower()
        assert "water quality" in body
        assert "monitoring" in body
        assert "prediction" in body

    def test_all_five_parameters_named(self, topics):
        for name in FEATURE_NAMES:
            assert name in topics["parameters"], f"{name} absent from the reference"

    def test_random_forest_classifier_is_named(self, topics, prompt):
        assert "Random Forest Classifier" in topics["machine_learning"]
        # And in the prompt the model actually receives.
        assert "Random Forest Classifier" in prompt

    def test_technology_stack(self, topics):
        stack = topics["tech_stack"]
        for fact in ("React", "Vite", "Flask", "REST", "MySQL", "Random Forest"):
            assert fact in stack, f"{fact} missing from the stack reference"

    def test_three_verdicts(self, topics):
        body = topics["prediction"]
        for verdict in ("SAFE", "MODERATE", "UNSAFE"):
            assert verdict in body

    def test_every_feature_is_documented(self, topics, prompt):
        """Dashboard, prediction, history, alerts, reports, location, admin."""
        screens = topics["dashboard"]
        for feature in ("Dashboard", "Prediction History", "Alerts", "Manual Prediction",
                        "Reports", "Location Prediction", "Admin"):
            assert feature in screens, f"{feature} missing from the screens reference"
        assert "chart" in screens.lower()
        # The console's credential is the "sign in" the reference documents.
        assert "console" in screens.lower()

    def test_workflow(self, topics):
        body = topics["project_workflow"].lower()
        for stage in ("validate", "preprocess", "predict", "store", "alert"):
            assert stage in body, f"{stage} missing from the workflow"

    def test_advantages(self, topics):
        """Advantages must be specific to this system, not generic filler."""
        body = topics["advantages"].lower()
        assert len(body) > 300
        for claim in ("validation", "recorded", "alert", "account"):
            assert claim in body, f"{claim} missing from the advantages"

    def test_advantages_make_no_false_claims(self, topics):
        """An advantage list is the easiest place to overstate the product."""
        body = topics["advantages"].lower()
        for overclaim in ("real-time", "certified", "sensor", "hardware", "iot"):
            assert overclaim not in body, f"advantages claim {overclaim!r}, which is not true"

    def test_software_only_testing(self, topics):
        body = topics["testing"].lower()
        assert "no bench" in body or "entirely in software" in body
        assert "test suite" in body

    def test_future_enhancements_are_marked_unbuilt(self, topics):
        body = topics["future"].lower()
        assert "not commitments" in body or "none of them is built" in body
        assert "ideas" in body


class TestHonestyGuarantees:
    """The assistant must be able to say \"that does not exist\"."""

    def test_not_implemented_block_exists_and_is_substantial(self, topics):
        assert len(topics["not_implemented"]) > 400

    @pytest.mark.parametrize(
        "absent",
        [
            "sensor",
            "hardware",
            "Arduino",
            "Raspberry Pi",
            "IoT",
            "SMS",
            "push notification",
            "live monitoring",
        ],
    )
    def test_absent_features_are_named(self, topics, absent):
        assert absent.lower() in topics["not_implemented"].lower(), (
            f"{absent} is not listed as missing, so the assistant may invent it"
        )

    def test_no_hardware_is_stated_plainly(self, topics):
        body = topics["not_implemented"]
        assert "no sensor" in body.lower() or "There is no sensor" in body

    def test_laboratory_limitation_is_stated(self, topics, prompt):
        combined = topics["not_implemented"] + topics["testing"]

        assert "not a certified laboratory test" in combined
        # The prompt must carry the same warning to the model. It is now stated
        # by the numbered safety rules, in stronger terms than before.
        assert "certified" in prompt and "laboratory" in prompt
        assert "Never describe a prediction as a certified" in prompt
    def test_the_prompt_forbids_inventing_features(self, prompt):
        assert "Never invent a project feature" in prompt
        assert "not implemented" in prompt

    def test_the_prompt_forbids_claiming_automatic_measurement(self, prompt):
        assert "nothing is measured automatically" in prompt.lower()

    def test_not_implemented_reaches_the_prompt(self, prompt):
        # The absence list itself must be in the prompt, not only reachable via
        # a tool call, or the model can answer before ever asking for it.
        assert "FEATURES THAT DO NOT EXIST" in prompt
        assert "Raspberry Pi" in prompt


class TestExplainConceptTool:
    @pytest.mark.parametrize("topic", TOPIC_BLOCKS)
    def test_every_topic_is_answerable_through_the_tool(self, app_ctx, topic):
        from app.ai.tool_runner import execute_tool

        result = execute_tool("explain_concept", {"topic": topic}, user_id=1)
        assert result["topic"] == topic
        assert result["content"].strip()

    def test_the_tool_accepts_an_alias(self, app_ctx):
        from app.ai.tool_runner import execute_tool

        result = execute_tool("explain_concept", {"topic": "random forest"}, user_id=1)
        assert result["topic"] == "machine_learning"
        assert "Random Forest" in result["content"]

    def test_the_tool_rejects_an_unknown_topic(self, app_ctx):
        from app.ai.tool_runner import execute_tool
        from app.utils.errors import ValidationError

        with pytest.raises(ValidationError) as exc:
            execute_tool("explain_concept", {"topic": "how do I hack this"}, user_id=1)
        assert "topic" in exc.value.errors

    def test_the_tool_names_the_valid_topics_when_refusing(self, app_ctx):
        """A refusal should be actionable, not a dead end."""
        from app.ai.tool_runner import execute_tool
        from app.utils.errors import ValidationError

        with pytest.raises(ValidationError) as exc:
            execute_tool("explain_concept", {"topic": "nonsense"}, user_id=1)
        assert "not_implemented" in exc.value.errors["topic"]


class TestReferenceIntegrity:
    def test_reference_contains_no_user_data(self, app_ctx):
        """The knowledge base is static reference — never per-user facts."""
        from app.ai.knowledge import build_knowledge_context

        body = build_knowledge_context()

        # No email addresses, secrets or credentials of any kind.
        assert "@aquaguard.test" not in body
        assert "DB_PASSWORD" not in body
        assert "AQUA_AI_API_KEY" not in body
        assert "SECRET_KEY" not in body

    def test_reference_does_not_leak_file_paths(self, app_ctx):
        from app.ai.knowledge import build_knowledge_context

        body = build_knowledge_context()
        assert "C:\\" not in body
        assert "/home/" not in body
        assert ".env" not in body

    def test_parameter_ranges_match_the_validator(self, app_ctx):
        """The reference must not advertise a range the API would reject."""
        from app.ai.knowledge import get_topics
        from app.constants import FEATURE_BOUNDS

        body = get_topics()["parameters"]
        for name in FEATURE_NAMES:
            low, high = FEATURE_BOUNDS[name]
            assert f"{low} to {high}" in body, f"{name} range wrong in the reference"
