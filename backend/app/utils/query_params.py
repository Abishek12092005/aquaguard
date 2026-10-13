"""Query-parameter readers shared by the list endpoints.

These exist so request parsing happens in one place and every list endpoint
degrades the same way when a client sends something malformed: an unusable
value is ignored in favour of the default, rather than becoming a 500 from a
bare `int()` cast deep inside a service.
"""

from flask import request


def parse_int_arg(name: str, default: int, *, minimum: int | None = None,
                  maximum: int | None = None) -> int:
    """Read an integer query parameter, clamped to the given bounds."""
    raw = request.args.get(name)
    if raw is None or str(raw).strip() == "":
        value = default
    else:
        try:
            value = int(str(raw).strip())
        except (TypeError, ValueError):
            value = default

    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def parse_choice_arg(name: str, allowed: tuple[str, ...], default: str | None = None):
    """Read a query parameter that must be one of a fixed set of values.

    An unrecognised value falls back to the default rather than erroring: a
    stale bookmark holding an old filter name should still show the user their
    history, not a validation failure.
    """
    raw = request.args.get(name)
    if raw is None:
        return default
    cleaned = str(raw).strip().lower()
    return cleaned if cleaned in allowed else default


def parse_search_term(name: str = "search", max_length: int = 120) -> str | None:
    """Read and normalise a free-text search term.

    Returns None when the term is absent or blank, so callers can skip the
    filtering entirely. Length is capped rather than rejected — a very long
    term simply will not match anything, and truncating it keeps the LIKE
    pattern bounded.
    """
    raw = request.args.get(name)
    if raw is None:
        return None
    cleaned = " ".join(str(raw).split())
    if not cleaned:
        return None
    return cleaned[:max_length]
