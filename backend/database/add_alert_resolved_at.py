"""
Adds `alerts.resolved_at` to an existing database.

WHY THIS EXISTS AS A SCRIPT AND NOT A MIGRATION FRAMEWORK. The project has no
Alembic setup — `database/schema.sql` is applied by hand — so a schema change
needs a small, readable, idempotent step that can be run against a database that
already holds data. This is that step.

It is idempotent: running it twice is a no-op, because it asks
`information_schema` whether the column is already there before altering.

Usage (from `backend/`, with the venv interpreter):

    python -m database.add_alert_resolved_at
    python -m database.add_alert_resolved_at --database aquaguard_db_test
Reads DB_HOST / DB_PORT / DB_NAME / DB_USER / DB_PASSWORD exactly like the app,
so it cannot be pointed somewhere the application is not.

A NOTE ON PERMISSIONS. `aquaguard_ai` is granted SELECT/INSERT/UPDATE/DELETE
only - deliberately no ALTER - so this script CANNOT reshape the test database
unless that account was granted rights there too. If it reports
"ALTER command denied", apply the equivalent statement from
`database/add_alert_resolved_at.sql` as a MySQL administrator, or provision the
test database from the updated `schema.sql` (which now includes the column).
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import create_engine, text

from app.config import BaseConfig


def _engine_uri(database: str | None) -> str:
    uri = BaseConfig.SQLALCHEMY_DATABASE_URI
    if not database:
        return uri
    # Swap the database name in the URI, keeping credentials and host intact.
    base, _, query = uri.partition("?")
    prefix = base.rsplit("/", 1)[0]
    return f"{prefix}/{database}?{query}" if query else f"{prefix}/{database}"


def column_exists(connection, database: str, table: str, column: str) -> bool:
    row = connection.execute(
        text(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema = :db AND table_name = :tbl AND column_name = :col"
        ),
        {"db": database, "tbl": table, "col": column},
    ).scalar_one()
    return bool(row)


def index_exists(connection, database: str, table: str, index: str) -> bool:
    row = connection.execute(
        text(
            "SELECT COUNT(*) FROM information_schema.statistics "
            "WHERE table_schema = :db AND table_name = :tbl AND index_name = :idx"
        ),
        {"db": database, "tbl": table, "idx": index},
    ).scalar_one()
    return bool(row)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        default=None,
        help="Override the database name (e.g. aquaguard_db_test).",
    )
    args = parser.parse_args()

    uri = _engine_uri(args.database)
    # The name is whatever is after the last '/' and before the query string.
    database = uri.split("?")[0].rsplit("/", 1)[1]

    print(f"Target database: {database}")
    engine = create_engine(uri)

    with engine.begin() as connection:
        if column_exists(connection, database, "alerts", "resolved_at"):
            print("  alerts.resolved_at already exists — nothing to do.")
        else:
            connection.execute(
                text(
                    "ALTER TABLE alerts "
                    "ADD COLUMN resolved_at TIMESTAMP NULL DEFAULT NULL "
                    "COMMENT 'NULL while open; set when resolved'"
                )
            )
            print("  added alerts.resolved_at")

        if index_exists(connection, database, "alerts", "ix_alerts_user_resolved"):
            print("  ix_alerts_user_resolved already exists — nothing to do.")
        else:
            connection.execute(
                text(
                    "ALTER TABLE alerts "
                    "ADD KEY ix_alerts_user_resolved (user_id, resolved_at)"
                )
            )
            print("  added index ix_alerts_user_resolved")

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
