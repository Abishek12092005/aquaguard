"""Repairs a database that predates later column additions.

WHY THIS EXISTS. `database/schema.sql` uses `CREATE TABLE IF NOT EXISTS`, so it
never ALTERs a table that already exists, and the app account
(`aquaguard_ai`) is granted SELECT/INSERT/UPDATE/DELETE plus CREATE and INDEX
- deliberately NOT ALTER. So a database created before a column was added
silently drifts: the app then fails at runtime with "Unknown column '<x>' in
'field list'", which reads as an application bug rather than a schema one.

This script adds exactly the columns the models declare and the schema omits
for an existing table. It is idempotent: it inspects each table first and only
issues the ALTER for what is missing.

    python database/repair_missing_columns.py                     # the app's DB
    python database/repair_missing_columns.py --database aquaguard_db_test

IT NEVER DROPS OR TRUNCATES ANYTHING, and it prints every statement it runs.
It needs ALTER rights on the target database; `aquaguard_ai` has them on
`aquaguard_db`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# `app` lives one directory up; this file is run as `python database/...`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, inspect, text  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402


def _base_uri() -> str:
    from app.config import BaseConfig

    return BaseConfig.SQLALCHEMY_DATABASE_URI


def _uri_for(database: str | None) -> str:
    uri = _base_uri()
    if not database:
        return uri
    base, _, query = uri.partition("?")
    prefix = base.rsplit("/", 1)[0]
    return f"{prefix}/{database}?{query}" if query else f"{prefix}/{database}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=None, help="Override the database name.")
    args = parser.parse_args()

    name = args.database or _base_uri().split("?")[0].rsplit("/", 1)[1]
    print(f"Target database: {name}")

    uri = _uri_for(args.database)
    engine = create_engine(uri)
    inspector = inspect(engine)

    tables = set(inspector.get_table_names())
    if not tables:
        print("  no tables present - apply database/schema.sql instead.")
        return 1

    # (table, column, DDL). Derived from the models; the same definitions the
    # additive migration scripts in this folder use.
    COLUMNS: list[tuple[str, str, str]] = [
        ("admin_settings", "admin_username", "ADD COLUMN `admin_username` VARCHAR(190) NULL"),
        ("admin_settings", "admin_email", "ADD COLUMN `admin_email` VARCHAR(190) NULL"),
        ("admin_settings", "admin_approval_email", "ADD COLUMN `admin_approval_email` VARCHAR(190) NULL"),
        ("admin_settings", "reset_code", "ADD COLUMN `reset_code` TEXT NULL"),
        ("admin_settings", "unlock_confirmation", "ADD COLUMN `unlock_confirmation` TEXT NULL"),
        # PROMPT 13, requirement 4: scope provenance. Kept apart from the row's
        # own `updated_at` because that one moves on every unrelated settings
        # save, so it cannot answer "when was the SCOPE last touched".
        ("admin_settings", "location_scope_updated_at", "ADD COLUMN `location_scope_updated_at` TIMESTAMP NULL DEFAULT NULL"),
        ("admin_settings", "location_scope_updated_by", "ADD COLUMN `location_scope_updated_by` VARCHAR(190) NULL"),
        ("model_audit_logs", "created_at", "ADD COLUMN `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"),
        ("model_audit_logs", "updated_at", "ADD COLUMN `updated_at` TIMESTAMP NULL DEFAULT NULL"),
        ("users", "reset_code_hash", "ADD COLUMN `reset_code_hash` VARCHAR(255) NULL"),
        ("users", "reset_code_expires_at", "ADD COLUMN `reset_code_expires_at` TIMESTAMP NULL DEFAULT NULL"),
        ("users", "reset_code_attempts", "ADD COLUMN `reset_code_attempts` INT NOT NULL DEFAULT 0"),
        ("login_events", "location_name", "ADD COLUMN `location_name` VARCHAR(190) NULL"),
        ("login_events", "location_city", "ADD COLUMN `location_city` VARCHAR(120) NULL"),
        ("login_events", "location_state", "ADD COLUMN `location_state` VARCHAR(120) NULL"),
        ("login_events", "location_country", "ADD COLUMN `location_country` VARCHAR(120) NULL"),
        ("login_events", "location_pincode", "ADD COLUMN `location_pincode` VARCHAR(20) NULL"),
        ("water_predictions", "location_name", "ADD COLUMN `location_name` VARCHAR(190) NULL"),
        ("water_predictions", "location_city", "ADD COLUMN `location_city` VARCHAR(120) NULL"),
        # The area/locality and district. The model declares both by name, so a
        # database created before they were added fails every location-carrying
        # insert with "Unknown column 'location_district'". This is the pair whose
        # absence broke the live dev database until they were applied by hand;
        # they belong here so a repaired or fresh-but-old database gets them too.
        ("water_predictions", "location_area", "ADD COLUMN `location_area` VARCHAR(120) NULL"),
        ("water_predictions", "location_district", "ADD COLUMN `location_district` VARCHAR(120) NULL"),
        ("water_predictions", "location_state", "ADD COLUMN `location_state` VARCHAR(120) NULL"),
        ("water_predictions", "location_country", "ADD COLUMN `location_country` VARCHAR(120) NULL"),
        ("water_predictions", "location_pincode", "ADD COLUMN `location_pincode` VARCHAR(20) NULL"),
        ("water_predictions", "location_lat", "ADD COLUMN `location_lat` DOUBLE NULL"),
        ("water_predictions", "location_lng", "ADD COLUMN `location_lng` DOUBLE NULL"),
        ("water_predictions", "water_source_type", "ADD COLUMN `water_source_type` VARCHAR(60) NULL"),
        ("water_predictions", "nearby_water_source", "ADD COLUMN `nearby_water_source` VARCHAR(190) NULL"),
        ("water_predictions", "nearby_water_source_distance", "ADD COLUMN `nearby_water_source_distance` DOUBLE NULL"),
        # PROMPT 1, E.9: provenance of the readings, persisted with the record.
        ("water_predictions", "param_provenance", "ADD COLUMN `param_provenance` VARCHAR(40) NULL"),
        ("alerts", "resolved_at", "ADD COLUMN `resolved_at` TIMESTAMP NULL DEFAULT NULL"),
    ]

    added = 0
    failures: list[str] = []
    with engine.begin() as connection:
        for table, column, ddl in COLUMNS:
            if table not in tables:
                continue
            live = {c["name"] for c in inspector.get_columns(table)}
            if column in live:
                continue
            statement = f"ALTER TABLE `{table}` {ddl}"
            try:
                connection.execute(text(statement))
                added += 1
                print(f"  + {table}.{column}")
            except SQLAlchemyError as exc:
                detail = str(getattr(exc, "orig", exc))[:140]
                failures.append(f"{table}.{column}: {detail}")
                print(f"  ! {table}.{column}: {detail}")

    print(f"\n{added} column(s) added.")
    if failures:
        print("Failed (the account needs ALTER on this database):")
        for line in failures:
            print(f"  - {line}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())