"""STEP 36 - why the model-less request HANGS instead of returning 503.

The sandbox run stopped fabricating a verdict but then timed out at 45 s rather
than failing fast. This drives the same code path in-process with a stack dump on
timeout, so the blocking call is identified rather than guessed at.
"""

import faulthandler
import os
import shutil
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
REAL_ML = os.path.join(os.path.dirname(HERE), "ml")

sandbox_root = tempfile.mkdtemp(prefix="aquaguard_hang_")
sandbox_ml = os.path.join(sandbox_root, "ml")
shutil.copytree(
    REAL_ML, sandbox_ml,
    ignore=shutil.ignore_patterns("__pycache__", "*.joblib", "subsets", "datasets"),
)
for name in ("imputer.joblib", "scaler.joblib"):
    src = os.path.join(REAL_ML, "preprocessing", name)
    if os.path.isfile(src):
        shutil.copy2(src, os.path.join(sandbox_ml, "preprocessing", name))
encoder = os.path.join(REAL_ML, "model", "label_encoder.joblib")
if os.path.isfile(encoder):
    shutil.copy2(encoder, os.path.join(sandbox_ml, "model", "label_encoder.joblib"))

os.environ["ML_WATER_QUALITY_DIR"] = sandbox_ml
os.environ["ML_MODEL_DIR"] = os.path.join(sandbox_root, "no_legacy")
os.makedirs(os.environ["ML_MODEL_DIR"], exist_ok=True)

from app import create_app  # noqa: E402
from app.ml import water_quality  # noqa: E402

app = create_app("testing")

# Give the warm-up thread time to finish (or fail) before the request.
threading.Event().wait(5)

print("\n=== state after boot, inside an app context ===")
with app.app_context():
    print("config dir :", app.config["ML_WATER_QUALITY_DIR"])
    print("_ml_root() :", water_quality._ml_root())
    print("available  :", water_quality.is_available())

print("\n=== is_available() OUTSIDE an app context (the request path is inside, but check) ===")
print(water_quality.is_available())

print("\n=== drive the predict endpoint through the test client (20 s cap) ===")
faulthandler.dump_traceback_later(20, exit=True)

client = app.test_client()
response = client.post("/api/v1/predictions", json={
    "ph": 7.2, "turbidity": 1.5, "tds": 300.0,
    "temperature": 25.0, "dissolved_oxygen": 7.0,
})
print("status:", response.status_code)
print("body  :", response.get_data(as_text=True)[:400])

shutil.rmtree(sandbox_root, ignore_errors=True)