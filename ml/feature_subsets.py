"""Feature-subset contract shared by training and inference.

The model must be able to answer with any subset of the five parameters, and it
must be honest about how much that answer is worth. This module is the single
place that defines:

    * the five features, in canonical order
    * every supported input configuration (each feature on its own, every pair,
      every triple, ... up to all five)
    * the configuration key format used in metadata and in the database

WHY SUBSETS RATHER THAN IMPUTATION. The tempting shortcut is to fill the missing
parameters with the training median and run the five-feature model. That is not a
partial prediction, it is a fabricated one: the model is told "turbidity is
exactly the median" and answers as if someone had measured it. The result looks
identical to a real five-parameter reading while being derived from data that did
not exist. Every number in the contract below exists to make that impossible —
a single-parameter request is served by a model that was TRAINED on that one
parameter, and its validation score is reported alongside the answer.

The number of configurations is the non-empty subsets of five features, i.e.
2^5 - 1 = 31. That is small enough to train exhaustively and evaluate honestly,
which is what `train_subset_models.py` does.
"""

from itertools import combinations

# Canonical order. Identical to the order used by the five-feature model, the
# database columns and the API, so no translation layer is ever needed.
FEATURES: tuple[str, ...] = (
    "ph",
    "turbidity",
    "tds",
    "temperature",
    "dissolved_oxygen",
)

# How a subset is named everywhere outside this module: the feature names in
# canonical order, joined by '+'. `ph+tds` and `tds+ph` therefore denote the same
# configuration, which is what makes the key safe to use as a database value.
CONFIG_SEPARATOR = "+"

# The complete assessment configuration. Kept as a named constant because the
# rest of the system treats it specially: it is the only one that may be
# described as a full assessment.
FULL_CONFIG: str = CONFIG_SEPARATOR.join(FEATURES)


def config_key(features) -> str:
    """Build the canonical key for a set of features.

    Always emitted in canonical order regardless of the caller's order, so a
    request of `{"tds": ..., "ph": ...}` and one of `{"ph": ..., "tds": ...}`
    resolve to the same trained model.
    """
    present = set(features)
    unknown = present - set(FEATURES)
    if unknown:
        raise ValueError(f"Unknown feature(s): {sorted(unknown)}")
    if not present:
        raise ValueError("At least one feature is required")
    return CONFIG_SEPARATOR.join(name for name in FEATURES if name in present)


def config_features(key: str) -> tuple[str, ...]:
    """Inverse of `config_key`: a key back to its features, in canonical order."""
    parts = tuple(part for part in key.split(CONFIG_SEPARATOR) if part)
    unknown = set(parts) - set(FEATURES)
    if unknown:
        raise ValueError(f"Unknown feature(s) in config: {sorted(unknown)}")
    return tuple(name for name in FEATURES if name in parts)


def all_configs() -> list[str]:
    """Every supported input configuration, shortest first.

    Ordered by size then canonically, so a report reads as "one parameter, then
    pairs, then triples..." rather than in arbitrary set order.
    """
    keys: list[str] = []
    for size in range(1, len(FEATURES) + 1):
        for combination in combinations(FEATURES, size):
            keys.append(CONFIG_SEPARATOR.join(combination))
    return keys


def is_supported(key: str) -> bool:
    """True when `key` names a configuration the system can serve."""
    return key in _SUPPORTED


def size_of(key: str) -> int:
    """How many features a configuration uses."""
    return len(config_features(key))


_SUPPORTED = frozenset(all_configs())

# Configuration keys grouped by how many features they use. Used by the report
# generator and by the tests that assert every size is covered.
CONFIGS_BY_SIZE: dict[int, tuple[str, ...]] = {
    size: tuple(key for key in _SUPPORTED if len(config_features(key)) == size)
    for size in range(1, len(FEATURES) + 1)
}
