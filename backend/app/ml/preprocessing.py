"""Input preprocessing for inference.

Turns a validated request payload into the exact feature representation the
trained model expects. Keeping this in its own module (rather than inline in
the predictor) means the offline training script can import the *same* function
and guarantee train/serve parity.
"""

from typing import Iterable, Mapping

import pandas as pd

from app.constants import FEATURE_LABELS, FEATURE_NAMES, FEATURE_UNITS
from app.utils.errors import ValidationError


def preprocess_input(features: Mapping[str, float]) -> pd.DataFrame:
    """Build a single-row ``DataFrame`` in canonical feature order.

    The column order is taken from ``FEATURE_NAMES``, not from the caller's
    dict, so a reordered or partially-specified payload can never silently
    scramble the model inputs.
    """
    if not isinstance(features, Mapping):
        raise ValidationError("Features must be a mapping of parameter name to value")

    missing = [name for name in FEATURE_NAMES if name not in features]
    if missing:
        raise ValidationError(
            "Missing required features", {name: "This parameter is required" for name in missing}
        )

    row = {}
    for name in FEATURE_NAMES:
        try:
            row[name] = float(features[name])
        except (TypeError, ValueError):
            raise ValidationError(
                "Feature must be numeric", {name: "Must be a number"}
            ) from None

    return pd.DataFrame([row], columns=list(FEATURE_NAMES))


def preprocess_batch(rows: Iterable[Mapping[str, float]]) -> pd.DataFrame:
    """Vectorised variant used by training, evaluation and CSV import."""
    frame = pd.DataFrame(list(rows))
    missing = [name for name in FEATURE_NAMES if name not in frame.columns]
    if missing:
        raise ValidationError(
            "Missing required features", {name: "This parameter is required" for name in missing}
        )
    return frame[list(FEATURE_NAMES)].astype(float)


def describe_features(features: Mapping[str, float]) -> list[dict]:
    """Return a stable, human-readable rendering of a sample.

    Used by the alert service and by Aqua AI when explaining why a sample was
    flagged, so both surfaces present identical wording.
    """
    return [
        {
            "name": name,
            "label": FEATURE_LABELS.get(name, name),
            "value": float(features[name]),
            "unit": FEATURE_UNITS[name],
        }
        for name in FEATURE_NAMES
        if name in features
    ]
