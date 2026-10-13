"""Synthetic water-quality dataset generator."""

import argparse
import os

import numpy as np
import pandas as pd

# Canonical column order, mirroring backend/app/constants.py FEATURE_NAMES.
FEATURES = ("ph", "turbidity", "tds", "temperature", "dissolved_oxygen")


def generate(rows: int = 3000, seed: int = 42) -> pd.DataFrame:
    """Generate a synthetic water potability dataset."""
    rng = np.random.default_rng(seed)

    # --- Plausible marginal distributions --------------------------------
    ph = np.clip(rng.normal(7.0, 1.3, rows), 0.0, 14.0)
    turbidity = np.clip(rng.gamma(2.0, 1.6, rows), 0.0, 1000.0)
    tds = np.clip(rng.lognormal(mean=6.3, sigma=0.7, size=rows), 0.0, 50000.0)
    temperature = np.clip(rng.normal(20.0, 7.0, rows), -5.0, 100.0)
    dissolved_oxygen = np.clip(rng.normal(7.5, 2.0, rows), 0.0, 20.0)

    # --- Physically-motivated potability score ---------------------------
    # Each term contributes positively when the reading sits inside the safe
    # band. The score is a sum of soft indicators plus noise; a threshold turns
    # it into the binary Potability label.
    score = np.zeros(rows)

    score += 1.4 * np.exp(-((ph - 7.2) ** 2) / (2 * 0.7 ** 2))          # pH near neutral
    score += 1.2 * (turbidity < 5.0)                                    # clear water
    score += 0.6 * np.exp(-turbidity / 25.0)                            # softer turbidity reward
    score += 1.3 * np.exp(-((np.log1p(tds) - np.log1p(350.0)) ** 2) / (2 * 1.2 ** 2))  # moderate TDS
    score += 0.8 * np.exp(-((temperature - 18.0) ** 2) / (2 * 10.0 ** 2))  # cool-ish water
    score += 1.1 * np.exp(-((dissolved_oxygen - 8.0) ** 2) / (2 * 2.0 ** 2))  # healthy DO

    # Noise so the classes overlap and the model must generalise.
    score += rng.normal(0.0, 0.55, rows)

    threshold = np.median(score)
    potability = (score >= threshold).astype(int)

    return pd.DataFrame(
        {
            "ph": np.round(ph, 2),
            "turbidity": np.round(turbidity, 2),
            "tds": np.round(tds, 2),
            "temperature": np.round(temperature, 2),
            "dissolved_oxygen": np.round(dissolved_oxygen, 2),
            "Potability": potability,
        }
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a synthetic water potability dataset")
    parser.add_argument("--rows", type=int, default=3000)
    parser.add_argument(
        "--out",
        default=os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "ml", "datasets", "water_potability.csv"
        ),
    )
    args = parser.parse_args(argv)

    frame = generate(rows=args.rows)
    out_path = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    frame.to_csv(out_path, index=False)

    balance = frame["Potability"].mean()
    print(f"Wrote {len(frame)} rows to {out_path}")
    print(f"  potable share: {balance:.3f}")
    print(f"  columns      : {', '.join(frame.columns)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
