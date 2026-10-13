"""
Creates the report_email_audits table (PROMPT 12).

WHY THIS EXISTS AS A SCRIPT AND NOT A MIGRATION FRAMEWORK. The project has no
Alembic setup — `database/schema.sql` is applied by hand — so a schema change
needs a small, readable, idempotent step that can be run against a database
that already holds data. This is that step, in the same shape as
`add_console_tables.py`.

It is idempotent: the statement is `CREATE TABLE IF NOT EXISTS`, so running it
twice is a no-op rather than an error.

Usage (from `backend/`, with the venv interpreter):

    python -m database.add_report_email_audit_table
    python -m database.add_report_email_audit_table --database aquaguard_db_test

A NOTE ON PERMISSIONS. `aquaguard_ai` is granted SELECT/INSERT/UPDATE/DELETE
only - deliberately no CREATE - so this script CANNOT reshape a database unless
that account was granted rights there. If it reports "CREATE command denied",
apply the table from `database/schema.sql` as a MySQL administrator, or
provision the test database from the updated schema (which now includes it).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# `app` lives one directory up; this file is run as `python database/...`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, inspect, text  # noqa: E402

from app.config import BaseConfig  # noqa: E402

# Mirrors `database/schema.sql` section 11 exactly; a divergence between the
# two would make a fresh install and an upgraded one behave differently.
REPORT_EMAIL_AUDITS_DDL = """
CREATE TABLE IF NOT EXISTS `report_email_audits` (
  `id`                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Primary key',
  `recipient_email`    VARCHAR(190)   NOT NULL,
  `report_option`      VARCHAR(20)    NOT NULL,
  `delivery_status`    VARCHAR(30)    NOT NULL,
  `reports_included`   INT            NULL,
  `user_id`            BIGINT UNSIGNED NULL,
  `requester_name`     VARCHAR(120)   NULL,
  `admin_username`     VARCHAR(120)   NULL,
  `location_name`      VARCHAR(190)   NULL,
  `location_city`      VARCHAR(120)   NULL,
  `location_state`     VARCHAR(120)   NULL,
  `location_country`   VARCHAR(120)   NULL,
  `location_pincode`   VARCHAR(20)    NULL,
  `location_source`    VARCHAR(20)    NULL,
  `device_label`       VARCHAR(80)    NULL,
  `created_at`         TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP
                                        COMMENT 'Request timestamp (UTC)',
  PRIMARY KEY (`id`),
  KEY `ix_report_email_recipient` (`recipient_email`),
  KEY `ix_report_email_option` (`report_option`),
  KEY `ix_report_email_status` (`delivery_status`),
  KEY `ix_report_email_user` (`user_id`),
  KEY `ix_report_email_created` (`created_at`),
  CONSTRAINT `fk_report_email_user`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Append-only trail of report-download-by-email requests.'
"""

TABLES: list[tuple[str, str]] = [("report_email_audits", REPORT_EMAIL_AUDITS_DDL)]


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
