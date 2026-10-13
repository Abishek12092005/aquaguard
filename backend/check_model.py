"""Check model determinism: same input 3x, and two different inputs."""
import json
import os

os.environ.setdefault("DATABASE_URL", "sqlite://")

from app.ml.predictor import predict  # noqa: E402

samples = [
    {"ph": 7.1, "turbidity": 4.2, "tds": 350, "temperature": 27.5, "dissolved_oxygen": 6.8},
    {"ph": 6.5, "turbidity": 1.5, "tds": 300, "temperature": 25.0, "dissolved_oxygen": 7.0},
    {"ph": 5.8, "turbidity": 8.0, "tds": 900, "temperature": 30.0, "dissolved_oxygen": 3.5},
]

print("same input x3 (determinism):")
for _ in range(3):
    r = predict(samples[0])
    print(json.dumps({"risk": r["risk_level"], "conf": r["confidence"], "probs": r["probabilities"]}))

print("different inputs:")
for s in samples:
    r = predict(s)
    print(json.dumps({"risk": r["risk_level"], "conf": r["confidence"], "probs": r["probabilities"]}))
