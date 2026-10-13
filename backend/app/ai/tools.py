"""Handlers for the Aqua AI controlled tool catalogue."""

import logging
from typing import Any

from sqlalchemy import func, select

from app.constants import (
    AI_NO_ALERTS,
    AI_NO_PREDICTIONS,
    FEATURE_BOUNDS,
    FEATURE_LABELS,
    FEATURE_NAMES,
    FEATURE_UNITS,
    RISK_LEVELS,
    RISK_SAFE,
    RISK_UNSAFE,
)
from app.extensions import db
from app.models import Alert, WaterPrediction
from app.utils.errors import ValidationError

logger = logging.getLogger(__name__)

_REGISTERED = False


# --------------------------------------------------------------------------
# Handlers
# --------------------------------------------------------------------------
def _get_prediction_summary(user_id: int = None) -> dict[str, Any]:
    """Totals, potable/unsafe counts and average confidence for the caller."""
    total = db.session.execute(
        select(func.count())
        .select_from(WaterPrediction)
        .where(WaterPrediction.user_id == user_id)
    ).scalar_one()

    safe = db.session.execute(
        select(func.count())
        .select_from(WaterPrediction)
        .where(WaterPrediction.user_id == user_id, WaterPrediction.prediction == RISK_SAFE)
    ).scalar_one()

    unsafe = db.session.execute(
        select(func.count())
        .select_from(WaterPrediction)
        .where(WaterPrediction.user_id == user_id, WaterPrediction.prediction == RISK_UNSAFE)
    ).scalar_one()

    avg_conf = db.session.execute(
        select(func.avg(WaterPrediction.confidence)).where(WaterPrediction.user_id == user_id)
    ).scalar_one()

    return {
        "total": int(total or 0),
        "safe": int(safe or 0),
        "unsafe": int(unsafe or 0),
        "moderate": int(total or 0) - int(safe or 0) - int(unsafe or 0),
        "average_confidence": round(float(avg_conf), 4) if avg_conf is not None else None,
    }


def _get_recent_predictions(limit: int = 5, user_id: int = None) -> dict[str, Any]:
    """The caller's most recent predictions."""
    limit = max(1, min(int(limit or 5), 20))

    rows = db.session.execute(
        select(WaterPrediction)
        .where(WaterPrediction.user_id == user_id)
        .order_by(WaterPrediction.created_at.desc(), WaterPrediction.id.desc())
        .limit(limit)
    ).scalars().all()

    return {
        "count": len(rows),
        "predictions": [
            {
                "id": row.id,
                "prediction": row.prediction,
                "confidence": float(row.confidence),
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "values": {name: float(getattr(row, name)) for name in FEATURE_NAMES},
            }
            for row in rows
        ],
    }


def _explain_parameter(parameter: str, user_id: int = None) -> dict[str, Any]:
    """Explain one water quality parameter: meaning, normal range, and what
    reading outside that range indicates.

    TWO RANGES, DELIBERATELY. `valid_range` is the span the API will ACCEPT
    (pH 0-14) - the physical scale. `normal_range` is the band that is actually
    HEALTHY for drinking water (pH 6.5-8.5). They are different numbers, and the
    user asking "what is a normal pH?" means the second one. Conflating them would
    tell someone that pH 1 is "within range", which is exactly the mistake this
    split prevents. The `below_normal` / `above_normal` sentences are what the
    reading means on either side, so the answer is usable rather than just numeric.
    """
    if parameter not in FEATURE_NAMES:
        raise ValidationError(
            "Unknown parameter",
            {"parameter": f"Must be one of: {', '.join(FEATURE_NAMES)}"},
        )

    low, high = FEATURE_BOUNDS[parameter]
    normal = _NORMAL_RANGES[parameter]
    return {
        "parameter": parameter,
        "label": FEATURE_LABELS.get(parameter, parameter),
        "unit": FEATURE_UNITS.get(parameter, ""),
        "valid_range": [low, high],
        "normal_range": [normal["low"], normal["high"]],
        "normal_range_text": f"{normal['low']} to {normal['high']} {FEATURE_UNITS.get(parameter, '')}".strip(),
        "below_normal": normal["below"],
        "above_normal": normal["above"],
        "description": _PARAMETER_DESCRIPTIONS.get(
            parameter, f"{FEATURE_LABELS.get(parameter, parameter)} is a measured water quality parameter."
        ),
    }


def _list_active_alerts(user_id: int = None) -> dict[str, Any]:
    """The caller's currently active (unread) alerts."""
    rows = db.session.execute(
        select(Alert)
        .where(Alert.user_id == user_id, Alert.is_read.is_(False))
        .order_by(Alert.created_at.desc())
        .limit(20)
    ).scalars().all()

    return {
        "count": len(rows),
        "alerts": [
            {
                "id": row.id,
                "type": row.type,
                "message": row.message,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
    }


def _run_prediction(user_id: int = None, **features) -> dict[str, Any]:
    """Run a prediction on the user's behalf with the supplied parameters."""
    from app.services.prediction_service import _serialize
    from app.ml.predictor import predict as run_model

    # Reuse the same validator the REST endpoint uses, so the tool cannot bypass
    # the bounds or the canonical ordering.
    from app.utils.validators import validate_water_quality_payload

    cleaned = validate_water_quality_payload(features)
    result = run_model(cleaned)

    prediction = WaterPrediction(
        user_id=user_id,
        prediction=result["risk_level"],
        confidence=result["confidence"],
        **cleaned,
    )
    db.session.add(prediction)
    db.session.commit()

    if result["risk_level"] == RISK_UNSAFE:
        from app.services.alert_service import raise_for_prediction

        try:
            raise_for_prediction(prediction.id, features=cleaned, confidence=result["confidence"])
        except Exception:  # noqa: BLE001 - alert failure must not hide the result
            logger.exception("AI-run prediction failed to raise an alert")

    payload = _serialize(prediction)
    payload["probabilities"] = {
        "potable": result["probability_potable"],
        "not_potable": result["probability_not_potable"],
    }
    return payload


def _get_my_account(user_id: int = None) -> dict[str, Any]:
    """The caller's own account details and usage counters.

    Scoped to `user_id` from the session, so the assistant can describe the
    user's account but can never read another one. Password material is not
    included - `User.to_dict()` omits it by construction.
    """
    from app.models import User
    user = db.session.get(User, user_id)
    if user is None:
        return {"error": "account not found"}

    predictions = db.session.execute(
        select(func.count())
        .select_from(WaterPrediction)
        .where(WaterPrediction.user_id == user_id)
    ).scalar_one()

    unread = db.session.execute(
        select(func.count())
        .select_from(Alert)
        .where(Alert.user_id == user_id, Alert.is_read.is_(False))
    ).scalar_one()

    return {
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "usage": {
            "predictions": int(predictions or 0),
            "unread_alerts": int(unread or 0),
        },
    }


def _explain_concept(topic: str, user_id: int = None) -> dict[str, Any]:
    """Return reference documentation for one topic.

    Answers come from `app.ai.knowledge`, which is written text reviewed as part
    of this project - not from the model's recollection. That distinction is the
    point: a model asked about this system will otherwise invent specifics.

    The topic is resolved through the alias table first, so the assistant can
    pass the user's own wording (random forest, hardware, benefits) instead of
    having to know the canonical key.
    """
    from app.ai.knowledge import get_topics, resolve_topic

    topics = get_topics()
    resolved = resolve_topic(topic) or topic
    if resolved not in topics:
        raise ValidationError(
            "Unknown topic",
            {"topic": "Must be one of: " + ", ".join(sorted(topics))},
        )

    return {"topic": resolved, "content": topics[resolved]}

# --------------------------------------------------------------------------
# Parameter reference text (static metadata, never model-invented)
# --------------------------------------------------------------------------
# The HEALTHY band for each parameter, with what a reading on either side means.
# Distinct from FEATURE_BOUNDS, which is the physical range the API accepts: a
# pH of 1 is a legal input and a terrible reading, and the assistant has to be
# able to say both. Mirrors `frontend/src/utils/reports.js` NORMAL_LEVELS so the
# chat and the Reports screen never disagree about what "normal" is.
_NORMAL_RANGES: dict[str, dict[str, Any]] = {
    "ph": {
        "low": 6.5,
        "high": 8.5,
        "below": (
            "Below 6.5 the water is acidic. That can dissolve metal from pipework "
            "(lead and copper in particular), give the water a metallic taste, and "
            "corrode plumbing."
        ),
        "above": (
            "Above 8.5 the water is alkaline. It tends to taste flat, can leave "
            "scale deposits in pipes and appliances, and may reduce the "
            "effectiveness of disinfection."
        ),
    },
    "turbidity": {
        "low": 0,
        "high": 5,
        "below": "Turbidity cannot go below 0 NTU; a very low reading is ideal - the water is clear.",
        "above": (
            "Above about 5 NTU the water is visibly cloudy. Suspended particles can "
            "shelter bacteria and viruses from disinfection, so cloudiness is a "
            "health signal even when the water looks merely dirty."
        ),
    },
    "tds": {
        "low": 0,
        "high": 500,
        "below": "Very low TDS is fine; distilled water sits near 0. It is not a safety problem.",
        "above": (
            "Above about 500 mg/L the water starts to taste salty or metallic and "
            "may indicate contamination - agricultural runoff, seawater intrusion "
            "or mineral leaching. It is mainly an acceptability measure rather "
            "than a direct health limit."
        ),
    },
    "temperature": {
        "low": 10,
        "high": 25,
        "below": (
            "Below about 10 C the water is cold, which is not a health problem in "
            "itself but slows disinfection and can indicate a deep or shaded source."
        ),
        "above": (
            "Above about 25 C the water is warm. Warm water holds less dissolved "
            "oxygen and supports faster microbial growth, so it is best read "
            "alongside the dissolved-oxygen value."
        ),
    },
    "dissolved_oxygen": {
        "low": 6.5,
        "high": 9.5,
        "below": (
            "Below about 6.5 mg/L the water is poorly oxygenated, which points to "
            "stagnant water or heavy organic load - decomposing material consumes "
            "the oxygen."
        ),
        "above": (
            "Above about 9.5 mg/L the water is well aerated. That is generally "
            "healthy for aquatic life and indicates a lively, moving source."
        ),
    },
}

_PARAMETER_DESCRIPTIONS = {
    "ph": "pH measures acidity/alkalinity. Drinking water is ideally 6.5-8.5; outside that range it can corrode pipes or taste metallic.",
    "turbidity": "Turbidity (NTU) is water cloudiness from suspended particles. Lower is clearer and safer; turbid water can shelter pathogens.",
    "tds": "Total Dissolved Solids (mg/L) is the combined mineral content. Low values (<600) are typically pleasant; very high values taste salty and signal contamination.",
    "temperature": "Temperature (degC) affects dissolved oxygen and biological activity. Cooler water holds more oxygen.",
    "dissolved_oxygen": "Dissolved Oxygen (mg/L) is oxygen available to aquatic life. Higher generally indicates healthier, better-aerated water.",
}


# ==========================================================================
# Canonical tool handlers (the tool contract)
# ==========================================================================
# Every handler below is scoped to the `user_id` passed by the tool runner,
# which comes from the authenticated JWT - never from the model or the request
# body. None accepts a table name, column name, raw SQL string or any other
# identifier that could redirect the query, and none runs dynamic code. A call
# can only ever read the caller's own rows.
def _get_latest_prediction(user_id: int = None, **_: Any) -> dict[str, Any]:
    """The caller's single most recent prediction, or an explicit empty state."""
    row = db.session.execute(
        select(WaterPrediction)
        .where(WaterPrediction.user_id == user_id)
        .order_by(WaterPrediction.created_at.desc(), WaterPrediction.id.desc())
        .limit(1)
    ).scalar_one_or_none()

    if row is None:
        # An explicit empty state, not just null: the model is told what to say
        # instead of being left to improvise (or invent) a result.
        return {
            "type": "PREDICTION",
            "prediction": None,
            "empty": True,
            "message": AI_NO_PREDICTIONS,
        }

    return {"type": "PREDICTION", "prediction": _prediction_to_result(row)}


def _explain_latest_prediction(user_id: int = None, **_: Any) -> dict[str, Any]:
    """Explain the caller's most recent prediction from its stored values.

    Everything in the reply is read from the row itself - verdict, confidence and
    the five measured parameters - or from static project metadata (labels, units,
    safe-range text). Nothing is generated by the model and nothing is inferred,
    so the explanation can never disagree with the record on screen.

    An account with no predictions gets the fixed empty-state sentence rather
    than a template with blanks in it.
    """
    row = db.session.execute(
        select(WaterPrediction)
        .where(WaterPrediction.user_id == user_id)
        .order_by(WaterPrediction.created_at.desc(), WaterPrediction.id.desc())
        .limit(1)
    ).scalar_one_or_none()

    if row is None:
        return {
            "type": "PREDICTION_EXPLANATION",
            "prediction": None,
            "empty": True,
            "message": AI_NO_PREDICTIONS,
        }

    return {
        "type": "PREDICTION_EXPLANATION",
        "prediction": {
            **_prediction_to_result(row),
            "explanation": _explanation_text(row),
            "parameters": _explanation_parameters(row),
        },
    }


def _explanation_parameters(row: WaterPrediction) -> list[dict[str, Any]]:
    """The stored readings, labelled, with the plain-English meaning of each."""
    from app.ml.preprocessing import describe_features
    described = {item["name"]: item for item in describe_features(row.features())}
    parameters: list[dict[str, Any]] = []
    for name in FEATURE_NAMES:
        item = described.get(name)
        if item is None:  # a column the row does not carry is omitted, not faked
            continue
        parameters.append(
            {
                **item,
                "valid_range": list(FEATURE_BOUNDS[name]),
                "description": _PARAMETER_DESCRIPTIONS.get(name, ""),
            }
        )
    return parameters

def _explanation_text(row: WaterPrediction) -> dict[str, Any]:
    """The fixed wording of an explanation, derived only from stored values.

    Held server-side rather than left to the model so the two things this step
    insists on are always present: the result is named as an AI-based prediction,
    and an unsafe verdict carries a cautious warning. `disclaimer` is always
    returned; `warning` only when the verdict is not safe.
    """
    verdict = row.prediction
    confidence = float(row.confidence)

    lines = [
        f"Your latest AquaGuard AI prediction is {verdict.upper()} with a confidence of {confidence * 100:.1f}%.",
        "",
        "Parameters:",
    ]
    for name in FEATURE_NAMES:
        label = FEATURE_LABELS.get(name, name)
        unit = FEATURE_UNITS.get(name, "")
        lines.append(f"{label}: {float(getattr(row, name)):g} {unit}".rstrip())

    lines += [
        "",
        f"The model classified this sample as {verdict.upper()} based on patterns learned during training.",
        "",
        "This AI prediction should not be treated as a certified laboratory water-safety result.",
    ]

    warning = None
    if verdict == RISK_UNSAFE:
        warning = (
            "This sample was classified as UNSAFE. Treat the water as unsafe until it "
            "has been checked by a certified laboratory: do not drink it, and do not "
            "use it for cooking or for children. An AI prediction can be wrong, so a "
            "cautious response is the right one."
        )

    return {
        "verdict": verdict,
        "confidence": confidence,
        "text": "\n".join(lines),
        "warning": warning,
        "disclaimer": (
            "This AI prediction should not be treated as a certified laboratory "
            "water-safety result."
        ),
        "is_ai_prediction": True,
    }


def _get_prediction_history(
    limit: int = 10, page: int = 1, risk_level: str | None = None, user_id: int = None, **_: Any
) -> dict[str, Any]:
    """A page of the caller's predictions, newest first.
    Filtering happens in SQL against the caller's own rows, so a filter cannot
    widen the result set to another account. `limit` and `page` are clamped to a
    safe range rather than trusted, because they arrive from the model.
    """
    from app.constants import RISK_LEVELS
    page = max(1, int(page or 1))
    limit = max(1, min(int(limit or 10), 50))

    if risk_level is not None and risk_level not in RISK_LEVELS:
        raise ValidationError(
            "Unknown risk level",
            {"risk_level": f"Must be one of: {', '.join(RISK_LEVELS)}"},
        )

    query = select(WaterPrediction).where(WaterPrediction.user_id == user_id)
    if risk_level:
        query = query.where(WaterPrediction.prediction == risk_level)
    query = query.order_by(
        WaterPrediction.created_at.desc(), WaterPrediction.id.desc()
    )

    rows = (
        db.session.execute(query.offset((page - 1) * limit).limit(limit))
        .scalars()
        .all()
    )

    result: dict[str, Any] = {
        "type": "PREDICTION_HISTORY",
        "page": page,
        "limit": limit,
        "count": len(rows),
        "predictions": [_prediction_to_result(row) for row in rows],
    }
    if not rows:
        result["empty"] = True
        result["message"] = AI_NO_PREDICTIONS
    return result


def _get_prediction_by_id(
    prediction_id: int, user_id: int = None, **_: Any
) -> dict[str, Any]:
    """One of the caller's predictions by id.

    The `user_id` predicate is part of the query, so an id belonging to another
    account simply does not match. The result is reported as not found, which is
    the same answer as a genuinely missing id, so the tool cannot be used to
    probe which ids exist.
    """
    try:
        prediction_id = int(prediction_id)
    except (TypeError, ValueError):
        raise ValidationError(
            "prediction_id must be an integer", {"prediction_id": "integer required"}
        ) from None
    row = db.session.execute(
        select(WaterPrediction).where(
            WaterPrediction.id == prediction_id,
            WaterPrediction.user_id == user_id,
        )
    ).scalar_one_or_none()

    if row is None:
        return {
            "type": "PREDICTION",
            "prediction": None,
            "not_found": True,
            "message": "No such prediction for this account.",
        }
    return {"type": "PREDICTION", "prediction": _prediction_to_result(row)}


def _get_alerts(
    unread_only: bool = False, limit: int = 20, user_id: int = None, **_: Any
) -> dict[str, Any]:
    """"The caller's alerts, newest first, optionally unread only."""
    limit = max(1, min(int(limit or 20), 50))

    query = select(Alert).where(Alert.user_id == user_id)
    if unread_only:
        query = query.where(Alert.is_read.is_(False))
    query = query.order_by(Alert.created_at.desc(), Alert.id.desc()).limit(limit)

    rows = db.session.execute(query).scalars().all()

    result: dict[str, Any] = {
        "type": "ALERTS",
        "count": len(rows),
        "unread_only": bool(unread_only),
        "alerts": [
            {
                "id": row.id,
                "type": row.type,
                "message": row.message,
                "severity": getattr(row, "severity", None),
                "is_read": bool(row.is_read),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
    }
    if not rows:
        result["empty"] = True
        result["message"] = AI_NO_ALERTS
    return result

def _get_dashboard_summary(user_id: int = None, **_: Any) -> dict[str, Any]:
    """"The caller's dashboard totals and open-alert count."""
    total = db.session.execute(
        select(func.count())
        .select_from(WaterPrediction)
        .where(WaterPrediction.user_id == user_id)
    ).scalar_one()

    safe = db.session.execute(
        select(func.count())
        .select_from(WaterPrediction)
        .where(
            WaterPrediction.user_id == user_id,
            WaterPrediction.prediction == RISK_SAFE,
        )
    ).scalar_one()

    unsafe = db.session.execute(
        select(func.count())
        .select_from(WaterPrediction)
        .where(
            WaterPrediction.user_id == user_id,
            WaterPrediction.prediction == RISK_UNSAFE,
        )
    ).scalar_one()

    avg_conf = db.session.execute(
        select(func.avg(WaterPrediction.confidence)).where(
            WaterPrediction.user_id == user_id
        )
    ).scalar_one()

    open_alerts = db.session.execute(
        select(func.count())
        .select_from(Alert)
        .where(Alert.user_id == user_id, Alert.is_read.is_(False))
    ).scalar_one()

    total_int, safe_int, unsafe_int = int(total or 0), int(safe or 0), int(unsafe or 0)
    return {
        "type": "DASHBOARD_SUMMARY",
        "total_predictions": total_int,
        "safe": safe_int,
        "unsafe": unsafe_int,
        "moderate": total_int - safe_int - unsafe_int,
        "average_confidence": round(float(avg_conf), 4) if avg_conf is not None else None,
        "open_alerts": int(open_alerts or 0),
    }


def _report_download_actions(risk_level: str | None) -> list[dict[str, Any]]:
    """The download actions for a report list, as client-renderable descriptors.

    These become real buttons in the chat panel. The frontend performs the
    download itself (it holds the CSV/PDF builders already), so the server sends a
    *description* of the action and the scope it covers - never a URL, a file path
    or bytes. That keeps the same boundary the navigation actions use: the
    assistant can ask the client to do something from a fixed vocabulary, and
    cannot express an arbitrary destination.
    """
    scope = risk_level or "all"
    return [
        {
            "type": "DOWNLOAD_REPORTS",
            "format": "csv",
            "scope": scope,
            "label": "Download CSV",
        },
        {
            "type": "DOWNLOAD_REPORTS",
            "format": "pdf",
            "scope": scope,
            "label": "Download PDF",
        },
    ]


def _get_report_list(
    risk_level: str | None = None,
    limit: int = 10,
    user_id: int = None,
    **_: Any,
) -> dict[str, Any]:
    """A list of the caller's reports, plus the downloads that apply to it.

    Scoped to `user_id` from the session like every other handler, so the list can
    only ever contain the caller's own readings. `risk_level` filters in SQL (not
    in Python) for the same reason: the filter cannot widen the result set to
    another account, because the ownership predicate is on the same query.

    The `downloads` array is the mechanism behind "show the unsafe list and put
    download buttons under it": the model relays the list, and the client renders
    each entry as a button that exports exactly the scope named here.
    """
    limit = max(1, min(int(limit or 10), 50))

    verdict = (risk_level or "all").strip().lower()
    if verdict in ("", "all", "any"):
        verdict = None
    elif verdict not in RISK_LEVELS:
        raise ValidationError(
            "Unknown risk level",
            {"risk_level": f"Must be one of: all, {', '.join(RISK_LEVELS)}"},
        )

    query = select(WaterPrediction).where(WaterPrediction.user_id == user_id)
    if verdict:
        query = query.where(WaterPrediction.prediction == verdict)
    query = query.order_by(
        WaterPrediction.created_at.desc(), WaterPrediction.id.desc()
    ).limit(limit)

    rows = db.session.execute(query).scalars().all()

    result: dict[str, Any] = {
        "type": "REPORT_LIST",
        "scope": verdict or "all",
        "scope_label": (verdict or "all").capitalize(),
        "count": len(rows),
        "reports": [_prediction_to_result(row) for row in rows],
        "downloads": _report_download_actions(verdict),
    }
    if not rows:
        result["empty"] = True
        if verdict:
            result["message"] = (
                f"Your account does not have any {verdict} prediction records yet."
            )
        else:
            result["message"] = AI_NO_PREDICTIONS
    return result


def _get_usage_counters(user_id: int = None, **_: Any) -> dict[str, Any]:
    """How much this application has been used.

    REPLACES THE OLD `get_current_user` TOOL, which reported the caller's own
    name, email and role. There are no user accounts any more, so that tool had
    nothing true to say and would have answered a question about a person that no
    longer exists. What remains worth answering is the volume of use, and that
    is what this returns.

    Counts are across the WHOLE application rather than scoped to one owner,
    because there are no private histories to scope them to.
    """
    from sqlalchemy import func

    predictions = db.session.execute(
        select(func.count()).select_from(WaterPrediction)
    ).scalar_one()
    unread = db.session.execute(
        select(func.count()).select_from(Alert).where(Alert.is_read.is_(False))
    ).scalar_one()

    return {
        "type": "USAGE",
        "usage": {
            "predictions": int(predictions or 0),
            "unread_alerts": int(unread or 0),
        },
    }


def _prediction_to_result(row: WaterPrediction) -> dict[str, Any]:
    """"Shape one stored prediction for a tool result."""
    return {
        "id": row.id,
        "verdict": row.prediction,
        "confidence": float(row.confidence),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "values": {name: float(getattr(row, name)) for name in FEATURE_NAMES},
        # The place the sample belongs to, with its EXACT stored pincode. A
        # missing value is reported as null, which the model must render as
        # "Pincode: Not Available" - never a pincode inferred from the place.
        "location": {
            "name": row.location_name or row.location_city,
            "state": row.location_state,
            "country": row.location_country,
            "pincode": row.location_pincode,
        },
    }


def register_default_tools() -> None:
    """Register every catalogue tool handler with the tool runner.

    Idempotent: importing the tool runner and calling this more than once (e.g.
    across test modules) does not duplicate registrations.
    """
    global _REGISTERED
    if _REGISTERED:
        return
    from app.ai.tool_runner import register_tool

    # ONE HANDLER PER CATALOGUED TOOL. Every name here must also exist in
    # `utils.ai_tools.AI_TOOL_SPECS`: `register_tool` refuses a name that is not
    # in the catalogue, which is the check that caught the stale legacy entries
    # this list used to carry (get_recent_predictions, list_active_alerts,
    # get_my_account, get_dashboard_summary). Those were duplicates of the
    # canonical tools below, and keeping the model's menu small is what shortens
    # every request - the schemas are re-sent on each turn.
    register_tool("get_prediction_summary", _get_prediction_summary)
    register_tool("get_latest_prediction", _get_latest_prediction)
    register_tool("get_prediction_history", _get_prediction_history)
    register_tool("get_prediction_by_id", _get_prediction_by_id)
    register_tool("get_alerts", _get_alerts)
    register_tool("get_usage_counters", _get_usage_counters)
    register_tool("get_dashboard_summary", _get_dashboard_summary)
    register_tool("explain_parameter", _explain_parameter)
    register_tool("run_prediction", _run_prediction)
    register_tool("explain_concept", _explain_concept)
    register_tool("explain_latest_prediction", _explain_latest_prediction)
    register_tool("get_report_list", _get_report_list)

    # The navigation tools have NO server handler on purpose: they are executed
    # by the frontend through React Router. `tool_runner.execute_tool` rejects
    # them if a server call ever tries to run one, and the service turns them
    # into NAVIGATE actions instead of executing them.

    _REGISTERED = True
    logger.info("Aqua AI default tool handlers registered")
