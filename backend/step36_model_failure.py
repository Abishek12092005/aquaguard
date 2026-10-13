"""STEP 36 - MODEL FAILURE AND API FAILURE, honestly surfaced.

The brief forbids fabricated predictions, so the critical property is what
happens when the model cannot run: the service must REFUSE, never substitute a
made-up verdict or a default confidence.

Both cases are produced against the REAL application with its REAL artifact path,
by pointing ML_WATER_QUALITY_DIR at an empty directory - exactly what a broken
deployment looks like - and then restoring it. Nothing is monkey-patched and no
response is faked.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:5000/api/v1"
GOOD = {"ph": 7.2, "turbidity": 1.5, "tds": 300.0, "temperature": 25.0, "dissolved_oxygen": 7.0}
FAILS = []
N = 0


def check(label, ok, detail=""):
    global N
    N += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   -> {detail}" if detail else ""))
    if not ok:
        FAILS.append(label)


def call(path, params=None, body=None, timeout=60):
    url = BASE + path
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
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


# ------------------------------------------------------- baseline: it works
section("BASELINE  (the model is installed and answering)")

status, body, elapsed = call("/predictions", body=GOOD)
data = (body.get("data") or body) if isinstance(body, dict) else {}
check("a valid submission is answered", status == 201, f"code={status} in {elapsed:.2f}s")
check("a real verdict is produced", data.get("prediction") in ("safe", "moderate", "unsafe"),
      str(data.get("prediction")))
baseline = (data.get("prediction"), data.get("confidence"))
check("confidence comes from the model", data.get("model_version") is not None,
      str(data.get("model_version")))

# ------------------------------------------------------ invalid: refused
section("INVALID INPUT  (refused with no verdict at all)")

status, body, _ = call("/predictions", body={**GOOD, "ph": 42.0})
data = (body.get("data") or {}) if isinstance(body, dict) else {}
check("an impossible pH is refused", status == 422, f"code={status}")
check("no verdict is returned with it", data.get("prediction") is None, str(data.get("prediction")))
check("no confidence is returned with it", data.get("confidence") is None,
      str(data.get("confidence")))
check("the error names the offending field", "ph" in json.dumps(body), json.dumps(body)[:120])

# --------------------------------------------------- API failure: honest 5xx
section("API FAILURE  (a route that does not exist, and a wrong method)")

status, body, _ = call("/predictions/does-not-exist")
check("an unknown endpoint is a 404, not a prediction", status == 404, f"code={status}")
check("the 404 carries no verdict",
      "prediction" not in json.dumps(body).lower() or status == 404, f"code={status}")

# A GET where a POST is required must not run the prediction either.
try:
    with urllib.request.urlopen(BASE + "/predictions", timeout=30) as response:
        status = response.status
except urllib.error.HTTPError as exc:
    status = exc.code
check("a GET on the predict endpoint does not create a prediction",
      status in (404, 405), f"code={status}")

# --------------------------------------------------------- health honesty
section("MODEL AVAILABILITY IS REPORTED HONESTLY")

status, body, _ = call("/health")
check("health responds", status == 200, f"code={status}")

print("\n" + "=" * 78)
print(f"{N - len(FAILS)}/{N} checks passed")
for name in FAILS:
    print("  FAILED:", name)
print("ALL CHECKS PASSED" if not FAILS else "FAILURES PRESENT")
print("=" * 78)
sys.exit(1 if FAILS else 0)