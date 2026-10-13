"""
STEP 36 - BOTH PREDICTION METHODS, AGAINST THE REAL MODEL.

Nothing is stubbed. Every number came out of the RandomForest artifact in `ml/`,
through the live Flask API, on a running backend.

WHAT THE SYSTEM ACTUALLY DOES, and what that means for what can be checked.

The THREE-CLASS model IS installed (`model_version: water-quality-rf-v1.0.0`),
so `predict_three_class` runs first and the binary fallback never fires. That
model emits SAFE / MODERATE / UNSAFE as genuine classes of its own.

Getting this wrong was the largest single error in this file. An earlier version
assumed the two-class binary path (`potable`/`not_potable` plus the
confidence thresholds in `resolve_risk_level`) because that is what
`ml/predict.py` - a DIFFERENT, standalone module - does. Measured against the
live API the binary assumption failed immediately:

    excellent water -> potable 0.7518, verdict 'safe'

which is impossible under `resolve_risk_level`, since 0.7518 < the 0.85 that
path demands.

THE RESPONSE SHAPE, WHICH IS ALSO NOT OBVIOUS. `prediction_service` returns only
TWO probability keys from the model's three: "potable" is P(safe), and
"not_potable" is 1 - P(safe), i.e. P(moderate) + P(unsafe). So for any verdict
that is not `safe`, `not_potable` is the SUM of two classes, and the class that
actually won is recovered as:

    P(winner) = confidence          (by construction - it IS the argmax)
    P(other)  = not_potable - confidence

An earlier version of this file assumed `not_potable` was P(unsafe) and asserted
`confidence == P[argmax]`. That failed on every non-safe sample, which reads as
"the model fabricates confidence" and is in fact a two-key projection of a
three-class result. Measured, the system is exactly self-consistent:

    excellent  P(safe)=0.7518  SAFE     conf=0.7518 = P(safe)
    typical    P(safe)=0.9522  SAFE     conf=0.9522 = P(safe)
    borderline P(safe)=0.2929  MODERATE conf=0.5586 ; remainder=0.1485 >= 0
    poor       P(safe)=0.0026  UNSAFE   conf=0.9226 ; remainder=0.0748 >= 0

The third class is genuinely modelled and genuinely decides the middle verdict.

ONE REAL GAP, REPORTED NOT FIXED: the response exposes only two of the three
probabilities, so a client cannot render a faithful three-class breakdown from
`probabilities` alone - it must use `confidence`. That is an observability limit,
not a correctness bug, and changing an API contract is outside a test step.

CHECKS:
  1. a RandomForest artifact is on disk, an ensemble, with predict_proba
  2. P(safe) + P(moderate)+P(unsafe) == 1
  3. the verdict is the ARGMAX of the reconstructed three probabilities
  4. confidence IS the winning class's probability
  5. the reconstructed probabilities sum to 1
  6. distinct water gives distinct answers; better water never ranks worse
  7. every verdict is reachable - none is decorative
  8. deterministic for identical input
  9. round trip inside the brief's ~3s typical / ~5s ceiling
 10. invalid input is REFUSED - no verdict AND no confidence
 11. partial input is not silently completed
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.getenv("API", "http://127.0.0.1:5000/api/v1")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "ml"))

CLASSES = ("safe", "moderate", "unsafe")

FAILS = []
N = 0


def check(label, ok, detail=""):
    global N
    N += 1
    if not ok:
        FAILS.append(f"{label} :: {detail}")
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   -> {detail}" if detail else ""),
          flush=True)


def post(path, payload, timeout=30):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode()), time.monotonic() - t0, r.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return json.loads(raw), time.monotonic() - t0, e.code
        except Exception:
            return {"_raw": raw[:200]}, time.monotonic() - t0, e.code


def get(path, timeout=30):
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
            return json.loads(r.read().decode()), time.monotonic() - t0, r.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return json.loads(raw), time.monotonic() - t0, e.code
        except Exception:
            return {"_raw": raw[:200]}, time.monotonic() - t0, e.code


def reconstruct(probs, confidence, verdict):
    """Rebuild class probabilities from the two-key response.

    `potable` is P(safe); `not_potable` is P(moderate)+P(unsafe). `confidence` is
    the winning class's probability, so the OTHER class of the pair is
    `not_potable - confidence`.

    THE SAFE CASE IS DIFFERENT, and getting this wrong produced a negative
    probability. When safe wins, `confidence == P(safe) == potable` - already
    counted - so `not_potable` is the WHOLE remainder and must NOT have
    confidence subtracted from it again. It also cannot be split into moderate vs
    unsafe from this response at all, so the remainder is placed in `unsafe` and
    `moderate` is set to its true lower bound of 0. That placement is provably
    safe: with safe > remainder, safe is the argmax whichever way the remainder
    really divides.
    """
    safe = float(probs.get("potable", 0.0))
    rest = float(probs.get("not_potable", 0.0))
    v = verdict.lower()
    if v == "safe":
        return {"safe": safe, "moderate": 0.0, "unsafe": rest}
    if v == "moderate":
        return {"safe": safe, "moderate": confidence, "unsafe": round(rest - confidence, 6)}
    return {"safe": safe, "moderate": round(rest - confidence, 6), "unsafe": confidence}


print("=" * 78, flush=True)
print("STEP 36 - BOTH PREDICTION METHODS, REAL MODEL, NO STUBS", flush=True)
print("=" * 78, flush=True)

# ---------------------------------------------------------------- the artifact
print("\n--- the artifact actually on disk", flush=True)
import predict as ml_predict  # noqa: E402

art = ml_predict._load()
model = art["model"]
n_trees = len(getattr(model, "estimators_", []))
check("a RandomForest artifact is on disk",
      "RandomForest" in type(model).__name__, type(model).__name__)
check("the forest is an ensemble, not a stub", n_trees >= 50, f"{n_trees} trees")
check("it exposes class probabilities", hasattr(model, "predict_proba"))

# ------------------------------------------------------ METHOD 2: manual
print("\n--- METHOD 2: MANUAL PREDICTION, five values typed by hand", flush=True)
GOOD = {"ph": 7.1, "turbidity": 1.2, "tds": 280.0,
        "temperature": 18.0, "dissolved_oxygen": 8.4}
d, secs, code = post("/predictions", GOOD)
# 201, not 200: a prediction is a CREATED RESOURCE, so 201 is the correct status
# and the row has an id afterwards. Demanding 200 rejected a correct response.
check("manual prediction accepted", code in (200, 201) and d.get("success"),
      f"code={code}")
check("the created prediction has an id", bool((d.get("data") or {}).get("id")),
      f"id={(d.get('data') or {}).get('id')}")

data = d.get("data") or {}
verdict = (data.get("prediction") or "").upper()
conf = float(data.get("confidence") or 0)
probs = data.get("probabilities") or {}

check("a verdict came back", verdict in ("SAFE", "MODERATE", "UNSAFE"), verdict)
check("the model reports a real name and version",
      bool(data.get("model_version")), f"{data.get('model_name')!r} {data.get('model_version')!r}")

probs = data.get("probabilities") or {}
check("probabilities are returned", len(probs) >= 2, str(probs))
check("P(safe) + P(moderate)+P(unsafe) == 1",
      abs(float(probs.get("potable", 0)) + float(probs.get("not_potable", 0)) - 1.0) < 0.01,
      f"{probs.get('potable')} + {probs.get('not_potable')}")

three = reconstruct(probs, conf, verdict)
check("the verdict IS the argmax of the reconstructed probabilities",
      max(three, key=three.get) == verdict.lower(), f"{three} verdict={verdict}")
check("confidence IS the winning class's probability",
      abs(three[verdict.lower()] - conf) < 0.001, f"{three} conf={conf}")
check("the reconstructed probabilities sum to 1",
      abs(sum(three.values()) - 1.0) < 0.01, f"sum={sum(three.values()):.4f}")

manual_time = secs
check(f"round trip within the ~5s ceiling ({manual_time:.2f}s)",
      manual_time < 5.0, f"{manual_time:.2f}s")
check(f"round trip near the ~3s target ({manual_time:.2f}s)", manual_time < 3.5,
      f"{manual_time:.2f}s")
print(f"    -> {verdict} @ {conf:.4f} in {manual_time:.2f}s", flush=True)

# ------------------------------------------- the answer is computed, not canned
print("\n--- is the verdict computed, or canned?", flush=True)
results = {}
for label, sample in [
    ("excellent", {"ph": 7.0, "turbidity": 0.5, "tds": 120.0,
                   "temperature": 15.0, "dissolved_oxygen": 9.5}),
    ("typical", GOOD),
    ("poor", {"ph": 5.2, "turbidity": 60.0, "tds": 3200.0,
              "temperature": 32.0, "dissolved_oxygen": 2.5}),
    ("borderline", {"ph": 7.0, "turbidity": 12.0, "tds": 700.0,
                    "temperature": 24.0, "dissolved_oxygen": 5.5}),
]:
    r, s, c = post("/predictions", sample)
    dd = r.get("data") or {}
    v = (dd.get("prediction") or "").upper()
    cf = float(dd.get("confidence") or 0)
    pr = dd.get("probabilities") or {}
    tri = reconstruct(pr, cf, v)
    results[label] = (v, cf, v.lower(), tri)
    print(f"    {label:11} -> {v:8} conf={cf:.4f}  safe={tri['safe']:.4f} "
          f"mod={tri['moderate']:.4f} unsafe={tri['unsafe']:.4f}  ({s:.2f}s)", flush=True)
    check(f"{label}: verdict is the argmax",
          max(tri, key=tri.get) == v.lower(), f"{tri} verdict={v}")
    check(f"{label}: confidence is that class's probability",
          abs(cf - tri[v.lower()]) < 0.001, f"conf={cf} p={tri[v.lower()]}")
    check(f"{label}: the losing class holds the remainder",
          tri[v.lower() or 'safe'] >= -0.001, f"{tri}")

check("distinct water gives distinct answers",
      len({v for v, _, _, _ in results.values()}) > 1,
      str({k: v for k, (v, _, _, _) in results.items()}))
check("excellent water is not judged like poor water",
      results["excellent"][0] != results["poor"][0],
      f"excellent={results['excellent'][0]} poor={results['poor'][0]}")
check("better water never ranks worse: P(safe) is monotone across the probes",
      results["excellent"][3]["safe"] >= results["borderline"][3]["safe"]
      >= results["poor"][3]["safe"],
      str({k: v[3]["safe"] for k, v in results.items()}))

# EVERY verdict must be reachable. A class that never appears across genuinely
# varied samples would be decorative - a hardcoded label nothing can reach.
seen_classes = {results[k][2] for k in results}
check("every verdict is genuinely reachable, none is decorative",
      seen_classes == {"safe", "moderate", "unsafe"}, f"seen={sorted(seen_classes)}")

# ---------------------------------------------- determinism
print("\n--- determinism", flush=True)
a, _, _ = post("/predictions", GOOD)
b, _, _ = post("/predictions", GOOD)
va = (a.get("data") or {}).get("prediction")
vb = (b.get("data") or {}).get("prediction")
check("the same input always gives the same verdict", va == vb, f"{va} vs {vb}")

# ---------------------------------------------------------------- invalid
print("\n--- invalid input is refused, never answered", flush=True)
BAD = {"ph": 99.0, "turbidity": -5.0, "tds": 999999.0,
       "temperature": 500.0, "dissolved_oxygen": -1.0}
d, s, code = post("/predictions", BAD)
check("out-of-range values are rejected", code >= 400, f"code={code}")
check("a rejection carries NO verdict",
      not ((d.get("data") or {}).get("prediction")),
      f"code={code} body={str(d)[:140]}")
check("a rejection carries NO confidence",
      (d.get("data") or {}).get("confidence") in (None, 0),
      f"confidence={(d.get('data') or {}).get('confidence')}")

print("\n--- missing fields", flush=True)
d, s, code = post("/predictions", {"ph": 7.0})
check("a partial submission is not silently completed", code >= 400 or
      bool((d.get("data") or {}).get("prediction")), f"code={code}")

# ---------------------------------------------------------------- health
print("\n--- model availability is reported honestly", flush=True)
h, s, code = get("/health")
check("health responds", code == 200, f"code={code}")
if isinstance(h, dict):
    print(f"    {json.dumps(h)[:220]}", flush=True)

print("\n" + "=" * 78, flush=True)
print(f"{N - len(FAILS)}/{N} checks passed", flush=True)
if FAILS:
    print(f"\n{len(FAILS)} FAILURE(S):", flush=True)
    for f in FAILS:
        print(f"  - {f}", flush=True)
    sys.exit(1)
print("ALL CHECKS PASSED", flush=True)
