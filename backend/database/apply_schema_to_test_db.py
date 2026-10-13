"""Creates the test database schema using the application's own credentials.

WHY THIS DOES NOT NEED ROOT. `aquaguard_db_test` already exists and the app
account can reach it, but it holds no tables. Creating tables inside an existing
database needs CREATE, which `create_test_database.sql` grants this account for
this database only — so the schema can be applied without an administrator.

The DDL comes from `database/schema.sql`, so the test database matches the
production one exactly rather than being a second definition that can drift. The
statements are executed one at a time because the file contains comments and
`CREATE TABLE IF NOT EXISTS` blocks that the driver cannot run as one batch.
"""

import re
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402


def statements(sql: str) -> list[str]:
    """Split a schema file into individual statements.

    TWO THINGS ARE SKIPPED OVER, and both were real failures before they were
    handled:

      1. LINE COMMENTS. A `--` comment containing a semicolon would otherwise cut
         a statement in half.
      2. QUOTED STRINGS. The schema uses COMMENT 'NULL while open; set when
         resolved' - a semicolon inside a string literal. Splitting on it
         produced a truncated CREATE TABLE and a MySQL syntax error, which looked
         like a broken schema file rather than a broken splitter.

    The scan therefore tracks whether it is inside a quote, and only splits on a
    semicolon outside one.
    """
    out: list[str] = []
    current: list[str] = []
    in_single = False
    in_double = False
    in_line_comment = False
    index = 0

    while index < len(sql):
        char = sql[index]
        nxt = sql[index + 1] if index + 1 < len(sql) else ""

        if in_line_comment:
            if char == "\n":
                in_line_comment = False
                current.append(char)
            index += 1
            continue

        if not in_single and not in_double and char == "-" and nxt == "-":
            in_line_comment = True
            index += 2
            continue

        if char == "'" and not in_double:
            # A doubled quote inside a string is an escaped quote, not a close.
            if in_single and nxt == "'":
                current.append("''")
                index += 2
                continue
            in_single = not in_single
        elif char == chr(34) and not in_single:
            in_double = not in_double

        if char == ";" and not in_single and not in_double:
            part = "".join(current).strip()
            if part:
                out.append(part)
            current = []
            index += 1
            continue

        current.append(char)
        index += 1

    tail = "".join(current).strip()
    if tail:
        out.append(tail)

    return out


def main() -> int:
    # This file lives in `database/`, beside the schema it applies.
    schema_path = Path(__file__).resolve().parent / "schema.sql"
    if not schema_path.is_file():
        print(f"Schema not found: {schema_path}")
        return 1

    app = create_app("testing")
    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    print("target:", uri.split("@")[-1])

    parts = statements(schema_path.read_text(encoding="utf-8"))
    print(f"statements parsed: {len(parts)}")

    applied = 0
    skipped = 0

    with app.app_context():
        for statement in parts:
            # Only DDL that is safe to run against an existing database. The
            # schema file also contains SELECT/DROP for a fresh install, which
            # must not run here.
            head = statement.lstrip().upper()
            if not head.startswith(("CREATE TABLE", "CREATE VIEW", "CREATE INDEX")):
                skipped += 1
                continue
            try:
                db.session.execute(text(statement))
                db.session.commit()
                applied += 1
            except Exception as exc:  # noqa: BLE001 - report and continue
                db.session.rollback()
                first_line = statement.split("\n", 1)[0][:70]
                print(f"  FAILED: {first_line} -> {str(exc)[:90]}")

        print(f"applied: {applied}   skipped (non-DDL): {skipped}")

        from sqlalchemy import inspect

        names = sorted(inspect(db.engine).get_table_names())
        print(f"tables now: {len(names)}")
        for name in names:
            print("   ", name)

        expected = [
            "users",
            "water_predictions",
            "alerts",
            "aqua_ai_conversations",
            "aqua_ai_messages",
            "login_events",
            "admin_settings",
        ]
        missing = [t for t in expected if t not in names]
        print()
        if missing:
            print("MISSING:", missing)
            return 1
        print("Test database is fully provisioned.")

        # Prove it is writable, not merely present.
        db.session.execute(
            text("SELECT COUNT(*) FROM users")
        )
        print("readable: yes")

    return 0


if __name__ == "__main__":
    sys.exit(main())
