"""Offline training entrypoint for the AquaGuard Random Forest classifier.

Run as a module so it picks up the application configuration:

    python -m app.ml.train --csv ../ml/datasets/water_potability.csv

The script writes a single self-describing artifact:

    {"model": <RandomForestClassifier>, "metadata": {...}}

`app.ml.model_loader` understands exactly this shape, and `predictor.predict`
reads `metadata` for the model name/version stamped onto every stored
prediction.
"""

import argparse
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split

from app.constants import FEATURE_NAMES

TARGET_COLUMN = "Potability"
MODEL_VERSION = "rf-v1.0.0"

DEFAULT_HYPERPARAMS = {
    "n_estimators": 300,
    "max_depth": None,
    "min_samples_split": 4,
    "min_samples_leaf": 2,
    "max_features": "sqrt",
    "class_weight": "balanced",  # the potability dataset is mildly imbalanced
    "random_state": 42,
    "n_jobs": -1,
}


def load_dataset(csv_path: str) -> pd.DataFrame:
    """Read and clean the raw dataset.

    Medians are imputed per feature (not dropped) because missing values in the
    public water potability data are missing-at-random and dropping rows would
    bias the model toward the majority class.
    """
    if not os.path.isfile(csv_path):
        raise FileNotFoundError(f"Dataset not found: {csv_path}")

    frame = pd.read_csv(csv_path)

    # Accept both the canonical capitalised headers and snake_case variants.
    rename_map = {column: column.strip().lower().replace(" ", "_") for column in frame.columns}
    frame = frame.rename(columns=rename_map)

    if "potability" in frame.columns:
        frame = frame.rename(columns={"potability": TARGET_COLUMN})
    elif TARGET_COLUMN not in frame.columns:
        raise ValueError(f"Target column {TARGET_COLUMN!r} not found in dataset")

    missing = [name for name in FEATURE_NAMES if name not in frame.columns]
    if missing:
        raise ValueError(f"Dataset is missing required feature columns: {missing}")

    for name in FEATURE_NAMES:
        frame[name] = pd.to_numeric(frame[name], errors="coerce")
        frame[name] = frame[name].fillna(frame[name].median())

    frame = frame.dropna(subset=[TARGET_COLUMN])
    frame[TARGET_COLUMN] = frame[TARGET_COLUMN].astype(int)
    return frame[list(FEATURE_NAMES) + [TARGET_COLUMN]]


def train(csv_path: str, output_path: str) -> dict:
    """Train, evaluate and persist the classifier. Returns the metadata dict."""
    import pickle

    frame = load_dataset(csv_path)
    # Kept as DataFrames (not raw numpy) so the fitted estimator carries feature
    # names and inference does not emit a "fitted without feature names" warning.
    feature_frame = frame[list(FEATURE_NAMES)].astype(float)
    target = frame[TARGET_COLUMN].to_numpy(dtype=int)
    features = feature_frame.to_numpy(dtype=float)

    x_train, x_test, y_train, y_test = train_test_split(
        feature_frame, target, test_size=0.2, random_state=42, stratify=target
    )

    model = RandomForestClassifier(**DEFAULT_HYPERPARAMS)
    model.fit(x_train, y_train)

    y_pred = model.predict(x_test)
    y_proba = model.predict_proba(x_test)[:, 1]

    metrics = {
        "accuracy": round(float(accuracy_score(y_test, y_pred)), 4),
        "roc_auc": round(float(roc_auc_score(y_test, y_proba)), 4),
        "confusion_matrix": confusion_matrix(y_test, y_pred).tolist(),
        "report": classification_report(y_test, y_pred, output_dict=True),
    }

    # Ship the training means inside the artifact so `predictor` can compute
    # local feature contributions without re-reading the dataset.
    model._training_stats = {
        "mean": {name: float(np.mean(features[:, i])) for i, name in enumerate(FEATURE_NAMES)},
        "std": {name: float(np.std(features[:, i])) for i, name in enumerate(FEATURE_NAMES)},
    }

    metadata = {
        "model_name": "random_forest",
        "model_version": MODEL_VERSION,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "dataset": os.path.basename(csv_path),
        "row_count": int(len(frame)),
        "feature_names": list(FEATURE_NAMES),
        "hyperparameters": DEFAULT_HYPERPARAMS,
        "feature_importances": {
            name: round(float(model.feature_importances_[i]), 4)
            for i, name in enumerate(FEATURE_NAMES)
        },
        "metrics": metrics,
    }

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "wb") as handle:
        pickle.dump({"model": model, "metadata": metadata}, handle)

    print(f"Artifact written to {output_path}")
    print(f"  accuracy : {metrics['accuracy']}")
    print(f"  roc_auc  : {metrics['roc_auc']}")
    return metadata


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train the AquaGuard Random Forest model")
    parser.add_argument(
        "--csv",
        default=os.path.join(os.path.dirname(__file__), "..", "..", "..", "ml", "datasets", "water_potability.csv"),
        help="Path to the training CSV",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output .pkl path (defaults to the configured model directory)",
    )
    args = parser.parse_args(argv)

    if args.out:
        output_path = args.out
    else:
        from app import create_app
        from app.config import get_config

        app = create_app()
        output_path = os.path.join(
            app.config["ML_MODEL_DIR"], app.config["ML_MODEL_FILENAME"]
        )

    try:
        train(os.path.abspath(args.csv), os.path.abspath(output_path))
    except (FileNotFoundError, ValueError) as exc:
        print(f"Training failed: {exc}", file=sys.stderr)
        print(
            "\nPlace the water potability CSV at ml/datasets/water_potability.csv "
            "or pass --csv <path>.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
