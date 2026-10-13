"""STEP 36 - MODEL FAILURE: no artifact must mean NO prediction, not a fake one.

The brief's hardest constraint is "never fabricate prediction results". The only
honest test of that is to remove the model and confirm the API refuses.

This starts a SECOND backend process against the real application, with
ML_WATER_QUALITY_DIR pointed at an empty directory, so its `is_available()`
answer is genuinely False. The running development server is left untouched.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
GOOD = {"ph": 7.2, "turbidity": 1.5, "tds": 300.0, "temperature": 25.0, "dissolved_oxygen": 7.0}
FAILS = []
N = 0


def check(label, ok, detail=""):
    global N
    N += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   -> {detail}" if detail else ""))
    if not ok:
        FAILS.append(label)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def call(base, path, body=None, timeout=45):
    url = base + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"},
        method="POST" if data else "GET",
    )
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw, status = response.read().decode("utf-8", "replace"), response.status
    except urllib.error.HTTPError as exc:
        raw, status = exc.read().decode("utf-8", "replace"), exc.code
    except Exception as exc:  # noqa: BLE001
        return 0, {"transport_error": str(exc)}, time.time() - started
    try:
        return status, json.loads(raw), time.time() - started
    except json.JSONDecodeError:
        return status, raw, time.time() - started


def section(title):
    print("\n" + "-" * 78)
    print(title)
    print("-" * 78)


# WHY A COPY, NOT AN ENV VAR. `ML_WATER_QUALITY_DIR` only decides where the ml/
# PACKAGE is imported from - `ml/predict.py` then resolves its own model/ and
# preprocessing/ directories relative to its own __file__. Pointing that setting
# at an empty directory therefore does NOT remove the model: the real ml/ tree is
# still on the path and still answers. An earlier run of this test "passed" the
# removal by mistake - it was measuring the real, present model.
#
# So the model is removed the only way that is actually true: a full COPY of the
# real ml/ tree with the forest artifact deleted. `predict.py` resolves its model
# dir from its own location, so this copy genuinely cannot find a forest, and the
# pipeline raises for real. Nothing is monkey-patched and no response is faked.
# The real ml/ tree is never touched.
SOURCE_ML = os.path.join(os.path.dirname(HERE), "ml")
artifact = "water_quality_rf.joblib"
missing_root = tempfile.mkdtemp(prefix="aquaguard_no_model_")
sandbox_ml = os.path.join(missing_root, "ml")
shutil.copytree(
    SOURCE_ML, sandbox_ml,
    ignore=shutil.ignore_patterns("__pycache__", "*.joblib", "subsets", "datasets"),
)
# Keep the small preprocessing artifacts, drop only the forest itself.
for name in ("imputer.joblib", "scaler.joblib"):
    src = os.path.join(SOURCE_ML, "preprocessing", name)
    if os.path.isfile(src):
        shutil.copy2(src, os.path.join(sandbox_ml, "preprocessing", name))
# label_encoder lives beside the forest; inference needs it, so keep it too.
src_encoder = os.path.join(SOURCE_ML, "model", "label_encoder.joblib")
if os.path.isfile(src_encoder):
    shutil.copy2(src_encoder, os.path.join(sandbox_ml, "model", "label_encoder.joblib"))

empty_model_dir = sandbox_ml
sandbox_model_file = os.path.join(sandbox_ml, "model", artifact)

# THE SECOND MODEL, WHICH AN EARLIER VERSION OF THIS TEST FORGOT.
#
# `app.ml.predictor.predict` tries the 3-class forest first and FALLS BACK to the
# legacy binary `ml/models/aquaguard_random_forest.pkl`. Removing only the first
# therefore does not disable prediction - the request was answered 201 by the
# binary forest, with confidence 0.9892 and a different importance profile
# (ph 0.3185 vs the 3-class model's 0.3254), which is how that was identified.
#
# That answer was real model output, not a fabrication, but it does not test what
# this test is for. ML_MODEL_DIR is pointed at an empty directory as well, so BOTH
# artifacts are genuinely absent and no forest of any kind can answer.
legacy_model_dir = os.path.join(missing_root, "no_legacy_model")
os.makedirs(legacy_model_dir, exist_ok=True)
legacy_artifact = os.path.join(legacy_model_dir, "aquaguard_random_forest.pkl")

print(f"built a sandbox ml/ tree at: {sandbox_ml}")
print(f"  3-class forest present? {os.path.isfile(sandbox_model_file)} "
      f"(real one exists: {os.path.isfile(os.path.join(SOURCE_ML, 'model', artifact))})")
print(f"  legacy forest present? {os.path.isfile(legacy_artifact)}")

port = free_port()
base = f"http://127.0.0.1:{port}/api/v1"

env = dict(os.environ)
env["ML_WATER_QUALITY_DIR"] = empty_model_dir
# Remove the legacy binary forest too, so the predictor's fallback cannot answer.
env["ML_MODEL_DIR"] = legacy_model_dir
env["ML_MODEL_FILENAME"] = "aquaguard_random_forest.pkl"
env["FLASK_PORT"] = str(port)
env["FLASK_HOST"] = "127.0.0.1"

server = subprocess.Popen(
    [sys.executable, "run.py"], cwd=HERE, env=env,
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
)

try:
    print("\nwaiting for the model-less server to boot...")
    booted = False
    for _ in range(60):
        if server.poll() is not None:
            print("server exited early:\n" + (server.stdout.read() if server.stdout else ""))
            sys.exit(1)
        status, body, _ = call(base, "/health", timeout=5)
        if status == 200:
            booted = True
            break
        time.sleep(1)
    check("the model-less server boots and answers /health", booted, f"port={port}")

    if booted:
        section("WITH NO MODEL INSTALLED")

        check("the sandbox really has no 3-class forest artifact",
              not os.path.isfile(sandbox_model_file), sandbox_model_file)
        check("the sandbox really has no legacy binary forest either",
              not os.path.isfile(legacy_artifact), legacy_artifact)

        status, body, elapsed = call(base, "/predictions", body=GOOD)
        print(f"  response: code={status} body={json.dumps(body)[:300]}")

        # The essential property: no prediction of any kind comes back.
        payload = body.get("data") if isinstance(body, dict) else None
        check("a prediction request FAILS rather than answering", status >= 400,
              f"code={status}")
        check("no verdict is invented", not (isinstance(payload, dict)
              and payload.get("prediction")), f"prediction={None if not isinstance(payload, dict) else payload.get('prediction')}")
        check("no confidence is invented", not (isinstance(payload, dict)
              and payload.get("confidence")), f"confidence={None if not isinstance(payload, dict) else payload.get('confidence')}")
        check("the failure is reported as a model error (503), not a server crash",
              status == 503, f"code={status}")
        check("the message says the model is unavailable, not a verdict",
              "model" in json.dumps(body).lower(), json.dumps(body)[:160])
        check("it failed FAST rather than hanging", elapsed < 20, f"{elapsed:.2f}s")

        # Aqua AI's prediction tool must fail the same way.
        section("THE ASSISTANT'S PREDICTION TOOL FAILS THE SAME WAY")
        status, body, _ = call(base, "/ai/chat", body={"message": "predict water quality",
                                                       "session_id": "step36-nomodel"}, timeout=60)
        text = json.dumps(body).lower()
        check("Aqua AI does not state a verdict without a model",
              not ("safe to drink" in text or "unsafe" in text and "confidence" in text),
              f"code={status}")
finally:
    server.terminate()
    try:
        server.wait(timeout=15)
    except subprocess.TimeoutExpired:
        server.kill()
    shutil.rmtree(empty_model_dir, ignore_errors=True)

print("\n" + "=" * 78)
print(f"{N - len(FAILS)}/{N} checks passed")
for name in FAILS:
    print("  FAILED:", name)
print("ALL CHECKS PASSED" if not FAILS else "FAILURES PRESENT")
print("=" * 78)
sys.exit(1 if FAILS else 0)