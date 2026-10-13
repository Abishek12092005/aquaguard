# AquaGuard AI — ML pipeline

Standalone training workspace for the water-quality classifier. The Flask
backend consumes the artifacts this directory produces; it never trains on
import.

```
ml/
├── dataset/
│   ├── generate_dataset.py     builds the water_quality dataset
│   └── water_quality.csv       generated training data
├── preprocessing/
│   ├── build_preprocessors.py  fits/saves the imputer + scaler
│   ├── imputer.joblib          saved SimpleImputer(median)
│   └── scaler.joblib           saved StandardScaler
├── model/
│   ├── water_quality_rf.joblib RandomForestClassifier
│   ├── label_encoder.joblib    LabelEncoder over the three classes
│   └── model_metadata.json     version, features, hyperparameters, metrics
├── train_model.py              the 13-step training pipeline
├── predict.py                  load artifacts + predict() callable
└── README.md
```

## How to run

```powershell
# 1. Build the dataset
python ml/dataset/generate_dataset.py --rows 4000

# 2. Train + evaluate + save artifacts
python ml/train_model.py

# 3. Smoke-test inference
python ml/predict.py
```

## Dataset

| | |
| --- | --- |
| File | `ml/dataset/water_quality.csv` |
| Rows | 4000 (before cleaning) |
| Source | `dataset/generate_dataset.py` — a synthetic set built from WHO / BIS-flavoured drinking-water thresholds |
| Deliberately dirty | ~2.5% missing feature values + ~0.8% physically-invalid rows, so the cleaning steps are exercised |

The generator scores each sample with smooth, physically-motivated terms (pH
near neutral, low turbidity, moderate TDS, cool water, healthy dissolved
oxygen), adds noise so the classes overlap, and cuts the score at the 30th and
65th percentiles into the three ordered classes. This yields a realistic,
imbalanced, non-trivially-separable problem rather than a perfect one.

> Replace `water_quality.csv` with real field data when available — the column
> contract is all the pipeline depends on.

## Features

Five measured parameters, in canonical order:

| Feature | Unit | Valid range |
| --- | --- | --- |
| `ph` | pH | 0 – 14 |
| `turbidity` | NTU | 0 – 1000 |
| `tds` | mg/L | 0 – 50000 |
| `temperature` | °C | −5 – 100 |
| `dissolved_oxygen` | mg/L | 0 – 20 |

## Target

| | |
| --- | --- |
| Column | `water_quality` |
| Classes | `SAFE`, `MODERATE`, `UNSAFE` |
| Encoding | `LabelEncoder` (alphabetical: MODERATE=0, SAFE=1, UNSAFE=2), saved as `model/label_encoder.joblib` |

## Model

| | |
| --- | --- |
| Algorithm | `sklearn.ensemble.RandomForestClassifier` |
| `n_estimators` | 300 |
| `max_depth` | None |
| `min_samples_split` / `min_samples_leaf` | 4 / 2 |
| `max_features` | `sqrt` |
| `class_weight` | `balanced` |
| `random_state` | 42 (reproducible) |

Preprocessing is fit on the training split only (no test leakage):

1. `SimpleImputer(strategy="median")` — fills missing values.
2. `StandardScaler()` — centres and scales the five features.

Both objects are saved with `joblib` and re-applied at serve time, so training
and inference use the identical transformation.

## Metrics

Measured on a held-out 20% test split (`random_state=42`, stratified). These are
printed by `train_model.py` — no figure is hardcoded.

| Metric | Value |
| --- | --- |
| Accuracy | **0.6071** |
| Macro precision | 0.61 |
| Macro recall | 0.61 |
| Macro F1 | 0.61 |

Per-class F1 is roughly even across `SAFE`, `MODERATE` and `UNSAFE`. Accuracy is
modest by design: the synthetic classes overlap heavily (the score term for each
feature is a smooth Gaussian plus noise), so ~0.61 is an honest result for a
3-class problem where neighbouring classes are genuinely ambiguous. Real,
better-separated data would raise it.

Confusion matrix and the full per-class report are printed during training and
stored under `metrics` in `model/model_metadata.json`.

## Calling it from Flask

`backend/app/ml/water_quality.py` imports this package and adapts its output:

```python
from app.ml import water_quality

result = water_quality.predict({
    "ph": 7.1, "turbidity": 1.2, "tds": 280.0,
    "temperature": 18.0, "dissolved_oxygen": 8.4,
})
# {"label": "SAFE", "risk_level": "safe", "confidence": 0.9522,
#  "probabilities": {"safe": 0.9522, "moderate": 0.0444, "unsafe": 0.0035}, ...}
```

If the artifact is missing, the bridge raises `MLModelError`, which the API
surfaces as a `503` naming the train command — it never returns a fabricated
prediction.
