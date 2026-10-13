"""Adds the location access scope columns to `admin_settings`.

WHAT THIS ADDS

    location_scope_mode      "state", "country" or NULL (no restriction)
    location_scope_state     the chosen state, when the mode is "state"
    location_scope_country   the chosen country, when the mode is "country"

WHY A SCRIPT AND NOT A MIGRATION. The project has no Alembic setup -- see
`add_console_tables.py` -- so a column addition needs a small, idempotent step
that can run against a database already holding data. MySQL has no
`ADD COLUMN IF NOT EXISTS`, so the script inspects the live table first and only
adds what is missing.

WHY THESE ARE PLAIN COLUMNS AND NOT JSON. Each is a single value, and the NULL
mode is what turns the restriction off, so a plain nullable column expresses the
feature exactly. The enforcement path reads them directly.

Usage (from `backend/`, with the venv interpreter):

    python -m database.add_location_scope_columns
    python -m database.add_location_scope_columns --database aquaguard_db_test

Reads DB_HOST / DB_PORT / DB_NAME / DB_USER / DB_PASSWORD exactly like the app,
so it cannot be pointed somewhere the application is not.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import create_engine, inspect, text

from app.config import BaseConfig

# (column name, DDL fragment). Order does not matter; each is independent.
COLUMNS: list[tuple[str, str]] = [
    ("location_scope_mode", "ADD COLUMN `location_scope_mode` VARCHAR(20) NULL"),
    ("location_scope_state", "ADD COLUMN `location_scope_state` VARCHAR(190) NULL"),
    ("location_scope_country", "ADD COLUMN `location_scope_country` VARCHAR(190) NULL"),
]

TABLE = "admin_settings"


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

    inspector = inspect(engine)
    if TABLE not in inspector.get_table_names():
        print(f"  {TABLE}: does not exist -- run add_console_tables first.")
        return 1

    existing = {column["name"] for column in inspector.get_columns(TABLE)}

    with engine.begin() as connection:
        for name, ddl in COLUMNS:
            if name in existing:
                print(f"  {name}: already present -- nothing to do.")
                continue
            connection.execute(text(f"ALTER TABLE `{TABLE}` {ddl}"))
            print(f"  {name}: added")

    # Verify by asking the database, not by trusting the statements above.
    after = {column["name"] for column in inspect(engine).get_columns(TABLE)}
    missing = [name for name, _ in COLUMNS if name not in after]
    if missing:
        print(f"  MISSING after the run: {missing}")
        return 1

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())