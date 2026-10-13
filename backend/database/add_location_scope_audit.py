"""
Adds the PROMPT 13 location-scope additions to a database that predates them:
the `location_scope_audits` table, and the two provenance columns on
`admin_settings`.

WHY A SCRIPT AND NOT A MIGRATION FRAMEWORK. The project has no Alembic setup —
`database/schema.sql` is applied by hand — and it uses `CREATE TABLE IF NOT
EXISTS`, so it never ALTERs a table that already exists. See `add_console_tables.py`
for the same reasoning applied to whole tables.

It is idempotent: the table statement is `CREATE TABLE IF NOT EXISTS`, and each
column is inspected before its ALTER is issued, because MySQL has no
`ADD COLUMN IF NOT EXISTS`.

Usage (from `backend/`, with the venv interpreter):

    python -m database.add_location_scope_audit
    python -m database.add_location_scope_audit --database aquaguard_db_test

It needs ALTER rights on the target database. `aquaguard_ai` has them on
`aquaguard_db`; the test database may need them granting first.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# `app` lives one directory up; this file is run as `python database/...`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, inspect, text  # noqa: E402

from app.config import BaseConfig  # noqa: E402

TABLE_DDL = """
CREATE TABLE IF NOT EXISTS `location_scope_audits` (
  `id`               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Primary key',
  `actor`            VARCHAR(190)   NOT NULL COMMENT 'Console identity',
  `new_mode`         VARCHAR(20)    NULL COMMENT 'state | country | NULL=off',
  `new_state`        VARCHAR(190)   NULL,
  `new_country`      VARCHAR(190)   NULL,
  `previous_mode`    VARCHAR(20)    NULL,
  `previous_state`   VARCHAR(190)   NULL,
  `previous_country` VARCHAR(190)   NULL,
  `success`          TINYINT(1)     NOT NULL DEFAULT 0 COMMENT '0 = refused',
  `detail`           VARCHAR(500)   NULL COMMENT 'Short reason; never a credential',
  `occurred_at`      TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_scope_audit_actor` (`actor`),
  KEY `ix_scope_audit_new_mode` (`new_mode`),
  KEY `ix_scope_audit_success` (`success`),
  KEY `ix_scope_audit_occurred` (`occurred_at`),
  CONSTRAINT `ck_scope_audit_mode`
    CHECK (`new_mode` IS NULL OR `new_mode` IN ('state', 'country'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Append-only trail of admin location-scope changes.'
"""

# (column, DDL fragment) on `admin_settings`.
COLUMNS: list[tuple[str, str]] = [
    (
        "location_scope_updated_at",
        "ADD COLUMN `location_scope_updated_at` TIMESTAMP NULL DEFAULT NULL "
        "COMMENT 'Last SCOPE change, not the row timestamp'",
    ),
    (
        "location_scope_updated_by",
        "ADD COLUMN `location_scope_updated_by` VARCHAR(190) NULL "
        "COMMENT 'Console identity of the last scope change'",
    ),
]


def _uri_for(database: str | None) -> str:
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

    uri = _uri_for(args.database)
    database = uri.split("?")[0].rsplit("/", 1)[1]
    print(f"Target database: {database}")

    engine = create_engine(uri)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    with engine.begin() as connection:
        if "location_scope_audits" in tables:
            print("  location_scope_audits: already present - nothing to do.")
        else:
            connection.execute(text(TABLE_DDL))
            print("  location_scope_audits: created")

        if "admin_settings" not in tables:
            print("  admin_settings: absent - skipping the provenance columns.")
        else:
            live = {c["name"] for c in inspector.get_columns("admin_settings")}
            for column, ddl in COLUMNS:
                if column in live:
                    print(f"  admin_settings.{column}: already present - nothing to do.")
                    continue
                connection.execute(text(f"ALTER TABLE `admin_settings` {ddl}"))
                print(f"  admin_settings.{column}: added")

    # Verify by asking the database, not by trusting the statements above.
    after = set(inspect(engine).get_table_names())
    if "location_scope_audits" not in after:
        print("  MISSING after the run: location_scope_audits")
        return 1
    live = {c["name"] for c in inspect(engine).get_columns("admin_settings")}
    missing = [c for c, _ in COLUMNS if c not in live]
    if missing:
        print(f"  MISSING after the run: admin_settings.{missing}")
        return 1

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())