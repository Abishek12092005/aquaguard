"""Train and evaluate one model per supported input configuration.

Produces 31 estimators — every non-empty subset of the five parameters — and a
metadata file recording, for each one, the features it uses and its held-out
validation metrics. The prediction service reads that metadata to decide how much
confidence to express in a given answer.

Run from the project root:
    python ml/train_subset_models.py

WHY TRAIN PER SUBSET RATHER THAN IMPUTE. See the module docstring in
`feature_subsets.py`. In short: imputing a missing parameter and then reporting the
five-feature model's accuracy would be a fabricated result. A model trained on pH
alone is genuinely a pH-only model, and its score honestly reflects how little pH
alone can tell you.

WHY THE SAME HYPERPARAMETERS FOR EVERY SUBSET. The five-feature model keeps the
project's existing hyperparameters so its behaviour is unchanged. The subsets use
the same settings deliberately: comparing configurations is only meaningful if
the only thing that varies between them is the input data. Tuning each subset
separately would make the comparison a measure of tuning effort, not of
information content.

The output is written alongside the existing five-feature artifacts and does not
replace them, so the current API contract keeps working unchanged.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder, StandardScaler

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from feature_subsets import CONFIGS_BY_SIZE, FEATURES, FULL_CONFIG, all_configs  # noqa: E402

DATASET_PATH = os.path.join(HERE, "dataset", "water_quality.csv")
MODEL_DIR = os.path.join(HERE, "model")
SUBSET_DIR = os.path.join(MODEL_DIR, "subsets")
SUBSET_METADATA_FILE = os.path.join(MODEL_DIR, "subset_metadata.json")

TARGET = "water_quality"
LABELS = ("MODERATE", "SAFE", "UNSAFE")  # sorted, matching LabelEncoder
RANDOM_STATE = 42

# Identical to the five-feature model's settings, so a comparison between
# configurations is a comparison of information, not of tuning.
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

VALID_RANGES = {
    "ph": (0.0, 14.0),
    "turbidity": (0.0, 1000.0),
    "tds": (0.0, 50000.0),
    "temperature": (-5.0, 100.0),
    "dissolved_oxygen": (0.0, 20.0),
}

# A configuration is only described as reliable when its macro-F1 clears this.
#
# Macro-F1 rather than accuracy, deliberately. Accuracy on a class-imbalanced
# three-class problem can be high while a whole class is never predicted —
# a model that answers SAFE for everything scores whatever the SAFE proportion
# happens to be. Macro-F1 averages the per-class scores, so a configuration that
# cannot recognise one of the three conditions is penalised for it.
#
# The threshold is data, not a claim: it is written into the metadata and the API
# reads it from there, so the number the UI shows as the bar is the number that
# was actually applied.
MIN_MACRO_F1 = 0.60

# A subset must also beat the largest-class baseline to be worth calling
# informative at all. This is the floor against which "better than guessing" is
# measured.
TRIVIAL_BASELINE_MARGIN = 0.05


def load_and_clean(path: str) -> pd.DataFrame:
    """Load the dataset and apply the same cleaning the five-feature model uses.

    Repeated here rather than imported so this script stays runnable on its own,
    which matters when regenerating artifacts on a machine that has the dataset
    but a different backend checkout. The rules are identical to
    `train_model.py`; a divergence would make the two models incomparable.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"Dataset not found: {path}\n"
            "Generate one first:  python ml/dataset/generate_dataset.py"
        )

    frame = pd.read_csv(path)
    frame.columns = [c.strip().lower().replace(" ", "_") for c in frame.columns]

    required = list(FEATURES) + [TARGET]
    missing = [c for c in required if c not in frame.columns]
    if missing:
        raise ValueError(f"Dataset is missing required columns: {missing}")

    frame = frame.dropna(subset=[TARGET])
    for column in FEATURES:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    keep = pd.Series(True, index=frame.index)
    for column, (low, high) in VALID_RANGES.items():
        keep &= frame[column].isna() | frame[column].between(low, high)
    frame = frame[keep]

    frame[TARGET] = frame[TARGET].astype(str).str.strip().str.upper()
    frame = frame[frame[TARGET].isin(LABELS)]
    return frame


def train_one(
    frame: pd.DataFrame,
    features: tuple[str, ...],
    encoder: LabelEncoder,
    x_train_idx: np.ndarray,
    x_test_idx: np.ndarray,
) -> tuple[RandomForestClassifier, SimpleImputer, StandardScaler, np.ndarray, np.ndarray]:
    """Fit preprocessing + estimator for one feature subset.

    The split indices are passed in and reused for every subset, so all 31 models
    are evaluated on exactly the same held-out rows. Without a shared split the
    scores would differ partly because of which rows landed in the test set, and
    comparing configurations would be comparing luck.

    The imputer is still fitted per subset. Even inside a subset a column can hold
    NaNs (the dataset deliberately contains some), and the median must come from
    that subset's own training rows.
    """
    columns = list(features)
    x_all = frame[columns].to_numpy(dtype=float)
    y_all = encoder.transform(frame[TARGET])

    x_train, x_test = x_all[x_train_idx], x_all[x_test_idx]
    y_train, y_test = y_all[x_train_idx], y_all[x_test_idx]

    # Fitted on training rows only, so no test information leaks into the medians
    # or the scaling statistics.
    imputer = SimpleImputer(strategy="median")
    x_train = imputer.fit_transform(x_train)
    x_test = imputer.transform(x_test)

    scaler = StandardScaler()
    x_train = scaler.fit_transform(x_train)
    x_test = scaler.transform(x_test)

    model = RandomForestClassifier(**HYPERPARAMS)
    model.fit(x_train, y_train)

    return model, imputer, scaler, x_test, y_test


def evaluate(model, x_test: np.ndarray, y_test: np.ndarray, encoder: LabelEncoder) -> dict:
    """Held-out metrics for one configuration.

    Reports accuracy, macro precision/recall/F1 and the confusion matrix, which is
    what the project brief asks to compare configurations on. `predictions` are
    kept in the returned dict for the baseline comparison below but are stripped
    before the metadata is written.
    """
    predictions = model.predict(x_test)

    accuracy = float(accuracy_score(y_test, predictions))
    macro_precision = float(precision_score(y_test, predictions, average="macro", zero_division=0))
    macro_recall = float(recall_score(y_test, predictions, average="macro", zero_division=0))
    macro_f1 = float(f1_score(y_test, predictions, average="macro", zero_division=0))
    matrix = confusion_matrix(y_test, predictions, labels=range(len(encoder.classes_))).tolist()
    report = classification_report(
        y_test,
        predictions,
        labels=range(len(encoder.classes_)),
        target_names=list(encoder.classes_),
        output_dict=True,
        zero_division=0,
    )

    return {
        "accuracy": round(accuracy, 4),
        "macro_precision": round(macro_precision, 4),
        "macro_recall": round(macro_recall, 4),
        "macro_f1": round(macro_f1, 4),
        "confusion_matrix": matrix,
        "per_class": {
            label: {
                "precision": round(float(report[label]["precision"]), 4),
                "recall": round(float(report[label]["recall"]), 4),
                "f1": round(float(report[label]["f1-score"]), 4),
                "support": int(report[label]["support"]),
            }
            for label in encoder.classes_
        },
        "predictions": predictions,
    }


def main() -> int:
    print("=" * 74)
    print("AquaGuard AI - feature-subset model training")
    print("=" * 74)

    frame = load_and_clean(DATASET_PATH)
    print(f"\nDataset: {DATASET_PATH}")
    print(f"Rows after cleaning: {len(frame)}")

    encoder = LabelEncoder()
    encoder.fit(list(LABELS))

    # One shared split for all configurations. Stratified so every subset sees the
    # same class balance, which matters because the subsets are being compared.
    indices = np.arange(len(frame))
    train_idx, test_idx = train_test_split(
        indices, test_size=0.2, random_state=RANDOM_STATE, stratify=encoder.transform(frame[TARGET])
    )
    print(f"Train rows: {len(train_idx)}   Test rows: {len(test_idx)} (shared by all subsets)")

    # The majority-class share of the test set: the score a model that always
    # predicted one label would get. Used to detect a configuration whose "skill"
    # is really just the class distribution.
    y_test_all = encoder.transform(frame[TARGET])[test_idx]
    baseline = float(np.bincount(y_test_all).max() / len(y_test_all))
    print(f"Majority-class baseline: {baseline:.4f}")

    os.makedirs(SUBSET_DIR, exist_ok=True)

    configs = all_configs()
    print(f"\nTraining {len(configs)} configurations...\n")

    results: dict[str, dict] = {}
    rows: list[dict] = []

    for index, key in enumerate(configs, start=1):
        features = tuple(key.split("+"))
        model, imputer, scaler, x_test, y_test = train_one(
            frame, features, encoder, train_idx, test_idx
        )
        metrics = evaluate(model, x_test, y_test, encoder)

        artifact = {
            "model": model,
            "imputer": imputer,
            "scaler": scaler,
            "features": list(features),
            "config": key,
            "labels": list(encoder.classes_),
            "model_version": f"water-quality-subset-v1.0.0::{key}",
            "trained_at": datetime.now(timezone.utc).isoformat(),
        }
        joblib.dump(artifact, os.path.join(SUBSET_DIR, f"{key}.joblib"))

        informative = metrics["macro_f1"] >= MIN_MACRO_F1
        beats_baseline = metrics["accuracy"] > baseline + TRIVIAL_BASELINE_MARGIN

        results[key] = {
            "config": key,
            "features": list(features),
            "feature_count": len(features),
            "model_file": f"{key}.joblib",
            "accuracy": metrics["accuracy"],
            "macro_precision": metrics["macro_precision"],
            "macro_recall": metrics["macro_recall"],
            "macro_f1": metrics["macro_f1"],
            "confusion_matrix": metrics["confusion_matrix"],
            "per_class": metrics["per_class"],
            # The two independent judgements about whether this configuration is
            # worth trusting. Both are recorded, so the API can explain which one
            # failed rather than only reporting a boolean.
            "meets_threshold": bool(informative),
            "beats_baseline": bool(beats_baseline),
            "reliable": bool(informative and beats_baseline),
        }

        rows.append(
            {
                "config": key,
                "n": len(features),
                "acc": metrics["accuracy"],
                "f1": metrics["macro_f1"],
                "precision": metrics["macro_precision"],
                "recall": metrics["macro_recall"],
                "reliable": results[key]["reliable"],
            }
        )
        print(
            f"  [{index:>2}/{len(configs)}] {key:<46} "
            f"acc={metrics['accuracy']:.4f}  macroF1={metrics['macro_f1']:.4f}  "
            f"{'RELIABLE' if results[key]['reliable'] else 'limited'}"
        )

    # --- Summary by configuration size ------------------------------------
    print("\n" + "=" * 74)
    print("Mean validation score by number of parameters supplied")
    print("=" * 74)
    print(f"  {'params':<8}{'configs':<10}{'mean acc':<12}{'mean macroF1':<14}{'reliable'}")
    by_size: dict[str, dict] = {}
    for size, keys in CONFIGS_BY_SIZE.items():
        subset = [results[k] for k in keys]
        mean_acc = float(np.mean([r["accuracy"] for r in subset]))
        mean_f1 = float(np.mean([r["macro_f1"] for r in subset]))
        reliable = sum(1 for r in subset if r["reliable"])
        by_size[str(size)] = {
            "config_count": len(keys),
            "mean_accuracy": round(mean_acc, 4),
            "mean_macro_f1": round(mean_f1, 4),
            "reliable_count": reliable,
            "configs": list(keys),
        }
        print(f"  {size:<8}{len(keys):<10}{mean_acc:<12.4f}{mean_f1:<14.4f}{reliable}/{len(keys)}")

    reliable_total = sum(1 for r in results.values() if r["reliable"])
    print(f"\n  Configurations meeting the reliability bar: {reliable_total}/{len(configs)}")
    print(f"  Threshold: macro-F1 >= {MIN_MACRO_F1} AND accuracy > baseline + {TRIVIAL_BASELINE_MARGIN}")

    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "training_version": "subset-v1.0.0",
        "dataset": os.path.basename(DATASET_PATH),
        "row_count": int(len(frame)),
        "train_rows": int(len(train_idx)),
        "test_rows": int(len(test_idx)),
        "random_state": RANDOM_STATE,
        "class_labels": list(encoder.classes_),
        "hyperparameters": HYPERPARAMS,
        "full_config": FULL_CONFIG,
        # The thresholds are part of the artifact, so the running service reads the
        # bar that was actually applied instead of carrying its own copy.
        "reliability_policy": {
            "min_macro_f1": MIN_MACRO_F1,
            "baseline_margin": TRIVIAL_BASELINE_MARGIN,
            "majority_class_baseline": round(baseline, 4),
        },
        "summary_by_size": by_size,
        "configs": results,
    }

    with open(SUBSET_METADATA_FILE, "w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2)

    print(f"\nArtifacts: {SUBSET_DIR}")
    print(f"Metadata : {SUBSET_METADATA_FILE}")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
