"""Profile the cold prediction path to find what dominates the first request."""
import cProfile
import io
import json
import os
import pstats
import sys
import time

os.environ.setdefault("FLASK_APP", "app")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app  # noqa: E402

app = create_app()

SAMPLE = {
    "ph": 7.1,
    "turbidity": 1.2,
    "tds": 280.0,
    "temperature": 18.0,
    "dissolved_oxygen": 8.4,
}

# --- Time each stage separately -------------------------------------------
print("=== stage timings (cold) ===")

start = time.perf_counter()
with app.app_context():
    from app.ml import water_quality

    available = water_quality.is_available()
print(f"1. module import + is_available: {(time.perf_counter()-start)*1000:.1f} ms (available={available})")

start = time.perf_counter()
with app.app_context():
    from app.ml.water_quality import _load_pipeline

    pipeline = _load_pipeline()
print(f"2. pipeline import:              {(time.perf_counter()-start)*1000:.1f} ms")

start = time.perf_counter()
with app.app_context():
    _ = pipeline._load()
print(f"3. artifact load (joblib):       {(time.perf_counter()-start)*1000:.1f} ms")

start = time.perf_counter()
with app.app_context():
    from app.ml.preprocessing import preprocess_input

    frame = preprocess_input(SAMPLE)
print(f"4. preprocessing:                {(time.perf_counter()-start)*1000:.1f} ms")

start = time.perf_counter()
with app.app_context():
    row = {name: float(frame.iloc[0][name]) for name in ("ph", "turbidity", "tds", "temperature", "dissolved_oxygen")}
    result = water_quality.predict(row)
print(f"5. model inference:              {(time.perf_counter()-start)*1000:.1f} ms (label={result.get('label')})")

# --- Whole cold request through the test client ---------------------------
print("\n=== whole cold POST through the test client ===")
client = app.test_client()
# reset caches so the client request is genuinely cold again
from app.ml import water_quality as _wq

ml_predict = _wq._load_pipeline()
ml_predict._cache.clear()

start = time.perf_counter()
profiler = cProfile.Profile()
profiler.enable()
response = client.post(
    "/api/v1/predictions/predict",
    data=json.dumps(SAMPLE),
    content_type="application/json",
)
profiler.disable()
print(f"cold POST status={response.status_code}: {(time.perf_counter()-start)*1000:.1f} ms")

stream = io.StringIO()
stats = pstats.Stats(profiler, stream=stream)
stats.sort_stats("cumulative")
stats.print_stats(18)
text = stream.getvalue()
# print only the interesting part
lines = text.splitlines()
for line in lines[:8]:
    print(line)
print(" ...")
for line in lines:
    if "joblib" in line or "sklearn" in line or "numpy" in line or "predict.py" in line or "scaler" in line or "preprocessing" in line or "water_quality" in line or "train" in line:
        print(line)
# --- Cleanup stub: the QA runner appends here ---
