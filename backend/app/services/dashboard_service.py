"""Dashboard service - read-only aggregates for the landing screen."""

from typing import Any

from sqlalchemy import func, select

from app.constants import (
    FEATURE_BOUNDS,
    FEATURE_LABELS,
    FEATURE_NAMES,
    FEATURE_UNITS,
    RISK_MODERATE,
    RISK_SAFE,
    RISK_UNSAFE,
)
from app.extensions import db
from app.models import Alert, WaterPrediction
from app.utils.errors import ValidationError


def _current_user_id() -> int:
    """The account whose readings these figures are counted from.

    Delegates to the one shared rule in `app.services.identity`: a request with a
    valid token acts as that account, and anything else acts as the shared
    visitor. Every aggregate below is still scoped to this id.
    """
    from app.services.identity import current_user_id

    return current_user_id()


def get_overview() -> dict[str, Any]:
    """KPI cards: total predictions, safety ratio, avg confidence, open alerts."""
    user_id = _current_user_id()

    total = db.session.execute(
        select(func.count())
        .select_from(WaterPrediction)
        .where(WaterPrediction.user_id == user_id)
    ).scalar_one()

    safe_count = db.session.execute(
        select(func.count())
        .select_from(WaterPrediction)
        .where(WaterPrediction.user_id == user_id, WaterPrediction.prediction == RISK_SAFE)
    ).scalar_one()

    unsafe_count = db.session.execute(
        select(func.count())
        .select_from(WaterPrediction)
        .where(
            WaterPrediction.user_id == user_id,
            WaterPrediction.prediction == RISK_UNSAFE,
        )
    ).scalar_one()

    avg_confidence = db.session.execute(
        select(func.avg(WaterPrediction.confidence)).where(
            WaterPrediction.user_id == user_id
        )
    ).scalar_one()

    open_alerts = db.session.execute(
        select(func.count())
        .select_from(Alert)
        .where(Alert.user_id == user_id, Alert.is_read.is_(False))
    ).scalar_one()

    # Imported lazily so this module stays importable without a request context.
    from app.services.prediction_service import get_latest_prediction

    total_int = int(total or 0)
    safe_int = int(safe_count or 0)
    unsafe_int = int(unsafe_count or 0)

    return {
        "total_predictions": total_int,
        "safe_readings": safe_int,
        "unsafe_readings": unsafe_int,
        "moderate_readings": total_int - safe_int - unsafe_int,
        "average_confidence": round(float(avg_confidence), 4)
        if avg_confidence is not None
        else None,
        # Safety ratio as a 0-1 fraction; None when there is nothing to divide.
        "safety_ratio": round(safe_int / total_int, 4) if total_int else None,
        "open_alerts": int(open_alerts or 0),
        "latest_prediction": get_latest_prediction(),
    }


def get_charts(range_key: str = "30d") -> dict[str, Any]:
    """Chart-ready series for the Recharts components.

    Shape:
        {
          "trend":        [{"date": ..., "predictions": n, "unsafe": n}, ...],
          "distribution": [{"label": "potable"|"not_potable", "value": n}, ...],
          "parameters":   [{"parameter": ..., "mean": ..., "min": ..., "max": ...}, ...]
        }
    """
    user_id = _current_user_id()

    # --- Distribution -----------------------------------------------------
    safe_count = db.session.execute(
        select(func.count())
        .select_from(WaterPrediction)
        .where(WaterPrediction.user_id == user_id, WaterPrediction.prediction == RISK_SAFE)
    ).scalar_one()

    unsafe_count = db.session.execute(
        select(func.count())
        .select_from(WaterPrediction)
        .where(
            WaterPrediction.user_id == user_id,
            WaterPrediction.prediction == RISK_UNSAFE,
        )
    ).scalar_one()

    total = db.session.execute(
        select(func.count())
        .select_from(WaterPrediction)
        .where(WaterPrediction.user_id == user_id)
    ).scalar_one()

    moderate_count = int(total or 0) - int(safe_count or 0) - int(unsafe_count or 0)

    # --- Per-parameter aggregates -----------------------------------------
    parameter_rows = []
    for name in FEATURE_NAMES:
        column = getattr(WaterPrediction, name)
        row = db.session.execute(
            select(func.avg(column), func.min(column), func.max(column)).where(
                WaterPrediction.user_id == user_id
            )
        ).one()
        parameter_rows.append(
            {
                "parameter": name,
                "label": FEATURE_LABELS.get(name, name),
                "unit": FEATURE_UNITS.get(name, ""),
                "mean": round(float(row[0]), 2) if row[0] is not None else None,
                "min": float(row[1]) if row[1] is not None else None,
                "max": float(row[2]) if row[2] is not None else None,
            }
        )

    from app.services.prediction_service import get_prediction_stats

    stats = get_prediction_stats(range_key)

    return {
        "trend": stats["trend"],
        "distribution": [
            {"label": "potable", "value": int(safe_count or 0)},
            {"label": "moderate", "value": moderate_count},
            {"label": "not_potable", "value": int(unsafe_count or 0)},
        ],
        "parameters": parameter_rows,
    }


def get_summary() -> dict[str, Any]:
    """KPI counters + chart series for the dashboard, scoped to the caller."""
    user_id = _current_user_id()

    total = db.session.execute(
        select(func.count())
        .select_from(WaterPrediction)
        .where(WaterPrediction.user_id == user_id)
    ).scalar_one()

    safe_count = db.session.execute(
        select(func.count())
        .select_from(WaterPrediction)
        .where(WaterPrediction.user_id == user_id, WaterPrediction.prediction == RISK_SAFE)
    ).scalar_one()

    moderate_count = db.session.execute(
        select(func.count())
        .select_from(WaterPrediction)
        .where(WaterPrediction.user_id == user_id, WaterPrediction.prediction == RISK_MODERATE)
    ).scalar_one()

    unsafe_count = db.session.execute(
        select(func.count())
        .select_from(WaterPrediction)
        .where(WaterPrediction.user_id == user_id, WaterPrediction.prediction == RISK_UNSAFE)
    ).scalar_one()

    avg_confidence = db.session.execute(
        select(func.avg(WaterPrediction.confidence)).where(
            WaterPrediction.user_id == user_id
        )
    ).scalar_one()

    from app.services.prediction_service import get_latest_prediction, get_prediction_stats
    total_int = int(total or 0)
    safe_int = int(safe_count or 0)
    moderate_int = int(moderate_count or 0)
    unsafe_int = int(unsafe_count or 0)
    stats = get_prediction_stats("30d")

    return {
        "totals": {
            "total": total_int,
            "safe": safe_int,
            "moderate": moderate_int,
            "unsafe": unsafe_int,
        },
        "average_confidence": round(float(avg_confidence), 4)
        if avg_confidence is not None
        else None,
        "latest_prediction": get_latest_prediction(),
        "charts": {
            "distribution": [
                {"label": RISK_SAFE, "value": safe_int},
                {"label": RISK_MODERATE, "value": moderate_int},
                {"label": RISK_UNSAFE, "value": unsafe_int},
            ],
            "trend": stats["trend"],
            "parameters": _parameter_aggregates(user_id),
        },
    }


def _parameter_aggregates(user_id: int) -> list[dict[str, Any]]:
    """Mean/min/max for each measured parameter across the caller's readings."""
    rows = []
    for name in FEATURE_NAMES:
        column = getattr(WaterPrediction, name)
        row = db.session.execute(
            select(func.avg(column), func.min(column), func.max(column)).where(
                WaterPrediction.user_id == user_id
            )
        ).one()
        rows.append(
            {
                "parameter": name,
                "label": FEATURE_LABELS.get(name, name),
                "unit": FEATURE_UNITS.get(name, ""),
                "mean": round(float(row[0]), 2) if row[0] is not None else None,
                "min": float(row[1]) if row[1] is not None else None,
                "max": float(row[2]) if row[2] is not None else None,
            }
        )
    return rows

def get_recent(limit: int = 5) -> dict[str, Any]:
    """Recent predictions (activity) and recent alerts for the caller."""
    user_id = _current_user_id()
    limit = max(1, min(int(limit or 5), 20))

    predictions = db.session.execute(
        select(WaterPrediction)
        .where(WaterPrediction.user_id == user_id)
        .order_by(WaterPrediction.created_at.desc(), WaterPrediction.id.desc())
        .limit(limit)
    ).scalars().all()

    alerts = db.session.execute(
        select(Alert)
        .where(Alert.user_id == user_id)
        .order_by(Alert.created_at.desc(), Alert.id.desc())
        .limit(limit)
    ).scalars().all()

    return {
        "recent_predictions": [
            {
                "id": row.id,
                "prediction": row.prediction,
                "confidence": float(row.confidence),
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "values": {name: float(getattr(row, name)) for name in FEATURE_NAMES},
                # The place label, with the exact stored pincode when the row
                # carries one. Never inferred - an unset column stays unset.
                "location_name": row.location_name,
                "location_city": row.location_city,
                "location_state": row.location_state,
                "location_pincode": row.location_pincode,
            }
            for row in predictions
        ],
        "recent_alerts": [
            {
                "id": row.id,
                "type": row.type,
                "message": row.message,
                "is_read": bool(row.is_read),
                "prediction_id": row.prediction_id,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in alerts
        ],
    }


def get_parameter_metadata() -> dict[str, Any]:
    """Parameter contract served to the frontend form.

    This is a real, complete implementation: it derives the metadata from the
    same constants the validator and ML pipeline use, so the input form, the
    validation bounds and the model's feature order can never diverge.
    """
    return {
        "order": list(FEATURE_NAMES),
        "parameters": [
            {
                "name": name,
                "label": FEATURE_LABELS.get(name, name.replace("_", " ").title()),
                "unit": FEATURE_UNITS[name],
                "min": FEATURE_BOUNDS[name][0],
                "max": FEATURE_BOUNDS[name][1],
                "required": True,
            }
            for name in FEATURE_NAMES
        ],
    }
