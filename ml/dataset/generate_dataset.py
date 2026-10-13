"""Generate the water_quality dataset (3-class: SAFE / MODERATE / UNSAFE).

The public water-potability dataset is binary and is not committed to this repo.
This script produces a labelled dataset with the project's five features and a
three-way `water_quality` target, using well-known drinking-water guidance
(WHO / BIS-flavoured thresholds) plus noise so the classes overlap and the model
must generalise rather than memorise.

Run from the project root:
    python ml/dataset/generate_dataset.py --rows 4000
"""

import argparse
import os

import numpy as np
import pandas as pd

FEATURES = ("ph", "turbidity", "tds", "temperature", "dissolved_oxygen")
TARGET = "water_quality"
LABELS = ("SAFE", "MODERATE", "UNSAFE")


def generate(rows: int = 4000, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)

    ph = np.clip(rng.normal(7.0, 1.4, rows), 0.0, 14.0)
    turbidity = np.clip(rng.gamma(2.0, 1.8, rows), 0.0, 1000.0)
    tds = np.clip(rng.lognormal(mean=6.3, sigma=0.8, size=rows), 0.0, 50000.0)
    temperature = np.clip(rng.normal(20.0, 8.0, rows), -5.0, 100.0)
    dissolved_oxygen = np.clip(rng.normal(7.2, 2.2, rows), 0.0, 20.0)

    # Physically-motivated suitability score: each term rewards a reading near
    # its ideal band and decays smoothly away from it.
    score = np.zeros(rows)
    score += 1.5 * np.exp(-((ph - 7.2) ** 2) / (2 * 0.8 ** 2))
    score += 1.2 * np.exp(-turbidity / 12.0)
    score += 1.3 * np.exp(-((np.log1p(tds) - np.log1p(350.0)) ** 2) / (2 * 1.3 ** 2))
    score += 0.8 * np.exp(-((temperature - 18.0) ** 2) / (2 * 11.0 ** 2))
    score += 1.1 * np.exp(-((dissolved_oxygen - 8.0) ** 2) / (2 * 2.2 ** 2))

    # Noise so class boundaries are not perfectly separable.
    score += rng.normal(0.0, 0.6, rows)

    # Two thresholds split the score into three ordered bands. The cut points are
    # the 30th and 65th percentiles, giving a realistic class imbalance.
    low, high = np.percentile(score, [30, 65])
    labels = np.where(score >= high, "SAFE", np.where(score >= low, "MODERATE", "UNSAFE"))

    return pd.DataFrame(
        {
            "ph": np.round(ph, 2),
            "turbidity": np.round(turbidity, 2),
            "tds": np.round(tds, 2),
            "temperature": np.round(temperature, 2),
            "dissolved_oxygen": np.round(dissolved_oxygen, 2),
            TARGET: labels,
        }
    )


def inject_missing_and_invalid(frame: pd.DataFrame, seed: int = 7) -> pd.DataFrame:
    """Introduce missing values and a few physically-invalid rows.

    Real datasets are dirty; the cleaning steps in train_model.py are exercised
    against this rather than a perfectly clean frame.
    """
    rng = np.random.default_rng(seed)
    frame = frame.copy()

    for column in ("ph", "turbidity", "tds", "dissolved_oxygen"):
        idx = rng.choice(frame.index, size=max(1, len(frame) // 40), replace=False)
        frame.loc[idx, column] = np.nan

    # Invalid records: pH out of 0-14, negative turbidity, negative temperature
    # below the physical floor.
    bad = rng.choice(frame.index, size=max(1, len(frame) // 120), replace=False)
    frame.loc[bad[: len(bad) // 3], "ph"] = rng.uniform(14.01, 20.0, len(bad[: len(bad) // 3]))
    frame.loc[bad[len(bad) // 3 : 2 * len(bad) // 3], "turbidity"] = -1.0
    frame.loc[bad[2 * len(bad) // 3 :], "temperature"] = -40.0

    return frame


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the water_quality dataset")
    parser.add_argument("--rows", type=int, default=4000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--out",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "water_quality.csv"),
    )
    args = parser.parse_args(argv)

    frame = inject_missing_and_invalid(generate(rows=args.rows, seed=args.seed), seed=args.seed)
    frame.to_csv(args.out, index=False)

    print(f"Wrote {len(frame)} rows to {args.out}")
    print("Class distribution:")
    for label, count in frame[TARGET].value_counts().items():
        print(f"  {label:<9}: {count}")
    print(f"Missing values introduced in feature columns: {int(frame[list(FEATURES)].isna().sum().sum())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
