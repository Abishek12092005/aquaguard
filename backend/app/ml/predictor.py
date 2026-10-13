"""Inference: validated features in, prediction + confidence out."""

import logging
from typing import Any, Mapping

import numpy as np

from app.constants import (
    CLASS_LABELS,
    FEATURE_NAMES,
    RISK_CONFIDENCE_THRESHOLD_HIGH,
    RISK_CONFIDENCE_THRESHOLD_MEDIUM,
    RISK_MODERATE,
    RISK_SAFE,
    RISK_UNSAFE,
)
from app.ml.model_loader import get_model, get_model_metadata
from app.ml.preprocessing import preprocess_input
from app.ml import water_quality
from app.utils.errors import ValidationError
logger = logging.getLogger(__name__)


def resolve_risk_level(predicted_class: int, confidence: float) -> str:
    """Map a class + confidence onto a risk level.

    An unsafe prediction is always at least `moderate`; a safe prediction is
    only fully `safe` when the model is confident, which keeps borderline
    results visible on the dashboard rather than silently green.
    """
    if predicted_class == 0:
        return RISK_UNSAFE if confidence >= RISK_CONFIDENCE_THRESHOLD_MEDIUM else RISK_MODERATE
    if confidence >= RISK_CONFIDENCE_THRESHOLD_HIGH:
        return RISK_SAFE
    return RISK_MODERATE


def predict_three_class(features: Mapping[str, float]) -> dict[str, Any] | None:
    """Run the trained 3-class water-quality model (SAFE / MODERATE / UNSAFE).

    This is the model Step 7 produced, and it is tried FIRST because it is the
    only artifact that emits all three verdicts the API contract promises.

    Returns None when that artifact is not installed, so the caller falls back
    to the legacy binary forest instead of failing outright.
    """
    if not water_quality.is_available():
        return None

    # `preprocess_input` returns a one-row pandas DataFrame, but the 3-class
    # pipeline takes a plain dict of the same five floats. Building the frame and
    # immediately unpacking it with `frame.iloc[0][name]` five times was pure
    # overhead on the hot path, so the validated values are coerced directly.
    row = _validated_row(features)

    result = water_quality.predict(row)
    probabilities = result['probabilities']
    prob_safe = float(probabilities.get(RISK_SAFE, 0.0))

    return {
        'predicted_class': result['label'],  # model class
        'label': result['label'],
        'risk_level': result['risk_level'],
        'confidence': result['confidence'],
        # Same potable/not-potable vocabulary the stored rows already use:
        # SAFE is potable, anything else is not.
        'probability_potable': round(prob_safe, 4),
        'probability_not_potable': round(1.0 - prob_safe, 4),
        'probabilities': probabilities,
        'model_name': 'random_forest_water_quality',
        'model_version': _water_quality_version(),
        'feature_contributions': _contributions_from_importance(
            result.get('feature_importance') or {}, row
        ),
    }


def _validated_row(features: Mapping[str, float]) -> dict[str, float]:
    """The five readings as floats, validated and in canonical order.

    The same checks `preprocess_input` applies, kept here so the 3-class path
    reaches the model with identical guarantees (no string, no bool, no missing
    field) without paying for a DataFrame it would immediately discard.
    """
    missing = [name for name in FEATURE_NAMES if name not in features]
    if missing:
        raise ValidationError(
            "Missing required features", {name: "This parameter is required" for name in missing}
        )

    row: dict[str, float] = {}
    for name in FEATURE_NAMES:
        try:
            row[name] = float(features[name])
        except (TypeError, ValueError):
            raise ValidationError(
                "Feature must be numeric", {name: "Must be a number"}
            ) from None
    return row


def _water_quality_version() -> str | None:
    """Read the version stamped by ``ml/train_model.py``, tolerating absence."""
    try:
        return water_quality.metadata().get('model_version')
    except Exception:  # noqa: BLE001 - a missing version must not break inference
        return None


def _contributions_from_importance(
    importances: Mapping[str, float], values: Mapping[str, float]
) -> list[dict[str, Any]] | None:
    """Per-feature influence from the 3-class model global importances.

    The artifact ships importances but not the training means, so each reading
    is centred on the mid-point of its allowed range. That is a cruder signal
    than the binary forest gives, and it is labelled as such rather than
    presented with false precision.
    """
    if not importances:
        return None

    from app.constants import FEATURE_BOUNDS

    contributions = []
    for name in FEATURE_NAMES:
        low, high = FEATURE_BOUNDS[name]
        midpoint = (low + high) / 2.0
        importance = float(importances.get(name, 0.0))
        value = float(values.get(name, 0.0))
        contributions.append(
            {
                'name': name,
                'value': value,
                'importance': round(importance, 4),
                'contribution': round(abs(value - midpoint) * importance, 4),
            }
        )
    return contributions


def predict(features: Mapping[str, float], threshold: float = 0.5) -> dict[str, Any]:
    """Run the Random Forest on one sample.

    Returns a dict matching the `Prediction` model columns:

        predicted_class, label, confidence,
        probability_potable, probability_not_potable,
        risk_level, model_name, model_version, feature_contributions
    """
    # The 3-class artifact is authoritative whenever it is installed; only fall
    # through to the binary forest below when it is genuinely absent.
    three_class = predict_three_class(features)
    if three_class is not None:
        return three_class
    frame = preprocess_input(features)
    model = get_model()

    # predict_proba -> [[P(class 0), P(class 1)]]
    probabilities = model.predict_proba(frame)[0]
    prob_not_potable = float(probabilities[0])
    prob_potable = float(probabilities[1])

    predicted_class = int(prob_potable >= threshold)
    confidence = prob_potable if predicted_class == 1 else prob_not_potable

    metadata = get_model_metadata()

    return {
        "predicted_class": predicted_class,
        "label": CLASS_LABELS[predicted_class],
        "confidence": round(confidence, 4),
        "probability_potable": round(prob_potable, 4),
        "probability_not_potable": round(prob_not_potable, 4),
        "risk_level": resolve_risk_level(predicted_class, confidence),
        "model_name": metadata.get("model_name", "random_forest"),
        "model_version": metadata.get("model_version"),
        "feature_contributions": _feature_contributions(model, frame),
    }


def _feature_contributions(model: Any, frame) -> list[dict[str, Any]] | None:
    """Per-feature influence for the history detail view.

    Uses the forest's global feature importances multiplied by how far each
    value sits from the training mean — a cheap, honest local signal that needs
    no extra dependency. Returns None when the estimator exposes neither.
    """
    importances = getattr(model, "feature_importances_", None)
    if importances is None:
        return None

    importances = np.asarray(importances, dtype=float)
    if importances.shape[0] != len(FEATURE_NAMES):
        return None

    values = frame.iloc[0].to_numpy(dtype=float)

    # Centre each value using the forest's own summary statistics when present.
    summary = getattr(model, "_training_stats", None)
    means = summary.get("mean") if isinstance(summary, dict) else None
    if isinstance(means, dict):
        centered = np.array([values[i] - float(means.get(name, 0.0)) for i, name in enumerate(FEATURE_NAMES)])
    else:
        centered = values - np.mean(values)

    contribution = np.abs(centered) * importances

    return [
        {
            "name": name,
            "value": float(values[index]),
            "importance": round(float(importances[index]), 4),
            "contribution": round(float(contribution[index]), 4),
        }
        for index, name in enumerate(FEATURE_NAMES)
    ]
