"""Alert service: raise and manage unsafe-water alerts."""

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.constants import (
    ALERT_SYSTEM,
    ALERT_WATER_UNSAFE,
    FEATURE_LABELS,
    FEATURE_NAMES,
    FEATURE_UNITS,
)
from app.extensions import db
from app.models import Alert, WaterPrediction
from app.models.mixins import utcnow
from app.utils.errors import NotFoundError, ValidationError
from app.utils.pagination import paginate_query

logger = logging.getLogger(__name__)


def _current_user_id() -> int:
    """The account this request's alerts belong to.

    Delegates to the one shared rule in `app.services.identity`: a request with a
    valid token acts as that account, and anything else acts as the shared
    visitor. Alerts therefore stay owned and filtered exactly as before.
    """
    from app.services.identity import current_user_id

    return current_user_id()


def _derive_status(alert: Alert) -> str:
    """Map the stored state onto a single UI status string.

    Three states, in the order they are reached: "active" (unread),"acknowledged"
    (read but still standing) and "resolved" (dealt with).

    Resolution is checked FIRST because it is the stronger claim: an alert is
    always read by the time it is resolved, so testing "is_read" first reported
    every resolved alert as merely acknowledged, which is the bug this fixes.
    """
    if alert.resolved_at is not None:
        return "resolved"
    if not alert.is_read:
        return "active"
    return "acknowledged"


def _serialize(alert: Alert) -> dict[str, Any]:
    """Shape one alert for the API."""
    payload = alert.to_dict()
    payload["is_read"] = bool(alert.is_read)
    payload["status"] = _derive_status(alert)
    # Severity is a presentation concern: every unsafe-water alert is high.
    payload["severity"] = "high" if alert.type == ALERT_WATER_UNSAFE else "info"
    return payload


def _build_message(
    features: dict[str, float] | None,
    confidence: float | None,
) -> str:
    """Human-readable explanation naming the readings behind the verdict.

    Wording is produced here (not in the template) so the alert body and the
    prediction detail view describe a sample identically.
    """
    if not features:
        return "An unsafe water quality reading was recorded."

    parts = [
        f"{FEATURE_LABELS.get(name, name)} {features[name]} {FEATURE_UNITS.get(name, '')}".strip()
        for name in FEATURE_NAMES
        if name in features
    ]
    reading = ", ".join(parts)

    if confidence is not None:
        return (
            f"Unsafe water detected with {confidence * 100:.1f}% confidence. "
            f"Readings: {reading}."
        )
    return f"Unsafe water detected. Readings: {reading}."


def raise_for_prediction(
    prediction_id: int,
    reasons: list[str] | None = None,
    features: dict[str, float] | None = None,
    confidence: float | None = None,
) -> dict[str, Any] | None:
    """Create an alert for an unsafe prediction; return None when safe.

    Called by `prediction_service.run_prediction` after the prediction row is
    committed, so the alert always has a valid `prediction_id` to reference.
    """
    prediction = db.session.get(WaterPrediction, prediction_id)
    if prediction is None:
        raise NotFoundError("Prediction not found")

    # Only an unsafe verdict raises an alert. `moderate` is deliberately quiet:
    # it is a "watch this", not something that should page the user.
    if prediction.prediction != "unsafe":
        return None
    # --- Duplicate prevention ---------------------------------------------
    # One alert per prediction, always. Without this, any retry or repeated call
    # for the same row would page the user again for a reading they have already
    # been warned about, and the unread badge would climb on its own.
    existing = db.session.execute(
        select(Alert).where(Alert.prediction_id == prediction.id).limit(1)
    ).scalar_one_or_none()
    if existing is not None:
        logger.info(
            "Alert already exists id=%s for prediction=%s; not raising another",
            existing.id,
            prediction_id,
        )
        return _serialize(existing)

    message = _build_message(features or prediction.features(), confidence)
    if reasons:
        message = f"{message} Reasons: {', '.join(reasons)}."

    alert = Alert(
        user_id=prediction.user_id,
        prediction_id=prediction.id,
        type=ALERT_WATER_UNSAFE,
        message=message,
        is_read=False,
    )

    db.session.add(alert)
    try:
        db.session.commit()
    except IntegrityError:
        # The check above and this insert are not one atomic step, so two
        # concurrent requests for the same prediction can both pass the check.
        # The unique index is what actually guarantees one alert per prediction;
        # losing that race is not an error, it just means the other request won.
        db.session.rollback()
        winner = db.session.execute(
            select(Alert).where(Alert.prediction_id == prediction.id).limit(1)
        ).scalar_one_or_none()
        if winner is None:
            raise
        logger.info(
            "Lost the race for prediction=%s; reusing alert id=%s",
            prediction_id,
            winner.id,
        )
        return _serialize(winner)

    logger.info("Alert raised id=%s for prediction=%s", alert.id, prediction_id)
    return _serialize(alert)


def list_user_alerts(
    page: int,
    per_page: int,
    status: str | None = None,
    severity: str | None = None,
) -> tuple[list, dict]:
    """Return a filtered, paginated page of the caller's alerts."""
    user_id = _current_user_id()

    query = select(Alert).where(Alert.user_id == user_id)

    # Each filter is exclusive and matches `_derive_status`, so the counts on the
    # filter chips and the rows behind them are the same partition of the data.
    if status == "active":
        query = query.where(Alert.is_read.is_(False), Alert.resolved_at.is_(None))
    elif status == "resolved":
        query = query.where(Alert.resolved_at.is_not(None))
    elif status in ("acknowledged", "read"):
        query = query.where(Alert.is_read.is_(True), Alert.resolved_at.is_(None))

    if severity:
        # severity maps back onto type: 'high' -> unsafe-water alerts.
        wanted = ALERT_WATER_UNSAFE if severity == "high" else ALERT_SYSTEM
        query = query.where(Alert.type == wanted)

    query = query.order_by(Alert.created_at.desc(), Alert.id.desc())

    items, meta = paginate_query(query, page, per_page)
    return [_serialize(item) for item in items], meta


def get_alert_summary() -> dict[str, Any]:
    """Counters by status and type, for the notification bell."""
    user_id = _current_user_id()

    total = db.session.execute(
        select(func.count()).select_from(Alert).where(Alert.user_id == user_id)
    ).scalar_one()

    # Actionable = unread AND not resolved. An alert that has been resolved must
    # stop asking for attention even if the read flag somehow lagged behind, and
    # deriving the badge from one source of truth here is what keeps the bell, the
    # sidebar badge and the page tiles agreeing with each other.
    unread = db.session.execute(
        select(func.count())
        .select_from(Alert)
        .where(
            Alert.user_id == user_id,
            Alert.is_read.is_(False),
            Alert.resolved_at.is_(None),
        )
    ).scalar_one()

    resolved = db.session.execute(
        select(func.count())
        .select_from(Alert)
        .where(Alert.user_id == user_id, Alert.resolved_at.is_not(None))
    ).scalar_one()

    unsafe_water = db.session.execute(
        select(func.count())
        .select_from(Alert)
        .where(Alert.user_id == user_id, Alert.type == ALERT_WATER_UNSAFE)
    ).scalar_one()

    total_int = int(total or 0)
    unread_int = int(unread or 0)
    resolved_int = int(resolved or 0)

    return {
        "total": total_int,
        # The bell badge reads `unread`. It is a count of what still needs doing,
        # not a historical count — see the comment on the query above.
        "unread": unread_int,
        "read": total_int - unread_int,
        "active": unread_int,
        "acknowledged": total_int - unread_int - resolved_int,
        "resolved": resolved_int,
        "by_type": {
            "water_unsafe": int(unsafe_water or 0),
            "system": total_int - int(unsafe_water or 0),
        },
    }


def mark_alert_read(alert_id: int) -> dict[str, Any]:
    """
    Mark one owned alert as read, and report whether that changed anything.
    Backs `PATCH /alerts/<id>/read`. Idempotent on purpose: marking an alert
    that is already read is a success, not a conflict, so a client retrying a
    request it never saw the answer to does not get an error for its trouble.

    Ownership is enforced in `_fetch_owned`, so another account's alert is
    """
    alert = _fetch_owned(alert_id)

    was_unread = not alert.is_read
    if was_unread:
        alert.is_read = True
        db.session.commit()
        logger.info("Alert marked read: id=%s user=%s", alert_id, alert.user_id)

    payload = _serialize(alert)
    # Lets the client skip refetching the unread count: a repeat call changed
    # nothing, so there is nothing new to show.
    payload["changed"] = was_unread
    return payload

def mark_all_alerts_read() -> dict[str, Any]:
    """Mark every unread alert the caller owns as read."""
    user_id = _current_user_id()

    unread = (
        db.session.execute(
            select(Alert).where(Alert.user_id == user_id, Alert.is_read.is_(False))
        )
        .scalars()
        .all()
    )

    for alert in unread:
        alert.is_read = True
    if unread:
        db.session.commit()
        logger.info("Marked %s alerts read for user=%s", len(unread), user_id)

    return {"updated": len(unread)}


def acknowledge_alert(alert_id: int) -> dict[str, Any]:
    """Mark an owned alert as acknowledged (read)."""
    alert = _fetch_owned(alert_id)

    if not alert.is_read:
        alert.is_read = True
        db.session.commit()
        logger.info("Alert acknowledged: id=%s", alert_id)

    return _serialize(alert)


def resolve_alert(alert_id: int) -> dict[str, Any]:
    """Mark an owned alert as resolved, and persist that.

    Sets `resolved_at` - a real column - rather than only writing a `status`
    string into the response. Resolving also marks the alert read, because an
    alert cannot be dealt with and unread at the same time.

    Idempotent: resolving an already-resolved alert keeps the ORIGINAL timestamp
    rather than overwriting it. The time it was dealt with is a fact about the
    past, and re-stamping it would make "how long was this open?" answer
    differently depending on whether the user pressed the button twice.
    """
    alert = _fetch_owned(alert_id)

    if alert.resolved_at is None:
        alert.resolved_at = utcnow()
    alert.is_read = True
    db.session.commit()
    logger.info("Alert resolved: id=%s", alert_id)

    return _serialize(alert)


def unresolve_alert(alert_id: int) -> dict[str, Any]:
    """Reopen a resolved alert.

    The counterpart to `resolve_alert`, and the reason resolve is safe to offer
    as a plain button: a mis-click is one press to undo, rather than something
    the user has to live with. `is_read` is deliberately NOT reset - reopening is
    about the work still to do, not about pretending the alert was never seen.
    """
    alert = _fetch_owned(alert_id)

    if alert.resolved_at is not None:
        alert.resolved_at = None
        db.session.commit()
        logger.info("Alert reopened: id=%s", alert_id)

    return _serialize(alert)

def _fetch_owned(alert_id: int) -> Alert:
    """Load an alert the caller owns, or raise NotFoundError."""
    user_id = _current_user_id()

    alert = db.session.execute(
        select(Alert).where(Alert.id == alert_id, Alert.user_id == user_id)
    ).scalar_one_or_none()

    if alert is None:
        raise NotFoundError("Alert not found")

    return alert
