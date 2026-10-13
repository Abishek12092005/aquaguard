"""Bridge from the Flask app to the standalone ml/ pipeline.

`ml/train_model.py` produces a 3-class Random Forest (SAFE / MODERATE /
UNSAFE). This module imports that pipeline's `predict()` and adapts it to the
shape the backend expects, so the same trained artifact serves both the CLI and
the API.

The standalone package is imported lazily and defensively: if it is not on the
path (or the artifact is missing), the caller gets an `MLModelError` that the
route turns into a clear 503 rather than a mock result.

PER-REQUEST COST, WHICH THIS MODULE KEEPS AT ZERO. Every prediction asks two
questions of this module before running the model: "is the artifact there?"
(`is_available`) and "what version is it?" (`metadata`). Both used to hit the
filesystem on every call - a `stat`, then an open+read+json parse. The answers
cannot change while the process runs, so they are resolved once and memoised
here. `warm_up()` does that work up front; the memoise makes it correct even
when it is not (a request that arrives first just pays the cost once).
"""

import json
import logging
import os
import sys
import threading
from typing import Any, Mapping

from flask import current_app

from app.constants import RISK_MODERATE, RISK_SAFE, RISK_UNSAFE
from app.utils.errors import MLModelError

logger = logging.getLogger(__name__)

# Map the pipeline's uppercase classes onto the backend's stored vocabulary.
_CLASS_TO_RISK = {"SAFE": RISK_SAFE, "MODERATE": RISK_MODERATE, "UNSAFE": RISK_UNSAFE}

_pipeline = None

# Memoised answers to the two per-request questions described above. Each is keyed
# by the `ml/` root it was resolved for, so pointing the app at a different model
# directory (a test, a staging deployment) cannot be answered with a value
# remembered from the previous one. `None` for a key means "not resolved yet";
# a False/`{}` value is a real answer and is not recomputed.
_available: dict[str, bool] = {}
_metadata: dict[str, dict[str, Any]] = {}

# The pipeline and the filesystem probes are lazy, so two concurrent first
# requests could each start an import and each parse the metadata file. A lock
# makes the winner pay and the loser wait, rather than both paying.
_init_lock = threading.Lock()


def _ml_root() -> str:
    """The `ml/` package root, from config, or the default relative to this file."""
    try:
        return current_app.config["ML_WATER_QUALITY_DIR"]
    except RuntimeError:
        # Outside an application context there is no configuration to read.
        return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "ml"))


def _load_pipeline():
    """Import the standalone ml/ package, adding its root to sys.path once."""
    global _pipeline
    if _pipeline is not None:
        return _pipeline

    with _init_lock:
        if _pipeline is not None:
            return _pipeline

        root = _ml_root()
        if root not in sys.path:
            sys.path.insert(0, root)

        import predict as wq_predict  # type: ignore  # provided by ml/predict.py

        _pipeline = wq_predict
        return _pipeline


def is_available() -> bool:
    """True when the standalone model artifact exists on disk.

    Memoised after the first call: the answer is a property of the deployed
    files, and asking the filesystem on every prediction was pure per-request
    latency for information that cannot change under a running process.
    """
    root = _ml_root()
    if root in _available:
        return _available[root]

    with _init_lock:
        if root not in _available:
            try:
                _available[root] = bool(_load_pipeline().is_model_available())
            except Exception:  # noqa: BLE001 - availability probe must not raise
                logger.exception("Water quality availability probe failed")
                _available[root] = False
    return _available[root]


def metadata() -> dict[str, Any]:
    """Training metadata (version, metrics, classes) for the 3-class model.

    Read from the JSON written beside the artifact by ``ml/train_model.py``, so
    the version stamped onto a stored prediction is genuinely the version the
    model was trained as. Parsed once and kept: the file only changes when the
    model is retrained, which restarts the process. Returns an empty dict when
    the file is missing rather than raising: metadata is descriptive, and its
    absence must not stop inference.
    """
    root = _ml_root()
    if root in _metadata:
        return _metadata[root]

    with _init_lock:
        if root not in _metadata:
            _metadata[root] = _read_metadata(root)
    return _metadata[root]


def _read_metadata(root: str) -> dict[str, Any]:
    """Parse the training metadata file. Runs at most once per `ml/` root."""
    path = os.path.join(root, "model", "model_metadata.json")
    if not os.path.isfile(path):
        return {}

    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:  # noqa: BLE001 - malformed metadata is not fatal
        logger.exception("Could not read water quality model metadata at %s", path)
        return {}


def warm_up() -> bool:
    """Import the pipeline, load the model and resolve metadata ahead of time.

    Called once at start-up so the FIRST prediction does not pay several seconds
    of import and unpickling. Returns False when the artifacts are missing, so
    the caller can log it - it does not raise, because a missing model must
    still surface as an honest 503 at request time, not as a boot failure.
    """
    try:
        _load_pipeline()
        is_available()
        metadata()
        warm = _pipeline.warm_up()
        if warm:
            logger.info("Water quality model pre-loaded and ready")
        return warm
    except Exception:  # noqa: BLE001 - start-up optimisation, never fatal
        logger.exception("Water quality model warm-up did not complete")
        return False


def predict(features: Mapping[str, float]) -> dict[str, Any]:
    """Run the 3-class water-quality model and adapt its output.

    Returns a dict shaped like the backend's other predictions:

        risk_level      safe | moderate | unsafe
        confidence      0-1
        probabilities   {safe, moderate, unsafe}
        raw             the pipeline's original output (class + importances)
    """
    try:
        pipeline = _load_pipeline()
        result = pipeline.predict(features)
    except FileNotFoundError as exc:
        raise MLModelError(
            "Water quality model artifact not found. Train it first: python ml/train_model.py",
            {"error": str(exc)},
        ) from exc
    except MLModelError:
        raise
    except Exception as exc:  # noqa: BLE001 - surfaced as a 503 with detail
        logger.exception("Water quality model inference failed")
        raise MLModelError("Water quality model could not run", {"error": str(exc)}) from exc

    label = result["water_quality"]
    risk_level = _CLASS_TO_RISK.get(label, RISK_MODERATE)

    probabilities = {
        _CLASS_TO_RISK.get(name, name.lower()): value
        for name, value in result["probabilities"].items()
    }

    return {
        "label": label,
        "risk_level": risk_level,
        "confidence": result["confidence"],
        "probabilities": probabilities,
        "feature_importance": result["feature_importance"],
        "raw": result,
    }
