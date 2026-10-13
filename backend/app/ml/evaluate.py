"""Model evaluation helpers.

Thin wrappers around scikit-learn metrics so the training script, a Jupyter
notebook and any future `/ai/model-report` endpoint all report identical
numbers for the same artifact.
"""

from typing import Any

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    precision_recall_fscore_support,
    roc_auc_score,
)


def evaluate(model: Any, features: np.ndarray, target: np.ndarray) -> dict[str, Any]:
    """Compute the standard metric bundle for a fitted classifier."""
    predictions = model.predict(features)

    report: dict[str, Any] = {
        "accuracy": round(float(accuracy_score(target, predictions)), 4),
        "confusion_matrix": confusion_matrix(target, predictions).tolist(),
        "report": classification_report(target, predictions, output_dict=True),
    }

    # Binary classifiers expose predict_proba; guard anyway so this helper
    # stays usable with estimators that do not.
    if hasattr(model, "predict_proba"):
        probabilities = model.predict_proba(features)[:, 1]
        report["roc_auc"] = round(float(roc_auc_score(target, probabilities)), 4)

    precision, recall, f1, _ = precision_recall_fscore_support(
        target, predictions, average="binary", zero_division=0
    )
    report["precision"] = round(float(precision), 4)
    report["recall"] = round(float(recall), 4)
    report["f1"] = round(float(f1), 4)
    return report


def feature_importances(model: Any, feature_names: tuple[str, ...]) -> dict[str, float]:
    """Return global feature importances keyed by parameter name."""
    importances = getattr(model, "feature_importances_", None)
    if importances is None:
        return {}
    return {
        name: round(float(importances[index]), 4)
        for index, name in enumerate(feature_names)
        if index < len(importances)
    }
