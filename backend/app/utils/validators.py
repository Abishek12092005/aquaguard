"""Input validation for requests.

Validation is explicit and side-effect free: it either returns a clean,
type-coerced value or raises `ValidationError` listing every problem found, so
the client can highlight all offending fields at once rather than making the
user fix them one submit at a time.
"""

import re

from app.constants import FEATURE_BOUNDS, FEATURE_LABELS, FEATURE_NAMES, MSG_INVALID_PAYLOAD
from app.utils.errors import BadRequestError, ValidationError

# Deliberately permissive. The only truly reliable email test is delivery; this
# rejects obvious typos (no @, no domain, no TLD) without rejecting valid but
# unusual addresses. Over-strict patterns are a common source of support
# tickets from users with legitimate addresses.
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")

# Domains that can NEVER receive internet mail, so a code or notice sent to them
# always bounces.
#
# `.local` (mDNS) is the one that turns up in practice: `abishek@aquaguard.local`
# is exactly the kind of address a developer types to get past a registration
# form, and it then becomes a mailbox that silently swallows every password-reset
# code -- the provider accepts the message and later returns "Address not found".
# `.invalid` and `.localhost` are the same class and cannot resolve either.
#
# `.example` and `.test` are deliberately NOT listed: both are formally reserved,
# but they are the standard placeholders that test suites and seed data use, and
# blocking them would reject fixtures rather than real mistakes. The mail service
# still refuses to SEND to any of these, so nothing bounces either way.
NON_DELIVERABLE_TLDS = (".local", ".invalid", ".localhost")

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128  # bcrypt silently truncates beyond 72 bytes
MAX_NAME_LENGTH = 120


def validate_name(name: str) -> str:
    """Normalise and validate a display name."""
    if not isinstance(name, str) or not name.strip():
        raise ValidationError("Name is required", {"name": "Name is required"})

    cleaned = " ".join(name.split())  # collapse repeated/odd whitespace

    if len(cleaned) < 2:
        raise ValidationError(
            "Name is too short", {"name": "Must be at least 2 characters"}
        )
    if len(cleaned) > MAX_NAME_LENGTH:
        raise ValidationError(
            "Name is too long",
            {"name": f"Must be {MAX_NAME_LENGTH} characters or fewer"},
        )

    return cleaned


def validate_email(email: str) -> str:
    """Normalise and validate an email address.

    Lowercased and trimmed. Since the database collation is case-insensitive,
    normalising here means the application and the unique index agree about
    whether two addresses are the same account.
    """
    if not isinstance(email, str) or not email.strip():
        raise ValidationError("Email is required", {"email": "Email is required"})

    cleaned = email.strip().lower()

    if len(cleaned) > 190:
        raise ValidationError(
            "Email is too long", {"email": "Must be 190 characters or fewer"}
        )
    if not EMAIL_RE.match(cleaned):
        raise ValidationError(
            "Email format is invalid", {"email": "Enter a valid email address"}
        )

    _tld = cleaned.rsplit("@", 1)[-1].lower()
    if any(_tld.endswith(reserved) for reserved in NON_DELIVERABLE_TLDS):
        raise ValidationError(
            "Email cannot receive mail",
            {
                "email": (
                    "That domain cannot receive email. Use a real address such as "
                    "one at gmail.com."
                )
            },
        )

    return cleaned


def validate_password_strength(password: str) -> str:
    """Enforce the password policy before bcrypt hashing.

    All violations are reported together, so the user sees the full policy once
    rather than discovering it one rule per attempt.
    """
    problems = []

    if not isinstance(password, str) or not password:
        raise ValidationError("Password is required", {"password": "Password is required"})

    if len(password) < MIN_PASSWORD_LENGTH:
        problems.append(f"Must be at least {MIN_PASSWORD_LENGTH} characters")
    elif len(password) > MAX_PASSWORD_LENGTH:
        problems.append(f"Must be {MAX_PASSWORD_LENGTH} characters or fewer")
    else:
        if not re.search(r"[A-Za-z]", password):
            problems.append("Must include at least one letter")
        if not re.search(r"\d", password):
            problems.append("Must include at least one number")

    if problems:
        raise ValidationError(
            "Password does not meet requirements", {"password": problems}
        )

    return password


def validate_water_quality_payload(payload: dict) -> dict:
    """Validate and coerce the water quality parameters.

    Returns a dict keyed by `FEATURE_NAMES` in canonical order with every value
    as a float — exactly what the preprocessing step expects.

    Parameter metadata (labels, units, bounds) is derived from the shared
    constants, so this function and the frontend form cannot disagree about
    what a valid reading is.
    """
    if not isinstance(payload, dict):
        raise ValidationError("Payload must be a JSON object")

    errors: dict[str, str] = {}
    cleaned: dict[str, float] = {}

    for feature in FEATURE_NAMES:
        label = FEATURE_LABELS.get(feature, feature)

        if feature not in payload:
            errors[feature] = f"{label} is required"
            continue

        raw = payload[feature]
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            errors[feature] = f"{label} is required"
            continue

        # bool is a subclass of int in Python, and True would otherwise become
        # a perfectly valid 1.0. Rejected explicitly.
        if isinstance(raw, bool):
            errors[feature] = f"{label} must be a number"
            continue

        try:
            value = float(raw)
        except (TypeError, ValueError):
            errors[feature] = f"{label} must be a number"
            continue

        if value != value or value in (float("inf"), float("-inf")):  # NaN / inf
            errors[feature] = f"{label} must be a real number"
            continue

        low, high = FEATURE_BOUNDS[feature]
        if not (low <= value <= high):
            errors[feature] = f"{label} must be between {low} and {high}"
            continue

        cleaned[feature] = value

    if errors:
        raise ValidationError("One or more parameters are invalid", errors)

    # Re-emitted in canonical model order: dict preserves insertion order, and
    # the order must never depend on the caller's key order.
    return {feature: cleaned[feature] for feature in FEATURE_NAMES}


def parse_json_body(required: bool = True) -> dict:
    """Safely read a JSON request body."""
    from flask import request

    body = request.get_json(silent=True)
    if body is None:
        if required:
            raise BadRequestError(MSG_INVALID_PAYLOAD)
        return {}
    if not isinstance(body, dict):
        raise BadRequestError("Request payload must be a JSON object")
    return body

def validate_prediction_request() -> dict:
    """Read the request body and validate it as water-quality parameters.

    The single entry point used by every prediction route, so the request flow
    (parse -> validate) can never diverge between endpoints.
    """
    return validate_water_quality_payload(parse_json_body())
