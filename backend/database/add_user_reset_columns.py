"""Adds the self-service password-reset columns to `users`.

WHAT THIS ADDS

    reset_code_hash        bcrypt hash of the pending 6-digit reset code
    reset_code_expires_at  epoch seconds the code stops working
    reset_code_attempts    wrong guesses so far, to cap brute force

WHY A SCRIPT AND NOT A MIGRATION. The project has no Alembic setup -- see
`add_console_tables.py` and `add_admin_identity_columns.py` -- so a column
addition needs a small, idempotent step that can run against a database already
holding data. MySQL has no `ADD COLUMN IF NOT EXISTS`, so the script inspects the
live table first and only adds what is missing.

Usage (from `backend/`, with the venv interpreter):

    python -m database.add_user_reset_columns
    python -m database.add_user_reset_columns --database aquaguard_db_test

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
    ("reset_code_hash", "ADD COLUMN `reset_code_hash` VARCHAR(255) NULL"),
    ("reset_code_expires_at", "ADD COLUMN `reset_code_expires_at` INT NULL"),
    ("reset_code_attempts", "ADD COLUMN `reset_code_attempts` INT NOT NULL DEFAULT 0"),
]

TABLE = "users"


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
        print(f"  {TABLE}: does not exist -- run the schema first.")
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
