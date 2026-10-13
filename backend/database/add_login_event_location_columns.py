"""Aligns the `login_events` location columns with the auth email feature.

WHY THIS EXISTS. Step 10 adds the sign-up / sign-in PLACE to the admin emails,
which meant the tracking row it is read from needed a `location_pincode` column
that the model declares but older tables do not have. The other four place
columns (`location_name`, `location_city`, `location_state`, `location_country`)
predate this and are only re-added when missing, so the script is safe against
every shape of table.

    location_pincode -> ADD, when missing

It reads the live table first — MySQL has no `ADD COLUMN IF NOT EXISTS` before
8.0, so the inspection is what makes it repeatable.

PRIVACY NOTE. Only place labels live here. There is deliberately NO latitude or
longitude column: the admin notices show an approximate place, never a position.

Usage (from `backend/`, with the venv interpreter):

    python -m database.add_login_event_location_columns
    python -m database.add_login_event_location_columns --database aquaguard_db_test
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import create_engine, inspect, text

from app.config import BaseConfig

TABLE = "login_events"

# (column, DDL fragment). Each is added only when it is missing.
ADD_COLUMNS: list[tuple[str, str]] = [
    ("location_name", "ADD COLUMN `location_name` VARCHAR(190) NULL"),
    ("location_city", "ADD COLUMN `location_city` VARCHAR(120) NULL"),
    ("location_state", "ADD COLUMN `location_state` VARCHAR(120) NULL"),
    ("location_country", "ADD COLUMN `location_country` VARCHAR(120) NULL"),
    ("location_pincode", "ADD COLUMN `location_pincode` VARCHAR(20) NULL"),
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
        print(f"  {TABLE}: does not exist -- run add_console_tables / schema.sql first.")
        return 1

    existing = {column["name"] for column in inspect(engine).get_columns(TABLE)}

    with engine.begin() as connection:
        for name, ddl in ADD_COLUMNS:
            if name in existing:
                print(f"  {name}: already present -- nothing to do.")
                continue
            connection.execute(text(f"ALTER TABLE `{TABLE}` {ddl}"))
            print(f"  {name}: added")

    # Verify by asking the database, not by trusting the statements above.
    after = {column["name"] for column in inspect(engine).get_columns(TABLE)}
    required = {name for name, _ in ADD_COLUMNS}
    missing = sorted(required - after)
    if missing:
        print(f"  MISSING after the run: {missing}")
        return 1

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())