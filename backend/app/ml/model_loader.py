"""Model artifact loading and caching.

The serialized Random Forest is loaded once per process and cached, because
unpickling on every request would dominate prediction latency. The loader
degrades gracefully: if no artifact exists yet (Phase 1), `is_model_available()`
reports that honestly instead of raising, and the prediction endpoint surfaces
a clear 503 rather than inventing a result.
"""

import logging
import os
import pickle
import threading
from typing import Any

from flask import current_app

from app.utils.errors import MLModelError

logger = logging.getLogger(__name__)

# Guarded by a lock so concurrent first-requests cannot double-load.
_model_cache: dict[str, Any] = {}
_metadata_cache: dict[str, Any] = {}
_cache_lock = threading.Lock()


def _model_path() -> str:
    """Resolve the absolute path of the configured model artifact."""
    model_dir = current_app.config["ML_MODEL_DIR"]
    filename = current_app.config["ML_MODEL_FILENAME"]
    return os.path.join(model_dir, filename)


def is_model_available() -> bool:
    """True when a model artifact exists on disk and can be loaded."""
    try:
        return os.path.isfile(_model_path())
    except RuntimeError:
        # Outside an application context there is no configuration to read.
        return False


def get_model(force_reload: bool = False) -> Any:
    """Return the cached model, loading it from disk on first use.

    Raises `MLModelError` when the artifact is missing or unreadable, so the
    API returns 503 with an actionable message instead of a generic 500.
    """
    path = _model_path()

    with _cache_lock:
        if not force_reload and path in _model_cache:
            return _model_cache[path]

        if not os.path.isfile(path):
            raise MLModelError(
                "Prediction model artifact was not found. "
                "Train the model first (python -m app.ml.train).",
                {"expected_path": path},
            )

        try:
            with open(path, "rb") as handle:
                artifact = pickle.load(handle)
        except Exception as exc:  # noqa: BLE001 - surfaced as a 503 with detail
            logger.exception("Failed to load model artifact at %s", path)
            raise MLModelError("Prediction model could not be loaded", {"path": path, "error": str(exc)}) from exc

        model, metadata = _unpack(artifact)

        # Cache the estimator and its metadata separately so callers get the
        # estimator directly and never have to know the file was packaged.
        _model_cache[path] = model
        _metadata_cache[path] = metadata
        logger.info("Loaded AquaGuard model artifact from %s", path)
        return model

def _unpack(artifact: Any) -> tuple[Any, dict[str, Any]]:
    """Split a loaded artifact into (estimator, metadata).

    Supported shapes:
      * a dict ``{"model": est, "metadata": {...}}`` written by app.ml.train
      * a bare estimator (e.g. a pickled ``RandomForestClassifier``)
    """
    if isinstance(artifact, dict) and "model" in artifact:
        return artifact["model"], dict(artifact.get("metadata") or {})

    estimator = artifact.get("model") if isinstance(artifact, dict) else artifact
    return estimator, {
        "model_name": type(estimator).__name__,
        "model_version": getattr(estimator, "version", None),
    }


def get_model_metadata() -> dict[str, Any]:
    """Return the artifact's bundled metadata (version, features, metrics).

    Supported artifact shapes:
      * a plain estimator (e.g. `RandomForestClassifier`)
      * a dict such as ``{"model": est, "metadata": {...}}``
    """
    path = _model_path()

    # Ensure the artifact is loaded so its metadata is cached alongside it.
    get_model()
    return dict(_metadata_cache.get(path) or {})


def clear_cache() -> None:
    """Drop the cached artifact — used after retraining or in tests."""
    with _cache_lock:
        _model_cache.clear()
        _metadata_cache.clear()
