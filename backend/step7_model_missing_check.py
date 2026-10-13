"""The real proof is the one that matters in production: the artifact file is
genuinely not there. This RENAMES `ml/model/water_quality_rf.joblib` and
`ml/models/aquaguard_random_forest.pkl` for the duration of the check and puts
them back afterwards, in a `finally`, so an interrupted run cannot leave the
project without a model.

A note on why it renames the FILES rather than repointing `ML_MODEL_DIR`:
`ml/predict.py` resolves `MODEL_DIR` from its own location at import time, so
`ML_WATER_QUALITY_DIR` decides only where the backend looks for the PACKAGE.
Moving the artifact on disk is the only way to actually make it unavailable.

Three things are asserted:

  1. the predict endpoint answers 503, not 200
  2. the response body contains no verdict, confidence or prediction field
  3. the error names the real cause, so the UI can say something true

The second is the one that matters. A 200 carrying an invented "safe" would look
like a working model to every layer above it.
"""
import json
import os
import sys

os.environ.setdefault("FLASK_APP", "app")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

ROOT = os.path.abspath(os.path.join(HERE, ".."))
# The two artifacts the prediction path can use: the 3-class pipeline and the
# legacy binary forest the predictor falls back to.
ARTIFACTS = [
    os.path.join(ROOT, "ml", "model", "water_quality_rf.joblib"),
    os.path.join(ROOT, "ml", "models", "aquaguard_random_forest.pkl"),
]

moved: list[tuple[str, str]] = []
for path in ARTIFACTS:
    if os.path.isfile(path):
        hidden = path + ".step7-hidden"
        os.rename(path, hidden)
        moved.append((path, hidden))

try:
    from app import create_app  # noqa: E402

    app = create_app()
    SAMPLE = {
        "ph": 7.1, "turbidity": 1.2, "tds": 280.0,
        "temperature": 18.0, "dissolved_oxygen": 8.4,
    }

    client = app.test_client()
    failures = []

    print("=" * 70)
    print("MODEL UNAVAILABLE  (both artifacts temporarily moved aside)")
    print("=" * 70)

    response = client.post(
        "/api/v1/predictions/predict",
        data=json.dumps(SAMPLE),
        content_type="application/json",
    )
    body = response.get_json() or {}

    ok = response.status_code == 503
    print(f"   status : {response.status_code}  ({'PASS' if ok else 'FAIL'}, expected 503)")
    if not ok:
        failures.append(f"expected 503, got {response.status_code}")

    text = json.dumps(body).lower()
    invented = [
        field for field in ("\"prediction\"", "\"confidence\"", "\"safe\"", "\"unsafe\"", "\"moderate\"")
        if field in text
    ]
    print(f"   invented verdict fields: {invented if invented else 'none'}  "
          f"({'PASS' if not invented else 'FAIL'})")
    if invented:
        failures.append(f"error response still carries result fields: {invented}")

    message = body.get("message", "")
    print(f"   message: {message}")
    if not message:
        failures.append("no message explaining the failure")

    print(f"\n   {'FAILED: ' + '; '.join(failures) if failures else 'PASSED: fails honestly, invents nothing'}")
    sys.exit(1 if failures else 0)
finally:
    # Always put the model back, even if the check above raised.
    for path, hidden in moved:
        os.rename(hidden, path)
    print(f"\n   restored {len(moved)} artifact(s)")
