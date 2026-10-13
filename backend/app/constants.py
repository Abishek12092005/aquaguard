"""Shared literals: API surface, enumerations and the ML feature contract.

Centralising these values means the routes, services, ML pipeline and the
frontend form all agree on the same vocabulary without duplication.
"""

# --------------------------------------------------------------------------
# API surface
# --------------------------------------------------------------------------
# Versioned, canonical API prefix.
API_PREFIX = "/api/v1"

# Unversioned prefix used for a small set of stable paths that clients and
# monitors should not have to re-point when the API version moves.
API_SHORT_PREFIX = "/api"

# --------------------------------------------------------------------------
# User / auth
# --------------------------------------------------------------------------
ROLE_USER = "user"
ROLE_ADMIN = "admin"
VALID_ROLES = (ROLE_USER, ROLE_ADMIN)

ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"

# --------------------------------------------------------------------------
# Aqua AI empty-state wording
# --------------------------------------------------------------------------
# A user-specific question with no matching rows must be answered with a fixed,
# honest sentence rather than an improvised one. The tools return these strings
# as `message`, and the system prompt quotes them, so the assistant cannot drift
# into inventing a number when the account simply has nothing yet.
AI_NO_PREDICTIONS = "Your account does not have any prediction records yet."
AI_NO_ALERTS = "Your account does not have any alerts yet."

# --------------------------------------------------------------------------
# Water quality
# --------------------------------------------------------------------------
# Canonical feature order for the Random Forest model. Preprocessing,
# validation, storage and inference all iterate this tuple, so they cannot
# drift apart. It matches the columns of `water_predictions` exactly.
FEATURE_NAMES = (
    "ph",
    "turbidity",
    "tds",
    "temperature",
    "dissolved_oxygen",
)

# Physical plausibility bounds used by request validation. Values outside
# these ranges are rejected as bad input rather than silently clamped, and the
# database enforces the same limits with CHECK constraints.
FEATURE_BOUNDS = {
    "ph": (0.0, 14.0),
    "turbidity": (0.0, 1000.0),
    "tds": (0.0, 50000.0),
    "temperature": (-5.0, 100.0),
    "dissolved_oxygen": (0.0, 20.0),
}

# Human-readable units, reused by the API response and the frontend labels.
FEATURE_UNITS = {
    "ph": "pH",
    "turbidity": "NTU",
    "tds": "mg/L",
    "temperature": "\u00b0C",
    "dissolved_oxygen": "mg/L",
}

# Display labels for the prediction form, kept beside the units so the two
# cannot diverge.
FEATURE_LABELS = {
    "ph": "pH",
    "turbidity": "Turbidity",
    "tds": "Total Dissolved Solids",
    "temperature": "Temperature",
    "dissolved_oxygen": "Dissolved Oxygen",
}

# --------------------------------------------------------------------------
# Potability / prediction outcome
# --------------------------------------------------------------------------
RISK_SAFE = "safe"
RISK_MODERATE = "moderate"
RISK_UNSAFE = "unsafe"
RISK_LEVELS = (RISK_SAFE, RISK_MODERATE, RISK_UNSAFE)

# The stored vocabulary matches the CHECK constraint on water_predictions:
# a model class of 1 means safe, 0 means unsafe.
CLASS_LABELS = {0: RISK_UNSAFE, 1: RISK_SAFE}

# Confidence thresholds that map a model score onto a risk level.
RISK_CONFIDENCE_THRESHOLD_HIGH = 0.85
RISK_CONFIDENCE_THRESHOLD_MEDIUM = 0.65

# --------------------------------------------------------------------------
# Alerts
# --------------------------------------------------------------------------
# These three values match the CHECK constraint on alerts.type exactly.
ALERT_WATER_UNSAFE = "water_unsafe"
ALERT_THRESHOLD_EXCEED = "threshold_exceeded"
ALERT_SYSTEM = "system"
ALERT_TYPES = (ALERT_WATER_UNSAFE, ALERT_THRESHOLD_EXCEED, ALERT_SYSTEM)

# --------------------------------------------------------------------------
# Aqua AI
# --------------------------------------------------------------------------
AI_ROLE_USER = "user"
AI_ROLE_ASSISTANT = "assistant"
AI_ROLE_SYSTEM = "system"

AI_MESSAGE_STATUS_OK = "ok"
AI_MESSAGE_STATUS_ERROR = "error"
AI_MESSAGE_STATUS_BLOCKED = "blocked"

# --------------------------------------------------------------------------
# Pagination
# --------------------------------------------------------------------------
DEFAULT_PAGE = 1
DEFAULT_PER_PAGE = 20
MAX_PER_PAGE = 100

# --------------------------------------------------------------------------
# HTTP messages reused across blueprints
# --------------------------------------------------------------------------
MSG_INVALID_PAYLOAD = "Request payload is missing or not valid JSON"
MSG_VALIDATION_FAILED = "Validation failed"
MSG_NOT_FOUND = "Resource not found"
MSG_FORBIDDEN = "You do not have access to this resource"
