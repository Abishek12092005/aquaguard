"""Measure the real end-to-end prediction API response time.

Hits the LIVE backend (run.py on :5000) the same way the frontend does:
POST /api/v1/predictions/predict. The first request includes model loading
(cold); subsequent requests are warm. Nothing is stubbed, no fake cache.
"""
import json
import statistics
import time
import urllib.request

URL = "http://127.0.0.1:5000/api/v1/predictions/predict"
SAMPLE = {
    "ph": 7.1,
    "turbidity": 1.2,
    "tds": 280.0,
    "temperature": 18.0,
    "dissolved_oxygen": 8.4,
}

body = json.dumps(SAMPLE).encode()


def one(n: int) -> float:
    request = urllib.request.Request(
        URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    start = time.perf_counter()
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read())
    elapsed = time.perf_counter() - start
    verdict = payload.get("data", {}).get("prediction")
    print(f"request {n}: {elapsed*1000:7.1f} ms  verdict={verdict}  id={payload.get('data', {}).get('id')}")
    return elapsed


times = []
for n in range(1, 9):
    times.append(one(n))

print("\n--- summary (ms) ---")
print(f"cold (first): {times[0]*1000:.1f}")
warm = times[1:]
print(f"warm min:     {min(warm)*1000:.1f}")
print(f"warm average: {statistics.mean(warm)*1000:.1f}")
print(f"warm max:     {max(warm)*1000:.1f}")
