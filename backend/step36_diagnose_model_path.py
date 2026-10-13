"""STEP 36 - diagnose why the model-less sandbox still answered 201.

The sandbox ml/ tree genuinely has no forest, yet the API returned a real
verdict from `water-quality-rf-v1.0.0`. Something is still resolving the REAL
ml/ tree. This resolves it explicitly rather than guessing.
"""

import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
SOURCE_ML = os.path.join(os.path.dirname(HERE), "ml")

sandbox_root = tempfile.mkdtemp(prefix="aquaguard_diag_")
sandbox_ml = os.path.join(sandbox_root, "ml")
shutil.copytree(
    SOURCE_ML, sandbox_ml,
    ignore=shutil.ignore_patterns("__pycache__", "*.joblib", "subsets", "datasets"),
)
for name in ("imputer.joblib", "scaler.joblib"):
    src = os.path.join(SOURCE_ML, "preprocessing", name)
    if os.path.isfile(src):
        shutil.copy2(src, os.path.join(sandbox_ml, "preprocessing", name))
encoder = os.path.join(SOURCE_ML, "model", "label_encoder.joblib")
if os.path.isfile(encoder):
    shutil.copy2(encoder, os.path.join(sandbox_ml, "model", "label_encoder.joblib"))

print(f"sandbox ml/       : {sandbox_ml}")
print(f"forest in sandbox : {os.path.isfile(os.path.join(sandbox_ml, 'model', 'water_quality_rf.joblib'))}")
print(f"forest in real    : {os.path.isfile(os.path.join(SOURCE_ML, 'model', 'water_quality_rf.joblib'))}")

os.environ["ML_WATER_QUALITY_DIR"] = sandbox_ml
os.environ["ML_MODEL_DIR"] = os.path.join(sandbox_root, "no_legacy_model")
os.makedirs(os.environ["ML_MODEL_DIR"], exist_ok=True)

from app import create_app  # noqa: E402
from app.ml import water_quality  # noqa: E402

app = create_app("testing")
with app.app_context():
    print(f"\nML_WATER_QUALITY_DIR = {app.config['ML_WATER_QUALITY_DIR']}")
    print(f"_ml_root()           = {water_quality._ml_root()}")
    print(f"is_available()       = {water_quality.is_available()}")
    print(f"metadata()           = {water_quality.metadata()}")

    pipeline = water_quality._load_pipeline()
    print(f"\nresolved pipeline module file = {pipeline.__file__}")
    print(f"its MODEL_DIR                 = {pipeline.MODEL_DIR}")
    print(f"its model file present        = {os.path.isfile(os.path.join(pipeline.MODEL_DIR, pipeline.MODEL_FILE))}")

    # The legacy binary forest is the OTHER source of a prediction. If it is
    # still installed, it can answer even with the 3-class model missing.
    from app.ml.model_loader import _model_path, is_model_available

    print(f"\nlegacy model path   = {_model_path()}")
    print(f"legacy is_available = {is_model_available()}")

print("\n--- what the API would do ---")
with app.app_context():
    from app.ml.predictor import predict_three_class

    row = {"ph": 7.2, "turbidity": 1.5, "tds": 300.0, "temperature": 25.0,
           "dissolved_oxygen": 7.0}
    try:
        three = predict_three_class(row)
        print(f"predict_three_class -> {three if three is None else three['label']}")
    except Exception as exc:
        print(f"predict_three_class RAISED {type(exc).__name__}: {exc}")

    from app.ml.predictor import predict

    try:
        full = predict(row)
        print(f"predict (with fallback) -> {full['label']} conf={full['confidence']} "
              f"model={full.get('model_name')} version={full.get('model_version')}")
    except Exception as exc:
        print(f"predict RAISED {type(exc).__name__}: {exc}")

shutil.rmtree(sandbox_root, ignore_errors=True)