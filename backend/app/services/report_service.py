"""Report queries for the admin console: predictions joined to their owner.

THE JOIN IS THE POINT. The requirement is that the console's results are
attached to a person, not to a bare user id — so every row carries `user_name` and
`user_email` from a single joined query. Fetching the name per row in the client
would be both an N+1 request pattern and a way for the two to disagree.

CATEGORY NAMES. The console speaks in `safe` / `warning` / `unsafe`, while the
database stores `safe` / `moderate` / `unsafe`. "Warning" is the console's word
for the model's MODERATE class; the mapping lives here, in one place, so the
filter chips, the counts and the export cannot drift apart.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select

from app.extensions import db
from app.models import User, WaterPrediction

logger = logging.getLogger(__name__)

# Console category -> the stored verdict it selects.
#
# `warning` maps to `moderate`: the class the model uses for "not clearly safe,
# not clearly unsafe". A filter named after the stored value would be accurate
# and useless — nobody looks for "moderate" results, they look for the ones that
# need watching.
CATEGORY_TO_VERDICT: dict[str, str | None] = {
    "all": None,
    "safe": "safe",
    "warning": "moderate",
    "unsafe": "unsafe",
}

CATEGORY_LABELS: dict[str, str] = {
    "all": "All results",
    "safe": "Safe results",
    "warning": "Warning results",
    "unsafe": "Unsafe results",
}


def _scope_predicate():
    """A WHERE fragment restricting predictions to the configured scope.

    PROMPT 13, REQUIREMENTS 5 AND 10. When an admin narrows the scope, the rows
    from OUTSIDE it must stop being visible in the console's reports - but they
    must NOT be deleted. Restricting on READ is the whole of requirement 10: a
    prediction taken before the scope narrowed is a real measurement that still
    exists, and destroying it would be a far worse answer than hiding it.

    ROWS WITH NO RECORDED LOCATION ARE STILL SHOWN, and this is deliberate
    rather than a convenience. A prediction submitted from the parameter-only
    path has no location at all - requirement 9 explicitly keeps that feature
    available - so excluding unlocated rows here would silently delete those
    results from the admin's view, which is data loss by another name and would
    contradict the requirement that says the manual path stays usable. Those rows
    are also the ones an admin most needs to see: they are the predictions no
    geographic check ever covered.

    NOTE `func.trim(NULL)` IS NULL IN SQL, not an empty string, so the raw
    column would never satisfy the "no location" half of the test and those rows
    would still vanish. Coalescing the TRIMMED value to '' is what makes that
    branch reachable.

    Returns None when no scope is configured, so the caller can leave its
    statement untouched.
    """
    try:
        from app.services.admin_service import get_location_scope

        scope = get_location_scope() or {}
        mode = (scope.get("mode") or "").strip().lower()
        if mode == "state":
            wanted = (scope.get("state") or "").strip().casefold()
            if not wanted:
                return None
            recorded = func.lower(
                func.coalesce(func.trim(WaterPrediction.location_state), "")
            )
            return or_(recorded == wanted, recorded == "")
        if mode == "country":
            wanted = (scope.get("country") or "").strip().casefold()
            if not wanted:
                return None
            recorded = func.lower(
                func.coalesce(func.trim(WaterPrediction.location_country), "")
            )
            return or_(recorded == wanted, recorded == "")
        return None
    except Exception:  # noqa: BLE001 - a scope read failure must not blank the console
        logger.warning("Report listing: location scope could not be read")
        return None


def _base_statement(category: str | None, search: str | None, start: str | None, end: str | None):
    """The joined, filtered select shared by the list and the export."""
    verdict = CATEGORY_TO_VERDICT.get((category or "all").lower(), None)

    statement = select(WaterPrediction, User.name, User.email).join(
        User, WaterPrediction.user_id == User.id
    )

    if verdict:
        statement = statement.where(WaterPrediction.prediction == verdict)

    if search:
        needle = f"%{search.strip()}%"
        statement = statement.where(
            or_(User.name.ilike(needle), User.email.ilike(needle))
        )

    if start:
        statement = statement.where(WaterPrediction.created_at >= _parse_day(start))
    if end:
        # `< end + 1 day`, so a filter ending "today" includes today's rows rather
        # than stopping at midnight and silently dropping them.
        statement = statement.where(WaterPrediction.created_at < _parse_day(end, True))

    # PROMPT 13: applied LAST, after every other filter, so it restricts what the
    # other filters return rather than interacting with them.
    scope_predicate = _scope_predicate()
    if scope_predicate is not None:
        statement = statement.where(scope_predicate)

    return statement.order_by(
        WaterPrediction.created_at.desc(), WaterPrediction.id.desc()
    )


def _row_to_dict(prediction: WaterPrediction, name: str | None, email: str | None) -> dict[str, Any]:
    """One report row, with its identifiers and its owner.

    LOCATION IS SHOWN AS A PLACE, WITHOUT THE EXACT COORDINATES. An administrator
    reviewing results needs to see where a sample came from ("Karaikudi, Tamil
    Nadu") so they can spot patterns and follow up, but the precise latitude and
    longitude are the user's private position. `place_dict()` supplies the coarse
    labels and the water source; the raw coordinates are never placed on this row.
    """
    payload = prediction.to_dict()
    # Drop the exact position: `to_dict()` carries it for the OWNER's own
    # endpoints, but this row is read by an administrator, not the owner.
    payload.pop("location_lat", None)
    payload.pop("location_lng", None)

    created = prediction.created_at
    stamp = created.strftime("%Y%m%d") if created else "00000"

    payload["user_name"] = name or "—"
    payload["user_email"] = email or "—"
    # The identifiers the report is quoted by. Derived rather than stored, so
    # they cannot drift from the row they name — see the frontend helper, which
    # renders the same two strings.
    payload["report_id"] = f"AGR-{stamp}-{str(prediction.id).zfill(5)}"
    payload["prediction_id"] = f"PRED-{str(prediction.id).zfill(5)}"
    # The console's category word, so the UI can label a row without re-deriving
    # the mapping.
    payload["category"] = {
        "safe": "safe",
        "moderate": "warning",
        "unsafe": "unsafe",
    }.get(prediction.prediction, "unknown")
    return payload


def list_unsafe_predictions(
    page: int = 1,
    per_page: int = 25,
    *,
    search: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """THE UNSAFE PREDICTION HISTORY: only rows the model judged `unsafe`.

    FILTERED IN SQL, NOT IN SOFTWARE. `WaterPrediction.prediction == "unsafe"` is
    part of the WHERE clause, so the database returns unsafe rows and nothing
    else - it is not a page of mixed rows that the caller then sifts. That is
    what makes the total in `meta` the real count of unsafe readings rather than
    the count of unsafe readings that happened to be on the fetched page.

    NO RECORD IS INVENTED. Every column comes from a stored prediction row; the
    console renders exactly what the database holds, or says "Not Available".

    THE ADMIN'S LOCATION SCOPE IS APPLIED LAST, exactly as it is for the reports
    list, so this section can never surface readings from outside the configured
    area that the rest of the console is restricted to.
    """
    statement = (
        select(WaterPrediction, User.name, User.email)
        .join(User, WaterPrediction.user_id == User.id)
        .where(WaterPrediction.prediction == "unsafe")
    )

    if search:
        needle = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                User.name.ilike(needle),
                User.email.ilike(needle),
                WaterPrediction.location_name.ilike(needle),
                WaterPrediction.location_city.ilike(needle),
                WaterPrediction.location_district.ilike(needle),
                WaterPrediction.location_state.ilike(needle),
                WaterPrediction.location_country.ilike(needle),
                WaterPrediction.location_pincode.ilike(needle),
            )
        )

    if start:
        statement = statement.where(WaterPrediction.created_at >= _parse_day(start))
    if end:
        statement = statement.where(WaterPrediction.created_at < _parse_day(end, True))

    scope_predicate = _scope_predicate()
    if scope_predicate is not None:
        statement = statement.where(scope_predicate)

    statement = statement.order_by(
        WaterPrediction.created_at.desc(), WaterPrediction.id.desc()
    )

    total = db.session.execute(
        select(func.count()).select_from(statement.subquery())
    ).scalar_one()

    per_page = max(1, min(int(per_page or 25), 100_000))
    page = max(1, int(page or 1))
    rows = db.session.execute(
        statement.limit(per_page).offset((page - 1) * per_page)
    ).all()

    items = [_row_to_dict(prediction, name, email) for prediction, name, email in rows]

    meta = {
        "page": page,
        "per_page": per_page,
        "total": int(total or 0),
        "pages": (int(total or 0) + per_page - 1) // per_page if per_page else 0,
    }
    return items, meta


def list_reports(
    page: int = 1,
    per_page: int = 25,
    *,
    category: str | None = None,
    search: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """A filtered, paged page of report rows, each with its username."""
    statement = _base_statement(category, search, start, end)

    total = db.session.execute(
        select(func.count()).select_from(statement.subquery())
    ).scalar_one()

    per_page = max(1, min(int(per_page or 25), 100_000))
    page = max(1, int(page or 1))
    rows = db.session.execute(
        statement.limit(per_page).offset((page - 1) * per_page)
    ).all()

    items = [_row_to_dict(prediction, name, email) for prediction, name, email in rows]

    meta = {
        "page": page,
        "per_page": per_page,
        "total": int(total or 0),
        "pages": (int(total or 0) + per_page - 1) // per_page if per_page else 0,
    }
    return items, meta


def category_summary(start: str | None = None, end: str | None = None) -> dict[str, Any]:
    """Counts per category, for the filter chips.

    Counted in the database rather than by fetching rows and counting in Python:
    the chips show these numbers before any rows are loaded, so they cannot
    depend on a page of data.
    """
    statement = select(WaterPrediction.prediction, func.count()).group_by(
        WaterPrediction.prediction
    )
    if start:
        statement = statement.where(WaterPrediction.created_at >= _parse_day(start))
    if end:
        statement = statement.where(WaterPrediction.created_at < _parse_day(end, True))

    # PROMPT 13: the chips must count the SAME rows the list will show. A chip
    # that counted hidden out-of-scope rows would promise a total the list cannot
    # deliver, which reads as rows going missing rather than as a restriction.
    scope_predicate = _scope_predicate()
    if scope_predicate is not None:
        statement = statement.where(scope_predicate)

    counts = {verdict: int(count) for verdict, count in db.session.execute(statement).all()}

    safe = counts.get("safe", 0)
    warning = counts.get("moderate", 0)
    unsafe = counts.get("unsafe", 0)

    return {
        "all": safe + warning + unsafe,
        "safe": safe,
        "warning": warning,
        "unsafe": unsafe,
        "labels": CATEGORY_LABELS,
    }


def _parse_day(value: str, end_of_day: bool = False) -> datetime:
    """Parse `YYYY-MM-DD` (or a full timestamp) into an aware UTC datetime."""
    text = str(value).strip()
    try:
        stamp = (
            datetime.fromisoformat(text.replace("Z", "+00:00"))
            if ("T" in text or "'" in text)
            else datetime.fromisoformat(f"{text}T00:00:00")
        )
    except ValueError:
        stamp = datetime.now(timezone.utc)

    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    if end_of_day and "T" not in text:
        # The exclusive upper bound is the last instant of the day.
        stamp = stamp.replace(hour=23, minute=59, second=59, microsecond=999)
    return stamp
