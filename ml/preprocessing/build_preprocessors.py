"""Preprocessing objects for the water_quality model.

Two fitted transformers are saved with joblib so training and serving use the
exact same objects — the same imputation medians and the same scaling means:

    preprocessing/imputer.joblib   SimpleImputer(strategy="median")
    preprocessing/scaler.joblib    StandardScaler()

`build_preprocessors()` fits them on training data; `save_preprocessors()` and
`load_preprocessors()` persist and restore them.
"""

import os

import joblib
import numpy as np
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler

FEATURES = ("ph", "turbidity", "tds", "temperature", "dissolved_oxygen")

IMPUTER_FILE = "imputer.joblib"
SCALER_FILE = "scaler.joblib"


def build_preprocessors(features: np.ndarray) -> tuple[SimpleImputer, StandardScaler]:
    """Fit the imputer (median) and scaler on the training feature matrix."""
    imputer = SimpleImputer(strategy="median")
    imputed = imputer.fit_transform(features)

    scaler = StandardScaler()
    scaler.fit(imputed)
    return imputer, scaler


def transform(features: np.ndarray, imputer: SimpleImputer, scaler: StandardScaler) -> np.ndarray:
    """Apply the fitted imputer then scaler, in that order."""
    return scaler.transform(imputer.transform(features))


def save_preprocessors(directory: str, imputer: SimpleImputer, scaler: StandardScaler) -> dict:
    """Persist both preprocessors and return their file paths."""
    os.makedirs(directory, exist_ok=True)
    imputer_path = os.path.join(directory, IMPUTER_FILE)
    scaler_path = os.path.join(directory, SCALER_FILE)

    joblib.dump(imputer, imputer_path)
    joblib.dump(scaler, scaler_path)
    return {"imputer": imputer_path, "scaler": scaler_path}


def load_preprocessors(directory: str) -> tuple[SimpleImputer, StandardScaler]:
    """Load the saved imputer and scaler from disk."""
    imputer = joblib.load(os.path.join(directory, IMPUTER_FILE))
    scaler = joblib.load(os.path.join(directory, SCALER_FILE))
    return imputer, scaler
