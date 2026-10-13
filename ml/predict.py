"""Inference for the water_quality model.

Loads the joblib artifacts written by train_model.py and exposes `predict()`,
which maps a feature dict to a water-quality category with a confidence score.

The Random Forest, the imputer, the scaler and the label encoder are loaded
ONCE per process and kept in memory, so repeated calls do not re-read 30 MB from
disk. Two details make that load cheap enough to also do eagerly:

  * `n_jobs` is forced to 1 on the loaded forest. A single-row prediction is
    300 trivial dot products; with the training-time `n_jobs=-1` scikit-learn
    hands that to a loky process pool, and the POOL is the cost. Measured on this
    artifact: ~440 ms with the pool, ~105 ms without, with byte-identical
    verdicts. A forest averages its trees deterministically, so scheduling is
    the only thing that changed - no tree is dropped and accuracy is untouched.
  * The per-class label mapping and the global feature importances are computed
    once here, rather than rebuilt from numpy on every request.

`warm_up()` loads everything up front so the first real request does not pay the
unpickling cost. Call it once at process start.

This module is import-safe from the Flask backend:
    from ml.predict import predict
    predict({"ph": 7.1, "turbidity": 1.2, "tds": 280.0,
             "temperature": 18.0, "dissolved_oxygen": 8.4})
"""

import logging
import os
import threading
from typing import Any, Mapping

import joblib
import numpy as np

logger = logging.getLogger(__name__)

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(HERE, "model")
PREPROCESSING_DIR = os.path.join(HERE, "preprocessing")

FEATURES = ("ph", "turbidity", "tds", "temperature", "dissolved_oxygen")
MODEL_FILE = "water_quality_rf.joblib"
ENCODER_FILE = "label_encoder.joblib"

_cache: dict[str, Any] = {}

# Guards the load so two concurrent first-requests cannot both unpickle 30 MB.
# A plain `if _cache` check is not enough: the second thread would see an
# empty dict between the first thread's start and its assignment.
_load_lock = threading.Lock()


def _build() -> dict[str, Any]:
    """Unpickle every artifact and precompute the per-request derivations."""
    model_path = os.path.join(MODEL_DIR, MODEL_FILE)
    if not os.path.isfile(model_path):
        raise FileNotFoundError(
            f"Model not found at {model_path}. Train it first: python ml/train_model.py"
        )

    model = joblib.load(model_path)
    encoder = joblib.load(os.path.join(MODEL_DIR, ENCODER_FILE))
    imputer = joblib.load(os.path.join(PREPROCESSING_DIR, "imputer.joblib"))
    scaler = joblib.load(os.path.join(PREPROCESSING_DIR, "scaler.joblib"))

    # See the module docstring: this is a scheduling change, not a model change.
    # n_jobs only controls how the already-fitted trees are walked, and the
    # forest's averaged probabilities are identical either way.
    if getattr(model, "n_jobs", 1) != 1:
        logger.info("Set model.n_jobs=1 for single-row inference (was %s)", model.n_jobs)
        model.n_jobs = 1

    importances = getattr(model, "feature_importances_", None)
    feature_importance = (
        {name: round(float(importances[i]), 4) for i, name in enumerate(FEATURES)}
        if importances is not None and len(importances) == len(FEATURES)
        else {}
    )

    return {
        "model": model,
        "encoder": encoder,
        "imputer": imputer,
        "scaler": scaler,
        # Built once, here, because they are constant for the life of the
        # process and were previously rebuilt on every request.
        "feature_importance": feature_importance,
        # encoder.inverse_transform([i]) per class, resolved up front.
        "labels_by_index": [str(cls) for cls in encoder.classes_],
    }


def _load() -> dict[str, Any]:
    """Return the loaded artifacts, loading them once per process."""
    if _cache:
        return _cache

    with _load_lock:
        if _cache:
            return _cache
        _cache.update(_build())
        logger.info("Water quality artifacts loaded from %s", MODEL_DIR)
    return _cache


def warm_up() -> bool:
    """Load the model and its preprocessing ahead of the first request.

    Returns True on success, False when the artifacts are absent or unreadable.
    Never raises: this is a start-up optimisation, and a missing artifact must
    still surface as a clear 503 at request time rather than as a boot crash.
    """
    try:
        _load()
        return True
    except Exception:  # noqa: BLE001 - reported, not raised, at start-up
        logger.exception("Could not pre-load the water quality model from %s", MODEL_DIR)
        return False


def is_model_available() -> bool:
    """True when the trained model artifact exists on disk."""
    return os.path.isfile(os.path.join(MODEL_DIR, MODEL_FILE))


def predict(features: Mapping[str, float]) -> dict[str, Any]:
    """Predict the water quality category for one sample.

    Returns:
        {
          "water_quality": "SAFE" | "MODERATE" | "UNSAFE",
          "confidence": float,                     # probability of the chosen class
          "probabilities": {label: prob, ...},     # every class
          "feature_importance": {feature: weight}  # global importances
        }
    """
    missing = [name for name in FEATURES if name not in features]
    if missing:
        raise ValueError(f"Missing required features: {missing}")

    artifacts = _load()
    row = np.array([[float(features[name]) for name in FEATURES]], dtype=float)

    imputed = artifacts["imputer"].transform(row)
    scaled = artifacts["scaler"].transform(imputed)

    probabilities = artifacts["model"].predict_proba(scaled)[0]
    class_index = int(np.argmax(probabilities))
    # The label for each class index was resolved once at load time, so this no
    # longer round-trips through encoder.inverse_transform on every request.
    label = artifacts["labels_by_index"][class_index]

    return {
        "water_quality": label,
        "confidence": round(float(probabilities[class_index]), 4),
        "probabilities": {
            name: round(float(probabilities[i]), 4)
            for i, name in enumerate(artifacts["labels_by_index"])
        },
        "feature_importance": artifacts["feature_importance"],
    }


if __name__ == "__main__":
    sample = {"ph": 7.1, "turbidity": 1.2, "tds": 280.0, "temperature": 18.0, "dissolved_oxygen": 8.4}
    print(f"sample   : {sample}")
    print(f"prediction: {predict(sample)}")
