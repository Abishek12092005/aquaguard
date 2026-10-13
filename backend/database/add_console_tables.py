"""
Creates the tables added after the original schema: login_events and
admin_settings.

WHY THIS EXISTS AS A SCRIPT AND NOT A MIGRATION FRAMEWORK. The project has no
Alembic setup — `database/schema.sql` is applied by hand — so a schema change
needs a small, readable, idempotent step that can be run against a database that
already holds data. This is that step.

It is idempotent: each statement is `CREATE TABLE IF NOT EXISTS`, so running it
twice is a no-op rather than an error.

Usage (from `backend/`, with the venv interpreter):

    python -m database.add_console_tables
    python -m database.add_console_tables --database aquaguard_db_test

A NOTE ON PERMISSIONS. `aquaguard_ai` is granted SELECT/INSERT/UPDATE/DELETE
only - deliberately no CREATE - so this script CANNOT reshape a database unless
that account was granted rights there. If it reports "CREATE command denied",
apply the new tables from `database/schema.sql` as a MySQL administrator, or
provision the test database from the updated schema (which now includes them).

Reads DB_HOST / DB_PORT / DB_NAME / DB_USER / DB_PASSWORD exactly like the app,
so it cannot be pointed somewhere the application is not.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import create_engine, inspect, text

from app.config import BaseConfig

# Each entry is (table name, DDL). The DDL mirrors `database/schema.sql`
# exactly; a divergence between the two would make a fresh install and an
# upgraded one behave differently, which is the worst kind of schema bug.
TABLES: list[tuple[str, str]] = [
    (
        "login_events",
        """
        CREATE TABLE IF NOT EXISTS `login_events` (
          `id`             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
          `user_id`        BIGINT UNSIGNED NULL,
          `email`          VARCHAR(190)    NOT NULL,
          `event_type`     VARCHAR(20)     NOT NULL DEFAULT 'login',
          `success`        TINYINT(1)      NOT NULL DEFAULT 1,
          `ip_address`     VARCHAR(45)     NULL,
          `user_agent`     VARCHAR(255)    NULL,
          `device`         VARCHAR(80)     NULL,
          `failure_reason` VARCHAR(120)    NULL,
          `created_at`     TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY (`id`),
          KEY `ix_login_events_created` (`created_at`),
          KEY `ix_login_events_user_created` (`user_id`, `created_at`),
          KEY `ix_login_events_email` (`email`),
          KEY `ix_login_events_success` (`success`),
          CONSTRAINT `fk_login_events_user`
            FOREIGN KEY (`user_id`) REFERENCES `users` (`id`)
            ON DELETE CASCADE ON UPDATE CASCADE,
          CONSTRAINT `ck_login_events_type`
            CHECK (`event_type` IN ('login', 'logout', 'register', 'admin_login'))
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
          COMMENT='Sign-in history. Append-only; never holds a credential.'
        """,
    ),
    (
        "admin_settings",
        """
        CREATE TABLE IF NOT EXISTS `admin_settings` (
          `id`                     INT UNSIGNED NOT NULL DEFAULT 1,
          `password_hash`          VARCHAR(255) NULL,
          `notification_templates` TEXT         NULL,
          `notification_settings`  TEXT         NULL,
          `parameter_limits`       TEXT         NULL,
          `admin_username`         VARCHAR(190) NULL,
          `admin_email`            VARCHAR(190) NULL,
          `reset_code`             TEXT         NULL,
          `location_scope_mode`    VARCHAR(20)  NULL,
          `location_scope_state`   VARCHAR(190) NULL,
          `location_scope_country` VARCHAR(190) NULL,
          `created_at`             TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
          `updated_at`             TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
                                                ON UPDATE CURRENT_TIMESTAMP,
          PRIMARY KEY (`id`),
          CONSTRAINT `ck_admin_settings_singleton` CHECK (`id` = 1)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
          COMMENT='Single-row admin console state.'
        """,
    ),
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
    parser.add_argument(
        "--database",
        default=None,
        help="Override the database name (e.g. aquaguard_db_test).",
    )
    args = parser.parse_args()

    uri = _engine_uri(args.database)
    database = uri.split("?")[0].rsplit("/", 1)[1]

    print(f"Target database: {database}")
    engine = create_engine(uri)

    existing = set(inspect(engine).get_table_names())

    with engine.begin() as connection:
        for name, ddl in TABLES:
            if name in existing:
                print(f"  {name}: already present — nothing to do.")
                continue
            connection.execute(text(ddl))
            print(f"  {name}: created")

    # Verify by asking the database, not by trusting the statements above.
    after = set(inspect(engine).get_table_names())
    missing = [name for name, _ in TABLES if name not in after]
    if missing:
        print(f"  MISSING after the run: {missing}")
        return 1

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
