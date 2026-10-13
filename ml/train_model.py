"""Train the AquaGuard water-quality classifier.

Water quality category prediction (SAFE / MODERATE / UNSAFE) from five measured
parameters, using a Random Forest Classifier.

Pipeline (see ml/README.md for the documented contract):

    1.  Load dataset
    2.  Inspect dataset
    3.  Handle missing values
    4.  Remove invalid records
    5.  Select features
    6.  Select target
    7.  Encode target
    8.  Split train/test
    9.  Train Random Forest
    10. Evaluate model
    11. Classification report
    12. Save trained model (joblib)
    13. Save preprocessing objects (joblib)

Run from the project root:
    python ml/train_model.py
"""

import json
import os
import sys
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
)
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from preprocessing.build_preprocessors import (  # noqa: E402
    FEATURES,
    build_preprocessors,
    save_preprocessors,
    transform,
)

HERE = os.path.dirname(os.path.abspath(__file__))

DATASET_PATH = os.path.join(HERE, "dataset", "water_quality.csv")
MODEL_DIR = os.path.join(HERE, "model")
PREPROCESSING_DIR = os.path.join(HERE, "preprocessing")

TARGET = "water_quality"
LABELS = ("SAFE", "MODERATE", "UNSAFE")
MODEL_FILE = "water_quality_rf.joblib"
METADATA_FILE = "model_metadata.json"

RANDOM_STATE = 42

# Physically-valid ranges. Rows outside these are corrupt measurements, not
# unusual-but-real water, so they are removed rather than clamped.
VALID_RANGES = {
    "ph": (0.0, 14.0),
    "turbidity": (0.0, 1000.0),
    "tds": (0.0, 50000.0),
    "temperature": (-5.0, 100.0),
    "dissolved_oxygen": (0.0, 20.0),
}

HYPERPARAMS = {
    "n_estimators": 300,
    "max_depth": None,
    "min_samples_split": 4,
    "min_samples_leaf": 2,
    "max_features": "sqrt",
    "class_weight": "balanced",
    "random_state": RANDOM_STATE,
    "n_jobs": -1,
}


# --------------------------------------------------------------------------
# 1. Load
# --------------------------------------------------------------------------
def load_dataset(path: str) -> pd.DataFrame:
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"Dataset not found: {path}\n"
            "Generate one first:  python ml/dataset/generate_dataset.py"
        )
    frame = pd.read_csv(path)
    frame.columns = [column.strip().lower().replace(" ", "_") for column in frame.columns]
    return frame


# --------------------------------------------------------------------------
# 2. Inspect
# --------------------------------------------------------------------------
def inspect_dataset(frame: pd.DataFrame) -> None:
    print("\n[2] Dataset inspection")
    print(f"    shape            : {frame.shape[0]} rows x {frame.shape[1]} columns")
    print(f"    columns          : {', '.join(frame.columns)}")
    print("    dtypes           :")
    for column, dtype in frame.dtypes.items():
        print(f"        {column:<18} {dtype}")
    print("    missing values   :")
    missing = frame.isna().sum()
    for column, count in missing.items():
        if count:
            print(f"        {column:<18} {count}")
    if missing.sum() == 0:
        print("        (none)")
    print(f"    duplicate rows   : {int(frame.duplicated().sum())}")
    print("    class distribution (raw):")
    for label, count in frame[TARGET].value_counts().items():
        print(f"        {label:<9} {count}")


# --------------------------------------------------------------------------
# 3 + 4. Clean
# --------------------------------------------------------------------------
def clean(frame: pd.DataFrame) -> pd.DataFrame:
    print("\n[3] Handling missing values")
    print(f"    rows before      : {len(frame)}")

    required = list(FEATURES) + [TARGET]
    missing_columns = [column for column in required if column not in frame.columns]
    if missing_columns:
        raise ValueError(f"Dataset is missing required columns: {missing_columns}")

    # Rows with no target label cannot be used for supervised training.
    frame = frame.dropna(subset=[TARGET])

    # Coerce features to numeric; anything non-numeric becomes NaN and is then
    # imputed. This also drops stray strings the CSV might carry.
    for column in FEATURES:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    # Median imputation per feature. Imputation is done AFTER invalid-record
    # removal (below) would be an option, but the model's preprocessing object
    # re-imputes at serve time, so we keep the raw NaNs for the imputer to learn
    # from and only report the count here.
    print(f"    feature NaNs     : {int(frame[list(FEATURES)].isna().sum().sum())} (imputed by the saved imputer)")

    print("\n[4] Removing invalid records")
    weight = pd.Series(True, index=frame.index)
    for column, (low, high) in VALID_RANGES.items():
        # NaN is allowed here (imputed later); only real out-of-range values fail.
        in_range = frame[column].isna() | frame[column].between(low, high)
        weight &= in_range

    removed = int((~weight).sum())
    frame = frame[weight]
    print(f"    out-of-range rows: {removed}")
    print(f"    rows after       : {len(frame)}")

    frame[TARGET] = frame[TARGET].astype(str).str.strip().str.upper()
    frame = frame[frame[TARGET].isin(LABELS)]
    print(f"    rows with a valid label: {len(frame)}")
    return frame


# --------------------------------------------------------------------------
# 5 + 6 + 7. Features, target, encoding
# --------------------------------------------------------------------------
def select_features_and_target(frame: pd.DataFrame):
    print("\n[5] Selecting features")
    print(f"    features : {list(FEATURES)}")

    print("\n[6] Selecting target")
    print(f"    target   : {TARGET}")

    print("\n[7] Encoding target")
    encoder = LabelEncoder()
    encoder.fit(list(LABELS))
    encoded = encoder.transform(frame[TARGET])
    print(f"    classes  : {list(encoder.classes_)}")
    mapping = {int(i): str(c) for i, c in enumerate(encoder.classes_)}
    print(f"    mapping  : {mapping}")

    return frame[list(FEATURES)].to_numpy(dtype=float), encoded, encoder


# --------------------------------------------------------------------------
# 8. Split
# --------------------------------------------------------------------------
def split(features: np.ndarray, target: np.ndarray):
    print("\n[8] Splitting train/test")
    x_train, x_test, y_train, y_test = train_test_split(
        features,
        target,
        test_size=0.2,
        random_state=RANDOM_STATE,
        stratify=target,
    )
    print(f"    train    : {len(x_train)} rows")
    print(f"    test     : {len(x_test)} rows")
    return x_train, x_test, y_train, y_test


# --------------------------------------------------------------------------
# 9. Train
# --------------------------------------------------------------------------
def train_model(x_train: np.ndarray, y_train: np.ndarray) -> RandomForestClassifier:
    print("\n[9] Training Random Forest")
    model = RandomForestClassifier(**HYPERPARAMS)
    model.fit(x_train, y_train)
    print(f"    hyperparameters: {json.dumps(HYPERPARAMS)}")
    return model


# --------------------------------------------------------------------------
# 10 + 11. Evaluate
# --------------------------------------------------------------------------
def evaluate(model, x_test, y_test, encoder, feature_importances: dict) -> dict:
    predictions = model.predict(x_test)

    accuracy = float(accuracy_score(y_test, predictions))
    matrix = confusion_matrix(y_test, predictions).tolist()
    report = classification_report(
        y_test, predictions, target_names=list(encoder.classes_), output_dict=True, zero_division=0
    )

    print("\n[10] Evaluation (held-out test set)")
    print(f"    accuracy : {accuracy:.4f}")
    print(f"    confusion matrix (rows=true, cols=predicted): {matrix}")

    print("\n[11] Classification report")
    print(
        classification_report(
            y_test, predictions, target_names=list(encoder.classes_), zero_division=0
        )
    )

    print("    feature importances:")
    for name, importance in sorted(feature_importances.items(), key=lambda kv: kv[1], reverse=True):
        print(f"        {name:<18} {importance:.4f}")

    return {
        "accuracy": round(accuracy, 4),
        "confusion_matrix": matrix,
        "report": report,
        "feature_importances": feature_importances,
    }


# --------------------------------------------------------------------------
# 12 + 13. Persist
# --------------------------------------------------------------------------
def save_model(model, encoder, imputer, scaler, metadata: dict) -> dict:
    os.makedirs(MODEL_DIR, exist_ok=True)

    model_path = os.path.join(MODEL_DIR, MODEL_FILE)
    joblib.dump(model, model_path)

    encoder_path = os.path.join(MODEL_DIR, "label_encoder.joblib")
    joblib.dump(encoder, encoder_path)

    print("\n[12] Saving trained model (joblib)")
    print(f"    {model_path}")
    print(f"    {encoder_path}")

    print("\n[13] Saving preprocessing objects (joblib)")
    paths = save_preprocessors(PREPROCESSING_DIR, imputer, scaler)
    for name, path in paths.items():
        print(f"    {name:<8} {path}")

    metadata_path = os.path.join(MODEL_DIR, METADATA_FILE)
    with open(metadata_path, "w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2)
    print(f"    metadata {metadata_path}")

    return {"model": model_path, "encoder": encoder_path, "metadata": metadata_path, **paths}


def main() -> int:
    print("=" * 70)
    print("AquaGuard AI - water quality model training")
    print("=" * 70)

    frame = load_dataset(DATASET_PATH)
    inspect_dataset(frame)
    frame = clean(frame)

    features, target, encoder = select_features_and_target(frame)
    x_train, x_test, y_train, y_test = split(features, target)

    # Fit preprocessing on TRAINING data only, so no test information leaks into
    # the imputer medians or the scaler statistics.
    imputer, scaler = build_preprocessors(x_train)
    x_train_scaled = transform(x_train, imputer, scaler)
    x_test_scaled = transform(x_test, imputer, scaler)

    model = train_model(x_train_scaled, y_train)

    feature_importances = {
        name: round(float(model.feature_importances_[i]), 4) for i, name in enumerate(FEATURES)
    }
    metrics = evaluate(model, x_test_scaled, y_test, encoder, feature_importances)

    metadata = {
        "model_name": "RandomForestClassifier",
        "model_version": "water-quality-rf-v1.0.0",
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "random_state": RANDOM_STATE,
        "dataset": os.path.basename(DATASET_PATH),
        "row_count": int(len(frame)),
        "features": list(FEATURES),
        "target": TARGET,
        "classes": list(encoder.classes_),
        "hyperparameters": HYPERPARAMS,
        "metrics": metrics,
    }
    paths = save_model(model, encoder, imputer, scaler, metadata)

    print("\n" + "=" * 70)
    print(f"Done. Test accuracy: {metrics['accuracy']:.4f}")
    print(f"Artifacts written under: {os.path.dirname(paths['model'])}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
