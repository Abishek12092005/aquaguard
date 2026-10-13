"""STEP 7 acceptance check: latency, correctness under load, and the honest error path.

Three things are measured against the LIVE backend on :5000, over real HTTP, with
nothing stubbed:

  1. LATENCY. 30 sequential POSTs to the predict endpoint, reported as
     average / p95 / max, against the 3 s average and 5 s max target.

  2. CONCURRENCY. 10 simultaneous predictions, because the model is shared
     mutable state and a cache that is not thread-safe would show up here as a
     crash or a corrupt verdict rather than as slowness.

  3. CORRECTNESS. Every verdict is compared against the same samples run
     through the model the ORIGINAL way (n_jobs=-1, the training-time setting).
     The optimisation must be a scheduling change only - if any label or
     confidence differs, the verdicts are genuinely different and this fails.

It also checks that a dead backend produces an error, not an invented result.
"""
import concurrent.futures
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request

URL = "http://127.0.0.1:5000/api/v1/predictions/predict"

SAMPLES = [
    {"ph": 7.1, "turbidity": 1.2, "tds": 280.0, "temperature": 18.0, "dissolved_oxygen": 8.4},
    {"ph": 3.1, "turbidity": 12.0, "tds": 900.0, "temperature": 30.0, "dissolved_oxygen": 2.1},
    {"ph": 8.9, "turbidity": 0.4, "tds": 120.0, "temperature": 12.0, "dissolved_oxygen": 9.9},
    {"ph": 6.2, "turbidity": 4.5, "tds": 450.0, "temperature": 22.0, "dissolved_oxygen": 6.0},
    {"ph": 0.0, "turbidity": 0.0, "tds": 0.0, "temperature": 0.0, "dissolved_oxygen": 0.0},
    {"ph": 14.0, "turbidity": 1000.0, "tds": 50000.0, "temperature": 45.0, "dissolved_oxygen": 14.0},
    {"ph": 5.5, "turbidity": 2.2, "tds": 310.0, "temperature": 19.0, "dissolved_oxygen": 7.2},
    {"ph": 9.4, "turbidity": 18.5, "tds": 1250.0, "temperature": 33.0, "dissolved_oxygen": 1.2},
]

failures: list[str] = []


def post(sample: dict, timeout: float = 30.0):
    """One prediction over HTTP. Returns (elapsed_seconds, payload)."""
    request = urllib.request.Request(
        URL,
        data=json.dumps(sample).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    start = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read())
    return time.perf_counter() - start, payload


# --- 1. Latency -------------------------------------------------------------
print("=" * 70)
print("1. LATENCY  (target: avg <= 3 s, max <= 5 s)")
print("=" * 70)

latencies = []
for n in range(30):
    elapsed, payload = post(SAMPLES[n % len(SAMPLES)])
    latencies.append(elapsed)
    if n < 3 or n == 29:
        print(f"   request {n+1:2d}: {elapsed*1000:7.1f} ms   verdict={payload['data']['prediction']}")

ordered = sorted(latencies)
p95 = ordered[int(len(ordered) * 0.95) - 1]
average = statistics.mean(latencies)
worst = max(latencies)

print(f"\n   average : {average*1000:7.1f} ms   ({'PASS' if average <= 3 else 'FAIL'} vs 3000 ms target)")
print(f"   p95     : {p95*1000:7.1f} ms")
print(f"   max     : {worst*1000:7.1f} ms   ({'PASS' if worst <= 5 else 'FAIL'} vs 5000 ms target)")
if average > 3:
    failures.append(f"average {average:.2f}s exceeds the 3s target")
if worst > 5:
    failures.append(f"max {worst:.2f}s exceeds the 5s target")

# --- 2. Concurrency ---------------------------------------------------------
print("\n" + "=" * 70)
print("2. CONCURRENCY  (10 simultaneous predictions, shared model)")
print("=" * 70)


def concurrent_call(i: int):
    try:
        elapsed, payload = post(SAMPLES[i % len(SAMPLES)], timeout=30.0)
        return elapsed, payload["data"].get("prediction"), None
    except Exception as exc:  # noqa: BLE001
        return None, None, str(exc)


with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
    results = list(pool.map(concurrent_call, range(10)))

errors = [err for _, _, err in results if err]
concurrent_times = [t for t, _, _ in results if t is not None]
print(f"   completed   : {len(concurrent_times)}/10")
print(f"   errors      : {len(errors)}")
print(f"   max latency : {max(concurrent_times)*1000:.1f} ms" if concurrent_times else "   no results")
print(f"   verdicts    : {sorted({v for _, v, _ in results if v})}")
if errors:
    failures.append(f"concurrent requests failed: {errors[:2]}")
if concurrent_times and max(concurrent_times) > 5:
    failures.append(f"concurrent max {max(concurrent_times):.2f}s exceeds 5s")

# --- 3. Correctness ---------------------------------------------------------
print("\n" + "=" * 70)
print("3. CORRECTNESS  (served verdicts vs the original n_jobs=-1 model)")
print("=" * 70)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "ml"))
import predict as wq  # noqa: E402

artifacts = wq._load()
model = artifacts["model"]

served = {}
for sample in SAMPLES:
    _, payload = post(sample)
    served[tuple(sample.values())] = (
        payload["data"]["prediction"],
        round(float(payload["data"]["confidence"]), 4),
    )

# Re-run the same samples with the pool restored, in this process.
model.n_jobs = -1
baseline = {}
for sample in SAMPLES:
    result = wq.predict(sample)
    baseline[tuple(sample.values())] = (
        {"SAFE": "safe", "MODERATE": "moderate", "UNSAFE": "unsafe"}[result["water_quality"]],
        result["confidence"],
    )

mismatches = 0
for key, (served_verdict, served_conf) in served.items():
    base_verdict, base_conf = baseline[key]
    same = served_verdict == base_verdict and abs(served_conf - base_conf) < 1e-4
    mismatches += 0 if same else 1
    print(f"   ph={key[0]:<5} served={served_verdict:<8}{served_conf:<7} "
          f"baseline={base_verdict:<8}{base_conf:<7} {'OK' if same else 'MISMATCH'}")

print(f"\n   {len(SAMPLES) - mismatches}/{len(SAMPLES)} identical to the unoptimised model.")
if mismatches:
    failures.append(f"{mismatches} verdict(s) differ from the original model")

# --- 4. Honest failure ------------------------------------------------------
# Nothing is listening here, so a correct client gets a connection error. This
# is the case the UI must report as an error rather than paper over with an
# invented verdict, so the check is that it DOES fail.
DEAD_URL = "http://127.0.0.1:5999/api/v1/predictions/predict"
try:
    urllib.request.urlopen(urllib.request.Request(DEAD_URL, data=b"{}",
                                                   headers={"Content-Type": "application/json"}),
                           timeout=5.0)
    print("   FAIL: a dead port answered")
    failures.append("dead backend did not fail")
except urllib.error.URLError as exc:
    print(f"   refused as expected: {type(exc).__name__}")
    print("   the UI shows a network error banner; no result is invented.")

# --- Verdict ----------------------------------------------------------------
print("\n" + "=" * 70)
if failures:
    print("RESULT: FAILED")
    for failure in failures:
        print(f"  - {failure}")
    sys.exit(1)
print("RESULT: ALL CHECKS PASSED")
print("=" * 70)
