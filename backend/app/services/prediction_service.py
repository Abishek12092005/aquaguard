"""Prediction service - the core workflow of AquaGuard AI."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import case, func, or_, select

from app.constants import FEATURE_NAMES, RISK_MODERATE, RISK_SAFE, RISK_UNSAFE
from app.extensions import db
from app.ml.predictor import predict as run_model
from app.models import WaterPrediction
from app.models.mixins import utcnow
from app.utils.errors import NotFoundError, ValidationError
from app.utils.pagination import paginate_query
from app.utils.validators import parse_json_body, validate_water_quality_payload

logger = logging.getLogger(__name__)

# THE PER-USER STORAGE QUOTA (requirement: cap stored report data at 50 MB and
# erase the OLDEST records automatically once it is reached).
#
# What counts toward the quota is the STORED row data — the prediction records
# the Reports screen, its PDF downloads and the email attachments are built
# from. PDFs themselves are never stored: they are generated on demand from
# these rows, so capping the rows caps everything downstream.
#
# The per-row size is ESTIMATED rather than measured with a DB function: every
# column is a fixed-width number or a bounded varchar whose cap is known here,
# so summing the caps is exact in the worst case and cheap (one indexed query
# per insert). The estimate is deliberately generous, so the real footprint is
# smaller and the quota can never understate usage.
_STORAGE_QUOTA_BYTES = 50 * 1024 * 1024  # 50 MB, the ceiling the requirement sets
_ROW_FIXED_BYTES = 120  # numeric columns (5 params + confidence + lat/lng) + overhead
_ROW_TEXT_MAX_BYTES = (
    # Every varchar column's declared max, in characters; utf8mb4 worst case is
    # 4 bytes per character, so the estimate cannot undershoot the true size.
    (190 + 120 + 120 + 120 + 120 + 120 + 20)  # location text columns
    + 20 + 60 + 190  # prediction verdict, water_source_type, nearby_water_source
    + 40  # param_provenance
) * 4
_ROW_ESTIMATE_BYTES = _ROW_FIXED_BYTES + _ROW_TEXT_MAX_BYTES


def _enforce_storage_quota(user_id: int) -> None:
    """Delete the caller's OLDEST stored reports until they fit the 50 MB quota.

    Runs after a successful insert, on the same request: the newest reading is
    what the user just made and must never be its own victim. Deleting oldest-
    first keeps the recent history the Reports screen is built around and
    erases the stale records automatically, exactly as the requirement words
    it. A quota failure is logged, never raised — a bookkeeping miss must not
    turn a successful prediction into an error the user sees.
    """
    try:
        total = db.session.scalar(
            select(func.count()).select_from(WaterPrediction).where(
                WaterPrediction.user_id == user_id
            )
        ) or 0
        estimated = total * _ROW_ESTIMATE_BYTES
        if estimated <= _STORAGE_QUOTA_BYTES:
            return

        # Rows to retire so the estimated footprint fits under the ceiling.
        keep = max(1, _STORAGE_QUOTA_BYTES // _ROW_ESTIMATE_BYTES)
        stale = (
            db.session.scalars(
                select(WaterPrediction.id)
                .where(WaterPrediction.user_id == user_id)
                .order_by(WaterPrediction.created_at.asc(), WaterPrediction.id.asc())
                .offset(keep)
            )
            .all()
        )
        if not stale:
            return
        db.session.execute(
            WaterPrediction.__table__.delete().where(
                WaterPrediction.id.in_(stale)
            )
        )
        db.session.commit()
        logger.info(
            "Storage quota enforced: user=%s deleted=%d kept~%d rows",
            user_id, len(stale), keep,
        )
    except Exception:
        db.session.rollback()
        logger.exception("Storage quota check failed for user=%s", user_id)


# Chart ranges accepted by `get_prediction_stats`.
_RANGE_DAYS = {"7d": 7, "30d": 30, "90d": 90, "365d": 365, "1y": 365}

# Optional location metadata the Location page can attach to a prediction.
# Max lengths mirror the schema columns, so an over-long value is clamped here
# rather than failing the whole commit at the database.
_LOCATION_TEXT_FIELDS = {
    "location_name": 190,
    "location_city": 120,
    "location_area": 120,
    "location_district": 120,
    "location_state": 120,
    "location_country": 120,
    "location_pincode": 20,
    "water_source_type": 60,
    "nearby_water_source": 190,
    # PROMPT 1, E.9: the provenance the readings carried, so the stored record
    # can never be re-read as a measurement it never claimed to be.
    "param_provenance": 40,
}
_LOCATION_NUMBER_FIELDS = ("location_lat", "location_lng", "nearby_water_source_distance")


def extract_location_fields(payload: dict) -> dict:
    """Pull the optional location metadata off a prediction request body.

    Every field is optional: a prediction without a location stays valid, so
    existing callers keep working untouched. Invalid values
    are dropped rather than raising — the measured parameters are what the
    verdict depends on, and a malformed label must not hide the answer.
    """
    if not isinstance(payload, dict):
        return {}

    fields: dict[str, Any] = {}
    for name, max_length in _LOCATION_TEXT_FIELDS.items():
        raw = payload.get(name)
        if raw is None:
            continue
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            raw = str(raw)
        if not isinstance(raw, str):
            continue
        cleaned = " ".join(raw.split())[:max_length]
        if cleaned:
            fields[name] = cleaned

    for name in _LOCATION_NUMBER_FIELDS:
        raw = payload.get(name)
        if raw is None or raw == "" or isinstance(raw, bool):
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value != value or value in (float("inf"), float("-inf")):
            continue
        fields[name] = value

    return fields


def extract_district_field(payload: dict) -> str | None:
    """Read the optional district the client sends alongside the location.

    The district IS a stored column now (`water_predictions.location_district`),
    so a prediction reports the same District in History, on the Reports sheet
    and in the generated PDF. It is still returned separately because the
    Predict response echoes it beside the rest of the place, but it is no
    longer only an echo: `extract_location_fields` keeps it for the row too.
    Cleaned the same way as the other stored labels: whitespace collapsed,
    clamped to the same 120-character budget a state or country label gets.
    """
    if not isinstance(payload, dict):
        return None
    raw = payload.get("location_district")
    if raw is None:
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        raw = str(raw)
    if not isinstance(raw, str):
        return None
    cleaned = " ".join(raw.split())[:120]
    return cleaned or None


def _current_user_id() -> int:
    """The account this request's rows belong to.

    A thin re-export of `identity.current_user_id`, so every feature answers
    "who owns this" from ONE rule: a request carrying a valid bearer token acts
    as that account, and every other request acts as the shared visitor. There is
    no login to require, so a missing token is not an error here.
    """
    from app.services.identity import current_user_id

    return current_user_id()


def _serialize(prediction: WaterPrediction) -> dict[str, Any]:
    """Shape one prediction for the API, including derived fields.

    `is_safe` and `risk_level` are computed here rather than stored, so the
    verdict semantics live in one place and never drift from the stored label.
    """
    payload = prediction.to_dict()
    payload["confidence"] = float(prediction.confidence)
    for name in FEATURE_NAMES:
        payload[name] = float(getattr(prediction, name))
    for name in ("location_lat", "location_lng", "nearby_water_source_distance"):
        if payload.get(name) is not None:
            payload[name] = float(payload[name])
    payload["is_safe"] = prediction.prediction == RISK_SAFE
    payload["risk_level"] = prediction.prediction
    return payload


def _parameter_echo(features: dict[str, float]) -> dict[str, Any]:
    """Echo the parameters back with the labels, units and bounds a client needs.

    Derived from the same shared constants the validator used, so the response
    can never describe a parameter differently from the way it was validated.
    """
    from app.constants import FEATURE_BOUNDS, FEATURE_LABELS, FEATURE_UNITS

    return {
        name: {
            "label": FEATURE_LABELS[name],
            "unit": FEATURE_UNITS[name],
            "min": FEATURE_BOUNDS[name][0],
            "max": FEATURE_BOUNDS[name][1],
            "value": features[name],
        }
        for name in FEATURE_NAMES
    }


def predict_only() -> dict[str, Any]:
    """Run a prediction for the authenticated user and persist it.

    Implements the documented request flow end to end:

        request -> JWT -> validation -> preprocessing -> model
                -> prediction -> confidence -> MySQL -> response

    The verdict is whatever the trained model produced. Nothing here
    synthesises a result: when the artifact cannot be loaded the caller gets
    `MLModelError` (503) instead of a made-up answer.
    """
    # --- 1. Validate ------------------------------------------------------
    payload = parse_json_body()
    features = validate_water_quality_payload(payload)
    # Location labels ride on the same body. Invalid ones are dropped, not
    # raised: the measured parameters are what the verdict depends on, and a
    # malformed label must never hide the answer.
    location_fields = extract_location_fields(payload)
    # The district rides on the same body. It IS a stored column now, so it is
    # folded into `location_fields` (which becomes the row's columns) rather
    # than only echoed. Read through the same cleaner, so History, Reports and
    # the PDF all report the one value the client sent.
    district = extract_district_field(payload)
    if district:
        location_fields["location_district"] = district

    # --- 1b. Enforce the admin's location scope (requirement 7) ------------
    # The Location routes already block an out-of-scope search, but a caller can
    # POST straight to this endpoint with its own location labels, so the guard
    # is repeated HERE, on the backend, at the point the reading is recorded.
    # A refusal raises ForbiddenError (403) and NEVER substitutes a location.
    from app.services.location_service import enforce_prediction_scope

    enforce_prediction_scope(location_fields)

    # --- 2. Preprocess + inference ----------------------------------------
    # `run_model` performs the preprocessing and raises MLModelError (503)
    # when no artifact is installed, which the route then surfaces honestly.
    result = run_model(features)

    risk_level = result["risk_level"]
    confidence = float(result["confidence"])

    # --- 3. Persist ------------------------------------------------
    # user_id, parameters, prediction, confidence and timestamp, in one row.
    # THE PREDICTION TIME IS WRITTEN ONCE, HERE, at the instant the prediction
    # is created, and never regenerated. Every surface - History, Reports, the
    # downloaded PDF and the emailed attachment - reads this one stored
    # `created_at`, so they can never disagree about the prediction's time.
    user_id = _current_user_id()

    prediction = WaterPrediction(
        user_id=user_id,
        prediction=risk_level,
        confidence=confidence,
        created_at=utcnow(),
        **features,
        **location_fields,
    )

    try:
        db.session.add(prediction)
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("Failed to persist prediction for user=%s", user_id)
        raise

    # --- 3b. Enforce the 50 MB stored-report quota -------------------------
    # The commit above may have pushed this account past the ceiling; erase the
    # OLDEST records now, on the same request, so the quota is honoured even if
    # the user never visits a cleanup screen.
    _enforce_storage_quota(user_id)

    # --- 4. Alert on an unsafe verdict ------------------------------------
    if risk_level == RISK_UNSAFE:
        from app.services.alert_service import raise_for_prediction

        try:
            raise_for_prediction(
                prediction.id, features=features, confidence=confidence
            )
        except Exception:
            # The prediction is already committed, so a failure to raise the
            # alert must not hide the verdict the user asked for.
            logger.exception("Failed to raise alert for prediction=%s", prediction.id)

    logger.info(
        "Prediction id=%s user=%s verdict=%s confidence=%.4f",
        prediction.id,
        user_id,
        risk_level,
        confidence,
    )

    return {
        "id": prediction.id,
        "prediction": risk_level,
        "confidence": confidence,
        "parameters": _parameter_echo(features),
        "is_safe": risk_level == RISK_SAFE,
        "probabilities": result.get("probabilities")
        or {
            "safe": result.get("probability_potable"),
            "unsafe": result.get("probability_not_potable"),
        },
        "label": result.get("label"),
        "model_name": result.get("model_name"),
        "model_version": result.get("model_version"),
        "feature_contributions": result.get("feature_contributions"),
        "created_at": prediction.created_at.isoformat()
        if prediction.created_at
        else None,
        # Echo the district the caller attached. Stored on the row as well (see
        # `location_fields` above), so the result panel, History, the Reports
        # sheet and the PDF all name the same district.
        "location_district": district,
        # PROMPT 1, E.9: echo the provenance the caller attached, beside the
        # place, so the result panel can say "these readings were a dataset
        # estimate" in the same breath as the verdict.
        "param_provenance": prediction.param_provenance,
        # Echo the location metadata the caller attached, so the result panel can
        # show WHAT was tested and WHERE from the same answer. Missing when the
        # caller sent none, which keeps a location-less prediction valid.
        **location_fields,
    }


def run_prediction(
    features: dict[str, float] | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Execute the full prediction workflow.

    TWO CALLERS, ONE PATH. The Predict endpoint passes nothing, and the inputs
    are taken from the request: the JSON body and the JWT identity. Aqua AI's
    prediction tool has neither, so it passes `features` and `user_id` explicitly.

    Both then run the SAME validation, the SAME model call, the SAME
    persistence and the SAME alert logic. That is the point of these
    parameters existing: the alternative - a second pipeline for the assistant -
    is the first step towards the two disagreeing about what a reading means.

    They are optional, so every existing caller keeps working untouched.
    """
    # --- 1. Validate ------------------------------------------------------
    # The assistant's values arrive already parsed, and are re-validated here
    # rather than trusted, so both callers go through the same bounds check.
    location_fields: dict[str, Any] = {}
    if features is None:
        payload = parse_json_body()
        features = validate_water_quality_payload(payload)
        # Location metadata rides on the same body; the assistant caller has none.
        location_fields = extract_location_fields(payload)
        # The district is a stored column, so it is folded in beside the other
        # location labels and persisted with the row - not dropped on this path.
        district = extract_district_field(payload)
        if district:
            location_fields["location_district"] = district
    else:
        features = validate_water_quality_payload(dict(features))

    # --- 1b. Enforce the admin's location scope (requirement 7) -------------
    # Same guard as the model-first path: the restriction is applied on the
    # BACKEND whichever route records the prediction, and an out-of-scope place
    # is refused with a 403 rather than being silently swapped for another.
    from app.services.location_service import enforce_prediction_scope

    enforce_prediction_scope(location_fields)

    # --- 2. Inference -----------------------------------------------------
    # `run_model` raises MLModelError (503) when no artifact is trained yet,
    # which the route surfaces honestly rather than inventing a verdict.
    result = run_model(features)

    # --- 3. Persist -------------------------------------------------------
    # Only resolved from the token when the caller did not supply it: the
    # assistant's tool call has no request of its own, so it supplies `user_id`.
    if user_id is None:
        user_id = _current_user_id()

    # THE PREDICTION TIME IS WRITTEN ONCE, HERE, at the instant the prediction
    # is created. Every reader (History, Reports, the PDF, the email) reads this
    # stored value rather than a fresh clock reading, so they cannot disagree.
    prediction = WaterPrediction(
        user_id=user_id,
        prediction=result["risk_level"],
        confidence=result["confidence"],
        created_at=utcnow(),
        **features,
        **location_fields,
    )

    try:
        db.session.add(prediction)
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("Failed to persist prediction for user=%s", user_id)
        raise

    # --- 4. Alert when unsafe --------------------------------------------
    # Imported lazily to avoid a circular import (alert_service reads
    # predictions for its message).
    from app.services.alert_service import raise_for_prediction

    if result["risk_level"] == RISK_UNSAFE:
        try:
            raise_for_prediction(
                prediction.id, features=features, confidence=result["confidence"]
            )
        except Exception:
            # The prediction itself is already committed; a failure to raise the
            # alert must not roll that back or hide the result from the user.
            logger.exception("Failed to raise alert for prediction=%s", prediction.id)

    logger.info(
        "Prediction id=%s user=%s verdict=%s confidence=%.4f",
        prediction.id,
        user_id,
        result["risk_level"],
        result["confidence"],
    )

    response = _serialize(prediction)
    # Surface the extended model output (probabilities, feature contributions)
    # alongside the stored row for the result panel.
    response["probabilities"] = {
        "potable": result["probability_potable"],
        "not_potable": result["probability_not_potable"],
    }
    response["label"] = result["label"]
    response["model_name"] = result.get("model_name")
    response["model_version"] = result.get("model_version")
    response["feature_contributions"] = result.get("feature_contributions")
    return response


def list_user_predictions(
    page: int,
    per_page: int,
    risk_level: str | None = None,
    search: str | None = None,
    sort: str = 'newest',
) -> tuple[list, dict]:
    """Return a paginated page of the caller's predictions.

    Every filter is applied in SQL rather than in Python. That is correctness,
    not tidiness: filtering a single fetched page would search only the rows
    that happened to land on that page, so a user with 200 records filtering
    for 'unsafe' would get a different answer depending on which page they
    were looking at.

    The `user_id` predicate is always present and is never read from the
    request, so no combination of query parameters can widen the result set
    to another account's rows.
    """
    user_id = _current_user_id()

    query = select(WaterPrediction).where(WaterPrediction.user_id == user_id)

    # --- Risk-level filter -------------------------------------------------
    if risk_level:
        query = query.where(WaterPrediction.prediction == risk_level)

    # --- Free-text search --------------------------------------------------
    # Matches the verdict or any of the parameter readings, so a record can be
    # found by what it was or by what it measured.
    if search:
        pattern = f"%{_escape_like(search)}%"
        conditions = [WaterPrediction.prediction.like(pattern)]
        for name in FEATURE_NAMES:
            conditions.append(
                db.cast(getattr(WaterPrediction, name), db.String).like(pattern)
            )
        query = query.where(or_(*conditions))

    # --- Ordering ----------------------------------------------------------
    if sort == "oldest":
        query = query.order_by(
            WaterPrediction.created_at.asc(), WaterPrediction.id.asc()
        )
    elif sort == "confidence":
        query = query.order_by(
            WaterPrediction.confidence.desc(), WaterPrediction.id.desc()
        )
    else:
        query = query.order_by(
            WaterPrediction.created_at.desc(), WaterPrediction.id.desc()
        )

    items, meta = paginate_query(query, page, per_page)
    return [_serialize(item) for item in items], meta


def _escape_like(value: str) -> str:
    """Escape LIKE wildcards in a user-supplied search term.

    Without this, searching for `%` matches every row and `_` matches any
    single character. Harmless in practice, but it makes the search look
    broken in a way that is hard to explain to whoever reported it.
    """
    # Raw literals: a plain "\\%" here would be read as an invalid escape
    # sequence and warn every time the module is imported.
    return value.replace("\\", r"\\").replace("%", r"\%").replace("_", r"\_")


def get_latest_prediction() -> dict[str, Any] | None:
    """Return the caller's most recent prediction, or None."""
    user_id = _current_user_id()

    prediction = db.session.execute(
        select(WaterPrediction)
        .where(WaterPrediction.user_id == user_id)
        .order_by(WaterPrediction.created_at.desc(), WaterPrediction.id.desc())
        .limit(1)
    ).scalar_one_or_none()

    return _serialize(prediction) if prediction is not None else None


def get_prediction_stats(range_key: str = "30d") -> dict[str, Any]:
    """Aggregate statistics for the dashboard and analytics charts."""
    user_id = _current_user_id()

    days = _RANGE_DAYS.get(range_key, 30)
    since = datetime.now(timezone.utc) - timedelta(days=days)

    scoped = (
        WaterPrediction.user_id == user_id,
        WaterPrediction.created_at >= since,
    )

    total = db.session.execute(
        select(func.count()).select_from(WaterPrediction).where(*scoped)
    ).scalar_one()

    safe_count = db.session.execute(
        select(func.count())
        .select_from(WaterPrediction)
        .where(*scoped, WaterPrediction.prediction == RISK_SAFE)
    ).scalar_one()

    unsafe_count = db.session.execute(
        select(func.count())
        .select_from(WaterPrediction)
        .where(*scoped, WaterPrediction.prediction == RISK_UNSAFE)
    ).scalar_one()

    avg_confidence = db.session.execute(
        select(func.avg(WaterPrediction.confidence)).where(*scoped)
    ).scalar_one()

    # --- Daily trend series -----------------------------------------------
    # `func.date()` is supported by both MySQL and SQLite, so this grouping
    # works against the real schema and the test database alike.
    trend_rows = db.session.execute(
        select(
            func.date(WaterPrediction.created_at).label("day"),
            func.count(WaterPrediction.id).label("predictions"),
            func.sum(case((WaterPrediction.prediction == RISK_UNSAFE, 1), else_=0)).label(
                "unsafe"
            ),
        )
        .where(*scoped)
        .group_by(func.date(WaterPrediction.created_at))
        .order_by(func.date(WaterPrediction.created_at))
    ).all()

    trend = [
        {
            "date": row.day.isoformat() if hasattr(row.day, "isoformat") else str(row.day),
            "predictions": int(row.predictions or 0),
            "unsafe": int(row.unsafe or 0),
        }
        for row in trend_rows
    ]

    total_int = int(total or 0)
    safe_int = int(safe_count or 0)
    unsafe_int = int(unsafe_count or 0)

    return {
        "range": range_key,
        "days": days,
        "total": total_int,
        "safe": safe_int,
        "unsafe": unsafe_int,
        "moderate": total_int - safe_int - unsafe_int,
        "average_confidence": round(float(avg_confidence), 4)
        if avg_confidence is not None
        else None,
        "trend": trend,
    }


def get_prediction_counts() -> dict[str, int]:
    """The caller's verdict counts, counted in the DATABASE from real records.

    WHY THIS EXISTS SEPARATELY FROM `get_prediction_stats`. The Reports page's
    filter chips show All / Safe / Moderate / Unsafe counts, and those numbers
    must describe EVERY stored record, not a page of them. Computing them in the
    browser from the rows the page happened to fetch was wrong twice over: the
    page fetches a bounded page (`per_page: 100`), so an account with more rows
    saw a capped total, and the browser was doing arithmetic that the database
    can answer exactly.

    `get_prediction_stats` cannot be reused here because it is scoped to a TIME
    RANGE (30 days by default) for the dashboard charts; these chips describe
    the whole history, so a range would silently under-count older rows. The
    three verdicts are grouped and counted in SQL in one statement, and `all`
    is their sum rather than a fourth query.
    """
    user_id = _current_user_id()
    rows = db.session.execute(
        select(WaterPrediction.prediction, func.count(WaterPrediction.id))
        .where(WaterPrediction.user_id == user_id)
        .group_by(WaterPrediction.prediction)
    ).all()
    counts = {str(verdict): int(count) for verdict, count in rows}
    safe = counts.get(RISK_SAFE, 0)
    moderate = counts.get(RISK_MODERATE, 0)
    unsafe = counts.get(RISK_UNSAFE, 0)
    return {
        "all": safe + moderate + unsafe,
        "safe": safe,
        "moderate": moderate,
        "unsafe": unsafe,
    }


def get_prediction_by_id(prediction_id: int) -> dict[str, Any]:
    """Fetch a single prediction, enforcing ownership."""
    user_id = _current_user_id()

    prediction = db.session.execute(
        select(WaterPrediction).where(
            WaterPrediction.id == prediction_id,
            WaterPrediction.user_id == user_id,
        )
    ).scalar_one_or_none()

    if prediction is None:
        # Reported as 404 rather than 403: a caller must not be able to probe
        # which ids exist by comparing "forbidden" against "not found".
        raise NotFoundError("Prediction not found")

    return _serialize(prediction)


def delete_prediction(prediction_id: int) -> None:
    """Delete a prediction owned by the caller."""
    user_id = _current_user_id()

    prediction = db.session.execute(
        select(WaterPrediction).where(
            WaterPrediction.id == prediction_id,
            WaterPrediction.user_id == user_id,
        )
    ).scalar_one_or_none()

    if prediction is None:
        raise NotFoundError("Prediction not found")

    try:
        db.session.delete(prediction)
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("Failed to delete prediction=%s", prediction_id)
        raise

    logger.info("Prediction deleted: id=%s user=%s", prediction_id, user_id)
