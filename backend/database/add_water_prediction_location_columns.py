"""Aligns the `water_predictions` location columns with the ORM model.

WHY THIS EXISTS. `WaterPrediction` (app/models/water_prediction.py) writes its
location columns by name. The original `schema.sql` had drifted from it:

    schema.sql            model                     result
    ----------            -----                     ------
    location_label        location_name             insert fails: unknown column
    (missing)             location_city             insert fails: unknown column
    (missing)             location_country          insert fails: unknown column

So a location-carrying prediction raised "Unknown column 'location_city'" on
insert and NOTHING was stored — which is why the prediction history showed no
location even when the sample was taken with one.

WHAT THIS DOES, IDEMPOTENTLY

    location_label  ->  location_name      (RENAME, when the old column exists)
    location_city   ->  ADD, when missing
    location_country->  ADD, when missing

It reads the live table first, so it is safe to run against a fresh database
(where the columns already exist under the new names) and against an old one.
MySQL has no `RENAME COLUMN IF EXISTS` / `ADD COLUMN IF NOT EXISTS` before 8.0,
so the inspection is what makes it repeatable.

Usage (from `backend/`, with the venv interpreter):

    python -m database.add_water_prediction_location_columns
    python -m database.add_water_prediction_location_columns --database aquaguard_db_test
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import create_engine, inspect, text

from app.config import BaseConfig

TABLE = "water_predictions"

# (column, DDL fragment) for the columns that may be missing outright.
#
# The live table predates the whole location feature, so on an older database
# EVERY one of these can be absent. Each is added only when it is missing, so the
# script is safe to re-run.
ADD_COLUMNS: list[tuple[str, str]] = [
    ("location_city", "ADD COLUMN `location_city` VARCHAR(120) NULL"),
    ("location_state", "ADD COLUMN `location_state` VARCHAR(120) NULL"),
    ("location_country", "ADD COLUMN `location_country` VARCHAR(120) NULL"),
    ("location_pincode", "ADD COLUMN `location_pincode` VARCHAR(20) NULL"),
    ("location_lat", "ADD COLUMN `location_lat` DECIMAL(9,6) NULL"),
    ("location_lng", "ADD COLUMN `location_lng` DECIMAL(9,6) NULL"),
    ("water_source_type", "ADD COLUMN `water_source_type` VARCHAR(60) NULL"),
    ("nearby_water_source", "ADD COLUMN `nearby_water_source` VARCHAR(190) NULL"),
    ("nearby_water_source_distance", "ADD COLUMN `nearby_water_source_distance` DECIMAL(8,2) NULL"),
]


def _engine_uri(database: str | None) -> str:
    uri = BaseConfig.SQLALCHEMY_DATABASE_URI
    if not database:
        return uri
    base, _, query = uri.partition("?")
    prefix = base.rsplit("/", 1)[0]
    return f"{prefix}/{database}?{query}" if query else f"{prefix}/{database}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=None, help="Override the database name.")
    args = parser.parse_args()

    uri = _engine_uri(args.database)
    database = uri.split("?")[0].rsplit("/", 1)[1]

    print(f"Target database: {database}")
    engine = create_engine(uri)

    if TABLE not in inspect(engine).get_table_names():
        print(f"  {TABLE}: does not exist -- run schema.sql first.")
        return 1

    existing = {column["name"] for column in inspect(engine).get_columns(TABLE)}

    with engine.begin() as connection:
        # --- Rename the old label column, when it is the one present ---------
        if "location_name" not in existing and "location_label" in existing:
            connection.execute(
                text(
                    f"ALTER TABLE `{TABLE}` RENAME COLUMN `location_label` TO `location_name`"
                )
            )
            print("  location_label -> location_name: renamed")
        elif "location_name" in existing:
            print("  location_name: already present -- nothing to do.")
        else:
            # Neither exists: add the canonical name so the ORM can write it.
            connection.execute(
                text(f"ALTER TABLE `{TABLE}` ADD COLUMN `location_name` VARCHAR(190) NULL")
            )
            print("  location_name: added")

        # --- Add any column the table is missing entirely --------------------
        for name, ddl in ADD_COLUMNS:
            if name in existing:
                print(f"  {name}: already present -- nothing to do.")
                continue
            connection.execute(text(f"ALTER TABLE `{TABLE}` {ddl}"))
            print(f"  {name}: added")

    # Verify by asking the database, not by trusting the statements above.
    after = {column["name"] for column in inspect(engine).get_columns(TABLE)}
    required = {"location_name", "location_city", "location_state",
                "location_country", "location_pincode", "location_lat", "location_lng",
                "water_source_type", "nearby_water_source", "nearby_water_source_distance"}
    missing = sorted(required - after)
    if missing:
        print(f"  MISSING after the run: {missing}")
        return 1

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
