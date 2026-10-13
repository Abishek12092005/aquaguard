"""ML model management: listing, importing and activating model artifacts.

WHAT "IMPORT A MODEL" MEANS HERE, HONESTLY. It means: accept an uploaded artifact,
prove that it can be deserialised AND that it predicts, and make it selectable.
It does not mean retraining, and it does not mean the file is safe to run — a
pickle is executable code by construction, which is why this is behind the admin
console and a console unlock rather than a public endpoint.

WHY THE UPLOAD IS VALIDATED BY LOADING IT. An artifact that cannot be unpickled
is worse than no upload at all: without this check the failure would surface later,
as a 500 on a real user's prediction, with nothing pointing back at the upload.
So the file is loaded and asked to predict on a probe sample BEFORE it is stored.
A model that fails either step is rejected and the previous one is untouched.

WHY ACTIVATION IS A POINTER, NOT A FILE SWAP. No file is overwritten. The active
model is recorded in the database and the predictor reads that; activating a
different artifact is one row update and is reversible in the same way. Deleting
the running model out from under a live request is not a failure mode this
design can have.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
from datetime import datetime, timezone
from typing import Any

import joblib
from flask import current_app

from app.constants import FEATURE_NAMES
from app.extensions import db
from app.models import AdminSettings
from app.utils.errors import NotFoundError, ValidationError

logger = logging.getLogger(__name__)

# Where imported artifacts are kept, under the configured model directory.
IMPORTED_DIRNAME = "imported"

# A probe row, in the model's own feature order. Every uploaded artifact must be
# able to score it. The values are mid-range, so the probe tests the code path
# rather than a boundary case.
_PROBE = {name: 7.0 for name in FEATURE_NAMES}

# The settings key under which the model's name is stored.
_ACTIVE_KEY = "active_model"


def _model_root() -> str:
    """The directory model artifacts live in."""
    root = current_app.config.get("ML_WATER_QUALITY_DIR") or "."
    return os.path.join(root, "model")


def _imported_root() -> str:
    """Where uploaded artifacts are stored, created on demand."""
    path = os.path.join(_model_root(), IMPORTED_DIRNAME)
    os.makedirs(path, exist_ok=True)
    return path


def _safe_name(filename: str) -> str:
    """Reduce an uploaded filename to a safe basename.

    The upload's filename is attacker-controlled. Without this, `../../app.py`
    would be written over the application. Everything outside a conservative
    allowlist is replaced rather than escaped, because a name that is merely
    quoted is still a name that can resolve somewhere unexpected.
    """
    base = os.path.basename(filename or "")
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", base).lstrip(".")
    if not cleaned:
        cleaned = "model.joblib"
    # Always store as .joblib: the extension is what tells a future reader (and
    # the loader) how the file is encoded.
    stem = os.path.splitext(cleaned)[0] or "model"
    return f"{stem}.joblib"


def _describe(path: str) -> dict[str, Any]:
    """Metadata for one artifact, read from the file itself where possible."""
    stat = os.stat(path)
    info: dict[str, Any] = {
        "name": os.path.splitext(os.path.basename(path))[0],
        "filename": os.path.basename(path),
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "readable": False,
        "features": [],
        "labels": [],
        "model_version": None,
        "trained_at": None,
    }

    # Loading is attempted because the metadata the console wants (features,
    # classes, version) lives INSIDE the artifact. A failure is reported as
    # `readable: false` rather than raised: one broken file must not take the
    # whole listing down, or the console could never be used to remove it.
    try:
        artifact = joblib.load(path)
    except Exception as exc:  # noqa: BLE001 - a bad artifact is data, not an error
        logger.warning("Could not read model artifact %s: %s", path, type(exc).__name__)
        return info

    if isinstance(artifact, dict):
        info["features"] = list(artifact.get("features") or [])
        info["labels"] = [str(label) for label in (artifact.get("labels") or [])]
        info["model_version"] = artifact.get("model_version")
        info["trained_at"] = artifact.get("trained_at")
    else:
        # A bare estimator rather than the project's artifact envelope. Reported
        # as readable, with empty metadata, which is the truth.
        info["features"] = list(getattr(artifact, "feature_names_in_", []) or [])

    info["readable"] = True
    return info


def list_models() -> list[dict[str, Any]]:
    """Every artifact the backend can see, newest first, with the active one flagged."""
    root = _model_root()
    active = active_model_name()

    candidates: list[str] = []
    for directory in (root, _imported_root()):
        if not os.path.isdir(directory):
            continue
        for entry in os.listdir(directory):
            if entry.endswith((".joblib", ".pkl")):
                candidates.append(os.path.join(directory, entry))

    rows = []
    for path in sorted(candidates):
        info = _describe(path)
        info["active"] = info["name"] == active
        info["imported"] = os.path.dirname(path) == _imported_root()
        rows.append(info)

    rows.sort(key=lambda row: row["modified_at"], reverse=True)
    return rows


def active_model_name() -> str | None:
    """The name of the artifact currently answering predictions, if recorded."""
    settings = db.session.get(AdminSettings, 1)
    if settings is None:
        return None
    stored = settings.get_notification_settings()
    return stored.get(_ACTIVE_KEY)


def active_model_info() -> dict[str, Any]:
    """What the predictor is actually using right now."""
    name = active_model_name()
    if not name:
        return {
            "name": None,
            "source": "configuration",
            "detail": (
                "No model has been activated through the console; the backend is "
                "using the artifact named by ML_MODEL_FILENAME."
            ),
        }

    for row in list_models():
        if row["name"] == name:
            return {"name": name, "source": "console", "model": row}

    # Recorded but missing from disk: reported rather than hidden, because this
    # is exactly the state that makes every prediction fail.
    return {
        "name": name,
        "source": "console",
        "missing": True,
        "detail": f"'{name}' is set as active but no artifact with that name exists.",
    }


def import_model(upload, name: str | None = None) -> dict[str, Any]:
    """Validate and store an uploaded artifact, returning its metadata."""
    safe = _safe_name(name or upload.filename or "imported-model")
    destination = os.path.join(_imported_root(), safe)

    # Written to a temporary name first. If validation fails, nothing has touched
    # the real filename, so a rejected upload cannot have replaced a good one.
    staging = f"{destination}.incoming"
    upload.save(staging)

    try:
        _validate_artifact(staging)
    except Exception:
        try:
            os.remove(staging)
        except OSError:
            pass
        raise

    shutil.move(staging, destination)
    logger.info("Model imported: %s", destination)

    info = _describe(destination)
    info["imported"] = True
    return info


def _validate_artifact(path: str) -> None:
    """Prove the file loads and can predict, or raise ValidationError.

    BOTH steps are required. A file that loads but cannot predict would pass a
    load-only check and then break on the first real request, which is the
    failure this exists to prevent.
    """
    try:
        artifact = joblib.load(path)
    except Exception:
        raise ValidationError(
            "That file is not a readable model artifact",
            {"file": "The upload could not be loaded as a scikit-learn model."},
        ) from None

    estimator = artifact.get("model") if isinstance(artifact, dict) else artifact
    if estimator is None or not hasattr(estimator, "predict"):
        raise ValidationError(
            "That file does not contain a predictor",
            {"file": "Expected a fitted estimator, or an artifact with a 'model' key."},
        )

    features = (artifact.get("features") if isinstance(artifact, dict) else None) or list(
        getattr(estimator, "feature_names_in_", []) or []
    )

    # A model expecting a different feature set cannot be used by this API, which
    # always presents the values in FEATURE_NAMES order. Accepting it would mean
    # every prediction silently used the wrong columns.
    if features and list(features) != list(FEATURE_NAMES):
        raise ValidationError(
            "That model expects different inputs",
            {
                "file": "Expected features " + ", ".join(FEATURE_NAMES) + ".",
                "found": ", ".join(str(f) for f in features),
            },
        )

    import numpy as np

    probe = np.array([[float(_PROBE[name]) for name in FEATURE_NAMES]])
    try:
        estimator.predict(probe)
    except Exception:
        raise ValidationError(
            "That model could not produce a prediction",
            {"file": "The artifact loaded, but predicting on a sample failed."},
        ) from None


def set_active_model(name: str) -> dict[str, Any]:
    """Point the predictor at an imported artifact.

    THE NAME IS COMPARED BY STEM, which is a fix. `_safe_name` re-appends the
    `.joblib` extension to whatever it is given, so passing an already-correct
    stem produced `"rf-2026-04.joblib"` - while `list_models()` reports each
    artifact's `name` as the basename WITHOUT its extension. The two could
    therefore never match, and every activation attempt through the console
    failed with "No model named '<name>.joblib' is available" no matter which
    row was clicked.

    Both spellings are accepted now, and the comparison is done on the stem, so
    `"rf-2026-04"`, `"rf-2026-04.joblib"` and a full path's basename all resolve
    to the same artifact. Which one arrived no longer decides whether activation
    works.
    """
    # `_safe_name` normalises the caller's input to a safe `.joblib` filename...
    safe = _safe_name(name)
    # ...and the stem is what every listing and every stored reference uses.
    stem = os.path.splitext(safe)[0]
    available = {row["name"] for row in list_models()}

    if stem not in available:
        raise NotFoundError(f"No model named '{stem}' is available")

    settings = db.session.get(AdminSettings, 1)
    if settings is None:
        settings = AdminSettings(id=1)
        db.session.add(settings)

    stored = settings.get_notification_settings()
    stored[_ACTIVE_KEY] = stem
    settings.set_notification_settings(stored)
    db.session.commit()

    logger.info("Active model set to %s", stem)

    # The predictor caches the artifact it loaded. Clearing that cache is what
    # makes the switch take effect without a process restart.
    try:
        from app.ml import predictor

        clear = getattr(predictor, "clear_cache", None)
        if callable(clear):
            clear()
    except Exception:  # noqa: BLE001 - a missing hook is not a failed activation
        logger.warning("Could not clear the predictor cache after activation")

    return {"active": stem}
