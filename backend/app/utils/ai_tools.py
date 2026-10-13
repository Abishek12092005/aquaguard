"""Controlled application tools exposed to Aqua AI.

The assistant may not touch the database or the router directly. It can only
*request* one of these declaratively-specified tools, which the frontend or a
service then executes under the user's own permissions. Keeping the schema in
one place prevents the model from inventing capabilities that do not exist.
"""

from typing import Any
from app.constants import FEATURE_NAMES
# ---------------------------------------------------------------------------
# Navigation targets
# ---------------------------------------------------------------------------
# The ONLY routes the assistant may send a user to. The model picks a tool; it
# never supplies a URL. A tool name maps to exactly one route here, so there is
# no parameter through which an arbitrary or external URL could be injected
# (no "open this link" capability, no redirect, no javascript: target).
NAVIGATION_TARGETS: dict[str, str] = {
    "navigate_to_dashboard": "/dashboard",
    "navigate_to_prediction": "/predict",
    "navigate_to_history": "/history",
    "navigate_to_alerts": "/alerts",
    # Rainy Alerts answers a weather question rather than a water-quality one,
    # and it is a real screen a visitor may legitimately ask for.
    "navigate_to_rainy_alerts": "/rainy-alerts",
    # Reports is a real screen with its own downloads, so "go to reports" must
    # land on it rather than being answered as if it did not exist.
    "navigate_to_reports": "/reports",
    # The Home walkthrough and the admin console are real screens a user may
    # name. They are part of the SAME allow-list as the rest, so "go to home"
    # and "go to admin" resolve to exactly these routes and nothing free-text
    # can become a URL.
    "navigate_to_home": "/home",
    "navigate_to_admin": "/admin",
}

# Tools that run on the client (React Router) rather than on the server. The
# service returns these as NAVIGATE actions instead of executing them.
CLIENT_SIDE_TOOLS = frozenset(NAVIGATION_TARGETS)

# Reverse lookup: route -> the tool that opens it. Used when the natural-language
# router (not the model) decides on the navigation, so the recorded action still
# names a real catalogued tool.
NAVIGATION_TOOL_FOR_TARGET: dict[str, str] = {
    target: name for name, target in NAVIGATION_TARGETS.items()
}

# Human-readable screen names, for the spoken half of a navigation reply.
NAVIGATION_LABELS: dict[str, str] = {
    "/dashboard": "Dashboard",
    "/predict": "Water Quality Prediction",
    "/history": "Prediction History",
    "/alerts": "Alerts",
    "/rainy-alerts": "Rainy Alerts",
    "/reports": "Reports",
    "/home": "Home",
    "/admin": "Admin Console",
}


def _navigation_spec(name: str, description: str) -> dict[str, Any]:
    """Build a navigation tool spec.

    No `parameters` are declared: the destination is fixed by the tool's own
    identity. A model cannot pass a route, so a hallucinated "https://evil" or
    "javascript:..." target is not expressible — there is nowhere to put it.

    The description is kept to ONE short line per tool. These schemas are re-sent
    on every single turn, and the long "use for requests such as ..." lists that
    used to be here were both the largest and the most redundant part of the
    request: the system prompt already explains the destinations and maps the
    user's wording onto them. Shortening them makes every request smaller and
    faster without removing anything the model needs.
    """
    return {
        "name": name,
        "description": description,
        "parameters": {"type": "object", "properties": {}},
    }

AI_TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "get_prediction_summary",
        "description": (
            "Counts for the signed-in user: total predictions, how many were safe, "
            "unsafe and moderate, average confidence, and open alerts. Use this for "
            "any counting question such as 'how many predictions have I made?', "
            "'how many unsafe predictions do I have?' or 'how many safe ones?'."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "explain_parameter",
        "description": (
            "Explain what ONE water quality parameter means: its plain-language "
            "meaning, the healthy/normal range, and what being below or above that "
            "range indicates. Use this for pH, turbidity, TDS (total dissolved "
            "solids), temperature or dissolved oxygen - including when the user asks "
            "about one of them by itself."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "parameter": {"type": "string", "enum": list(FEATURE_NAMES)}
            },
            "required": ["parameter"],
        },
    },
    {
        "name": "run_prediction",
        "description": (
            "Run a water quality prediction on the user's behalf. Only call this "
            "once every required parameter has been supplied by the user."
        ),
        "parameters": {
            "type": "object",
            "properties": {name: {"type": "number"} for name in FEATURE_NAMES},
            "required": list(FEATURE_NAMES),
        },
    },
    {
        "name": "explain_concept",
        "description": (
            "Explain how AquaGuard works, or a water-quality or machine-learning "
            "concept, from the project's own reference documentation. Use this "
            "instead of answering from memory whenever the question is about this "
            "system, the model, or water-quality science."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "enum": [
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
                        "page_guides",
                        "downloads",
                        "not_implemented",
                        "testing",
                        "future",
                        "capabilities",
                    ],
                    "description": (
                        "Which reference topic to explain. Use not_implemented "
                        "whenever the user asks about a capability such as hardware, "
                        "notifications or exports."
                    ),
                }
            },
            "required": ["topic"],
        },
    },
]

# ---------------------------------------------------------------------------
# Application navigation tools
# ---------------------------------------------------------------------------
# One tool per screen, each with a hard-coded destination. The assistant asks to
# navigate; the frontend does the navigating through React Router.
AI_TOOL_SPECS.extend(
    [
        _navigation_spec("navigate_to_dashboard", "Open the Dashboard screen."),
        _navigation_spec(
            "navigate_to_prediction",
            "Open the Predict screen - the ONLY place a new prediction is run.",
        ),
        _navigation_spec(
            "navigate_to_history", "Open the Prediction History screen."
        ),
        _navigation_spec("navigate_to_alerts", "Open the Alerts screen."),
        _navigation_spec("navigate_to_rainy_alerts", "Open the Rainy Alerts screen."),
        _navigation_spec("navigate_to_home", "Open the Home walkthrough screen."),
        _navigation_spec(
            "navigate_to_admin", "Open the Admin Console sign-in screen."
        ),
        _navigation_spec(
            "navigate_to_reports",
            "Open the Reports screen, which has the CSV and PDF downloads.",
        ),
    ]
)

# ---------------------------------------------------------------------------
# Canonical data tools named by the tool contract
# ---------------------------------------------------------------------------
# These are the explicitly-defined, server-executed tools. Every one of them is
# scoped to the authenticated user inside its handler; none accepts a user id,
# a table name, a column name, a raw query or an arbitrary identifier.
AI_TOOL_SPECS.extend(
    [
        {
            "name": "get_dashboard_summary",
            "description": (
                "Retrieve the signed-in user's Dashboard numbers: total "
                "predictions, the safe/moderate/unsafe split, average confidence "
                "and unread alerts. Use this for 'how many', 'what's my average' "
                "and any question about their overall record."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
        {
            "name": "get_latest_prediction",
            "description": (
                "Retrieve the signed-in user's most recent water-quality prediction "
                "(verdict and confidence). Use this when the user asks about their "
                "latest or last result. If they ask you to EXPLAIN it, use "
                "explain_latest_prediction instead."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
        {
            "name": "explain_latest_prediction",
            "description": (
                "Explain the signed-in user's most recent prediction from the values "
                "stored with it: the verdict, the confidence, and each measured "
                "parameter in plain language. Use this whenever the user asks you to "
                "explain, interpret or break down their latest result. It returns the "
                "exact wording to use, including any safety warning and the "
                "laboratory disclaimer - do not restate the numbers from memory."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
        {
            "name": "get_prediction_history",
            "description": (
                "Retrieve a page of the signed-in user's prediction history, newest "
                "first. Optionally filter by verdict or page through results."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                        "description": "How many records to return.",
                    },
                    "page": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Page number, 1-based.",
                    },
                    "risk_level": {
                        "type": "string",
                        "enum": ["safe", "moderate", "unsafe"],
                        "description": "Optional verdict filter.",
                    },
                },
            },
        },
        {
            "name": "get_prediction_by_id",
            "description": (
                "Retrieve one of the signed-in user's predictions by its id. A "
                "prediction belonging to another account is reported as not found."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prediction_id": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Id of the prediction to fetch.",
                    }
                },
                "required": ["prediction_id"],
            },
        },
        {
            "name": "get_alerts",
            "description": (
                "Retrieve the signed-in user's alerts, newest first. Optionally "
                "limit to unread alerts only."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "unread_only": {
                        "type": "boolean",
                        "description": "Return only unread alerts when true.",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                        "description": "How many alerts to return.",
                    },
                },
            },
        },
        {
            "name": "get_usage_counters",
            "description": (
                "How much this application has been used: the number of water "
                "readings submitted and how many alerts are still unread. Use it "
                "for \"how many predictions are there\", \"how many alerts\", or any "
                "question about totals rather than about a specific record. There "
                "are no user accounts, so no personal details are involved."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
        {
            "name": "get_report_list",
            "description": (
                "Build a list of the user's water-quality REPORTS for the Reports "
                "screen, optionally filtered by verdict, together with the download "
                "actions for that list (CSV and PDF). Use this whenever the user "
                "asks for their reports, a list of results to download, or \"safe / "
                "moderate / unsafe list\". Pass risk_level to filter. The returned "
                "`reports` array MUST be shown as a list, and its `downloads` array "
                "MUST be shown as buttons - do not simply describe them in prose."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "risk_level": {
                        "type": "string",
                        "enum": ["safe", "moderate", "unsafe", "all"],
                        "description": (
                            "Which reports to list. Use 'all' when the user does not "
                            "name a verdict. A named verdict is exactly the "
                            "filter the Reports screen applies."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                        "description": "How many reports to list.",
                    },
                },
            },
        },
    ]
)


def get_ai_tool_specs() -> list[dict[str, Any]]:
    """Return the tool catalogue sent to the LLM."""
    return AI_TOOL_SPECS


def get_tool_names() -> list[str]:
    """Return just the tool identifiers, for validation of model output."""
    return [tool["name"] for tool in AI_TOOL_SPECS]



def get_navigation_target(tool_name: str) -> str | None:
    """Return the fixed route for a navigation tool, or None if not one.

    The lookup is a static dict read, never a value derived from model output, so
    an unrecognised name yields None and the caller drops the action rather than
    trusting anything the model produced.
    """
    return NAVIGATION_TARGETS.get(tool_name)



# ===========================================================================
# Natural-language navigation
# ===========================================================================
# Maps what a user actually types ("open water quality test", "take me to my
# alerts") onto the same fixed targets as the tools above. Two reasons this
# exists rather than leaving it entirely to the model:
#
#   1. Determinism. "Open water quality test" is not obviously the Predict
#      screen; a model may hesitate, or pick History. A keyword table makes the
#      documented phrases work every time.
#   2. It only ever returns a value from NAVIGATION_TARGETS. There is no path
#      from free text to an arbitrary route — the result is a lookup, not a
#      string built out of what the user typed.
#
# Each entry is (phrase, target). Phrases are matched on the normalised message,
# longest first, so "previous predictions" beats a bare "predictions".
NAVIGATION_PHRASES: list[tuple[str, str]] = [
    # --- Dashboard ---
    ("go to dashboard", NAVIGATION_TARGETS["navigate_to_dashboard"]),
    ("open dashboard", NAVIGATION_TARGETS["navigate_to_dashboard"]),
    ("open the dashboard", NAVIGATION_TARGETS["navigate_to_dashboard"]),
    ("show dashboard", NAVIGATION_TARGETS["navigate_to_dashboard"]),
    ("show me the dashboard", NAVIGATION_TARGETS["navigate_to_dashboard"]),
    ("take me to dashboard", NAVIGATION_TARGETS["navigate_to_dashboard"]),
    ("take me to the dashboard", NAVIGATION_TARGETS["navigate_to_dashboard"]),
    ("go to the dashboard", NAVIGATION_TARGETS["navigate_to_dashboard"]),
    ("dashboard", NAVIGATION_TARGETS["navigate_to_dashboard"]),
    ("overview", NAVIGATION_TARGETS["navigate_to_dashboard"]),
    # --- Home (its own screen, distinct from the dashboard) ---
    ("go to home page", NAVIGATION_TARGETS["navigate_to_home"]),
    ("go to the home page", NAVIGATION_TARGETS["navigate_to_home"]),
    ("go to home", NAVIGATION_TARGETS["navigate_to_home"]),
    ("take me home", NAVIGATION_TARGETS["navigate_to_home"]),
    ("take me to home", NAVIGATION_TARGETS["navigate_to_home"]),
    ("take me to the home page", NAVIGATION_TARGETS["navigate_to_home"]),
    ("open home", NAVIGATION_TARGETS["navigate_to_home"]),
    ("open the home page", NAVIGATION_TARGETS["navigate_to_home"]),
    ("show home", NAVIGATION_TARGETS["navigate_to_home"]),
    ("home page", NAVIGATION_TARGETS["navigate_to_home"]),
    # --- Admin console ---
    ("go to admin page", NAVIGATION_TARGETS["navigate_to_admin"]),
    ("go to the admin page", NAVIGATION_TARGETS["navigate_to_admin"]),
    ("go to admin", NAVIGATION_TARGETS["navigate_to_admin"]),
    ("open admin", NAVIGATION_TARGETS["navigate_to_admin"]),
    ("open the admin page", NAVIGATION_TARGETS["navigate_to_admin"]),
    ("open the admin console", NAVIGATION_TARGETS["navigate_to_admin"]),
    ("take me to admin", NAVIGATION_TARGETS["navigate_to_admin"]),
    ("take me to the admin page", NAVIGATION_TARGETS["navigate_to_admin"]),
    ("show admin", NAVIGATION_TARGETS["navigate_to_admin"]),
    ("admin page", NAVIGATION_TARGETS["navigate_to_admin"]),
    ("admin panel", NAVIGATION_TARGETS["navigate_to_admin"]),
    ("admin console", NAVIGATION_TARGETS["navigate_to_admin"]),
    ("admin", NAVIGATION_TARGETS["navigate_to_admin"]),
    # --- Predict (the water-quality test screen) ---
    ("open water quality test", NAVIGATION_TARGETS["navigate_to_prediction"]),
    ("open the water quality test", NAVIGATION_TARGETS["navigate_to_prediction"]),
    ("water quality test", NAVIGATION_TARGETS["navigate_to_prediction"]),
    ("start a water quality test", NAVIGATION_TARGETS["navigate_to_prediction"]),
    ("take me to prediction", NAVIGATION_TARGETS["navigate_to_prediction"]),
    ("take me to the prediction", NAVIGATION_TARGETS["navigate_to_prediction"]),
    ("take me to predictions", NAVIGATION_TARGETS["navigate_to_prediction"]),
    ("go to prediction", NAVIGATION_TARGETS["navigate_to_prediction"]),
    ("go to predict", NAVIGATION_TARGETS["navigate_to_prediction"]),
    ("go to the predict", NAVIGATION_TARGETS["navigate_to_prediction"]),
    ("open predict", NAVIGATION_TARGETS["navigate_to_prediction"]),
    ("go to the prediction", NAVIGATION_TARGETS["navigate_to_prediction"]),
    ("open prediction", NAVIGATION_TARGETS["navigate_to_prediction"]),
    ("open the prediction page", NAVIGATION_TARGETS["navigate_to_prediction"]),
    ("open the prediction screen", NAVIGATION_TARGETS["navigate_to_prediction"]),
    ("show prediction", NAVIGATION_TARGETS["navigate_to_prediction"]),
    ("new prediction", NAVIGATION_TARGETS["navigate_to_prediction"]),
    ("new test", NAVIGATION_TARGETS["navigate_to_prediction"]),
    ("test my water", NAVIGATION_TARGETS["navigate_to_prediction"]),
    ("check my water", NAVIGATION_TARGETS["navigate_to_prediction"]),
    ("run a prediction", NAVIGATION_TARGETS["navigate_to_prediction"]),
    ("prediction page", NAVIGATION_TARGETS["navigate_to_prediction"]),
    ("prediction screen", NAVIGATION_TARGETS["navigate_to_prediction"]),
    ("predict page", NAVIGATION_TARGETS["navigate_to_prediction"]),
    # --- History ---
    ("open my previous predictions", NAVIGATION_TARGETS["navigate_to_history"]),
    ("open previous predictions", NAVIGATION_TARGETS["navigate_to_history"]),
    ("previous predictions", NAVIGATION_TARGETS["navigate_to_history"]),
    ("my previous predictions", NAVIGATION_TARGETS["navigate_to_history"]),
    ("past predictions", NAVIGATION_TARGETS["navigate_to_history"]),
    ("prediction history", NAVIGATION_TARGETS["navigate_to_history"]),
    ("open prediction history", NAVIGATION_TARGETS["navigate_to_history"]),
    ("open my history", NAVIGATION_TARGETS["navigate_to_history"]),
    ("take me to history", NAVIGATION_TARGETS["navigate_to_history"]),
    ("take me to the history", NAVIGATION_TARGETS["navigate_to_history"]),
    ("go to history", NAVIGATION_TARGETS["navigate_to_history"]),
    ("show history", NAVIGATION_TARGETS["navigate_to_history"]),
    ("show my history", NAVIGATION_TARGETS["navigate_to_history"]),
    ("show me my history", NAVIGATION_TARGETS["navigate_to_history"]),
    ("old results", NAVIGATION_TARGETS["navigate_to_history"]),
    ("past results", NAVIGATION_TARGETS["navigate_to_history"]),
    ("my records", NAVIGATION_TARGETS["navigate_to_history"]),
    ("history", NAVIGATION_TARGETS["navigate_to_history"]),
    # --- Alerts ---
    ("take me to alerts", NAVIGATION_TARGETS["navigate_to_alerts"]),
    ("take me to the alerts", NAVIGATION_TARGETS["navigate_to_alerts"]),
    ("take me to my alerts", NAVIGATION_TARGETS["navigate_to_alerts"]),
    ("go to alerts", NAVIGATION_TARGETS["navigate_to_alerts"]),
    ("open my alerts", NAVIGATION_TARGETS["navigate_to_alerts"]),
    ("open the alerts", NAVIGATION_TARGETS["navigate_to_alerts"]),
    ("show alerts", NAVIGATION_TARGETS["navigate_to_alerts"]),
    ("show my alerts", NAVIGATION_TARGETS["navigate_to_alerts"]),
    ("show me my alerts", NAVIGATION_TARGETS["navigate_to_alerts"]),
    ("alerts page", NAVIGATION_TARGETS["navigate_to_alerts"]),
    ("alerts screen", NAVIGATION_TARGETS["navigate_to_alerts"]),
    ("notifications", NAVIGATION_TARGETS["navigate_to_alerts"]),
    ("warnings", NAVIGATION_TARGETS["navigate_to_alerts"]),
    ("alerts", NAVIGATION_TARGETS["navigate_to_alerts"]),
    # --- Rainy Alerts ---
    ("take me to rainy alerts", NAVIGATION_TARGETS["navigate_to_rainy_alerts"]),
    ("go to rainy alerts", NAVIGATION_TARGETS["navigate_to_rainy_alerts"]),
    ("open rainy alerts", NAVIGATION_TARGETS["navigate_to_rainy_alerts"]),
    ("show rainy alerts", NAVIGATION_TARGETS["navigate_to_rainy_alerts"]),
    ("rainy alerts", NAVIGATION_TARGETS["navigate_to_rainy_alerts"]),
    ("rain alerts", NAVIGATION_TARGETS["navigate_to_rainy_alerts"]),
    ("rainy alert", NAVIGATION_TARGETS["navigate_to_rainy_alerts"]),
    ("weather alerts", NAVIGATION_TARGETS["navigate_to_rainy_alerts"]),
    # --- Reports ---
    # Matched longest-phrase-first, so
    # "go to reports" cannot be caught by a shorter phrase from another section.
    ("take me to reports", NAVIGATION_TARGETS["navigate_to_reports"]),
    ("take me to the reports", NAVIGATION_TARGETS["navigate_to_reports"]),
    ("take me to my reports", NAVIGATION_TARGETS["navigate_to_reports"]),
    ("go to reports", NAVIGATION_TARGETS["navigate_to_reports"]),
    ("go to the reports", NAVIGATION_TARGETS["navigate_to_reports"]),
    ("open reports", NAVIGATION_TARGETS["navigate_to_reports"]),
    ("open the reports", NAVIGATION_TARGETS["navigate_to_reports"]),
    ("open my reports", NAVIGATION_TARGETS["navigate_to_reports"]),
    ("show reports", NAVIGATION_TARGETS["navigate_to_reports"]),
    ("show my reports", NAVIGATION_TARGETS["navigate_to_reports"]),
    ("show me my reports", NAVIGATION_TARGETS["navigate_to_reports"]),
    ("show me the reports", NAVIGATION_TARGETS["navigate_to_reports"]),
    ("show me reports", NAVIGATION_TARGETS["navigate_to_reports"]),
    ("reports page", NAVIGATION_TARGETS["navigate_to_reports"]),
    ("reports screen", NAVIGATION_TARGETS["navigate_to_reports"]),
    ("download reports", NAVIGATION_TARGETS["navigate_to_reports"]),
    ("my reports", NAVIGATION_TARGETS["navigate_to_reports"]),
    ("reports", NAVIGATION_TARGETS["navigate_to_reports"]),
]

# Verbs that signal the user wants to go somewhere. A phrase match alone is not
# enough: "tell me about the history of water testing" must not navigate, so a
# navigation verb (or an explicit screen noun) has to be present too.
_NAVIGATION_VERBS = (
    "go to",
    "open",
    "take me to",
    "show me",
    "show",
    "navigate to",
    "navigate",
    "bring me to",
    "jump to",
    "switch to",
    "view",
    "see my",
    "display",
)

# Matches are tried longest-first so a specific phrase wins over its own suffix.
_NAVIGATION_PHRASES_SORTED = sorted(NAVIGATION_PHRASES, key=lambda p: -len(p[0]))


def resolve_navigation_intent(message: str) -> str | None:
    """Return a route if the message is a navigation request, else None.

    Deliberately conservative. The result is always a value from
    `NAVIGATION_TARGETS`; free text cannot become a route. A question such as
    "what does history mean?" contains the word but no navigation verb and is
    left to the model to answer normally.
    """
    if not isinstance(message, str) or not message.strip():
        return None

    # Normalise: lowercase, collapse whitespace, strip trailing punctuation so
    # "Open the dashboard." matches. A leading greeting is tolerated.
    text = " ".join(message.lower().split()).strip(" .!?,")
    for greeting in ("hey ", "hi ", "hello ", "please ", "can you ", "could you "):
        if text.startswith(greeting):
            text = text[len(greeting):].strip()

    has_verb = any(verb in text for verb in _NAVIGATION_VERBS)

    for phrase, target in _NAVIGATION_PHRASES_SORTED:
        if phrase not in text:
            continue
        # A bare screen noun ("alerts", "profile", "history", "dashboard",
        # "home", "admin") is accepted on its own only when the whole message
        # is essentially that noun — otherwise a passing mention would hijack a
        # real question.
        if phrase in {"alerts", "profile", "history", "dashboard", "overview",
                      "notifications", "warnings", "reports", "home", "admin",
                      "admin page", "admin panel", "admin console",
                      "home page", "prediction", "predictions"}:
            if not has_verb and text not in {phrase, f"my {phrase}", f"the {phrase}"}:
                continue
        elif not has_verb and phrase not in text:
            continue
        return target

    return None


# ===========================================================================
# Deterministic "explain my prediction" intent
# ===========================================================================
# The same reasoning as the navigation router above, applied to a question
# rather than a destination: "explain my latest prediction" is a documented
# capability, and it must work whether or not the model decides to call the
# tool. This resolves the intent server-side so the tool runs either way.
#
# It is deliberately narrow. It matches only when BOTH an explain verb and a
# reference to the user's own latest result are present, so "explain pH to me"
# and "what is a prediction?" are left to the model rather than being hijacked.
EXPLAIN_TOOL_NAME = "explain_latest_prediction"

_EXPLAIN_VERBS = ("explain", "interpret", "break down", "breakdown", "walk me through")

# Words that anchor the request to the caller's OWN most recent record. A bare
# "the prediction" does not qualify: without an ownership cue this could be a
# general question about what a prediction is.
_LATEST_CUES = (
    "my latest",
    "my last",
    "my most recent",
    "my recent",
    "latest prediction",
    "latest result",
    "latest reading",
    "latest test",
    "last prediction",
    "last result",
    "last reading",
    "last test",
    "recent prediction",
    "recent result",
)

# A question that is plainly about the concept rather than the caller's row.
_EXPLAIN_EXCLUSIONS = (
    "what is a prediction",
    "what does prediction mean",
    "how does prediction work",
    "how does the prediction work",
    "what does confidence mean",
    "explain the model",
    "explain machine learning",
    "explain the random forest",
)


def resolve_explain_intent(message: str) -> str | None:
    """Return the explanation tool name if the message asks to explain the
    caller's own latest prediction, else None.

    Returns a fixed constant, never a value built from the user's text, so this
    cannot be used to name an arbitrary tool. It resolves to `None` for concept
    questions, which the model answers from the knowledge base.
    """
    if not isinstance(message, str) or not message.strip():
        return None

    text = " ".join(message.lower().split()).strip(" .!?,")
    for greeting in ("hey ", "hi ", "hello ", "please ", "can you ", "could you "):
        if text.startswith(greeting):
            text = text[len(greeting):].strip()

    if any(phrase in text for phrase in _EXPLAIN_EXCLUSIONS):
        return None

    has_verb = any(verb in text for verb in _EXPLAIN_VERBS)
    has_cue = any(cue in text for cue in _LATEST_CUES)

    return EXPLAIN_TOOL_NAME if has_verb and has_cue else None
