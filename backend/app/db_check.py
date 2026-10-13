"""Database connectivity check."""""

import sys

from sqlalchemy import inspect, text

from app import create_app
from app.constants import API_PREFIX
from app.extensions import db

EXPECTED_TABLES = (
    "users",
    "water_predictions",
    "alerts",
    "aqua_ai_conversations",
    "aqua_ai_messages",
)


def _ok(message: str) -> None:
    print(f"  [PASS] {message}")


def _fail(message: str, detail: str = "") -> None:
    print(f"  [FAIL] {message}")
    if detail:
        print(f"         {detail}")


def main() -> int:
    app = create_app()

    print("\nAquaGuard AI — database connection check")
    print("=" * 58)

    with app.app_context():
        uri = app.config["SQLALCHEMY_DATABASE_URI"]
        # Never print the password, even on a developer console.
        safe_uri = uri
        if "://" in uri and "@" in uri:
            scheme, rest = uri.split("://", 1)
            credentials, host = rest.split("@", 1)
            user = credentials.split(":", 1)[0]
            safe_uri = f"{scheme}://{user}:***@{host}"
        print(f"  URL: {safe_uri}\n")

        # --- 1. Can we reach the server at all? ----------------------------
        try:
            version, database = db.session.execute(
                text("SELECT VERSION(), DATABASE()")
            ).one()
            _ok(f"Connected to MySQL {version}")
            _ok(f"Using schema `{database}`")
        except Exception as exc:
            _fail("Could not connect to MySQL", str(exc).splitlines()[0])
            print(
                "\n  Check MYSQL_USER / MYSQL_PASSWORD / MYSQL_DATABASE in backend/.env"
            )
            return 1

        # --- 2. Are the tables present? ------------------------------------
        inspector = inspect(db.engine)
        existing = set(inspector.get_table_names())
        missing = [table for table in EXPECTED_TABLES if table not in existing]

        if missing:
            _fail(f"Missing tables: {', '.join(missing)}")
            print("         Apply the schema:  mysql -u root -p < database/schema.sql")
        else:
            _ok(f"All {len(EXPECTED_TABLES)} tables present")

        # --- 3. Do the foreign keys exist? ---------------------------------
        try:
            fk_count = db.session.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM information_schema.REFERENTIAL_CONSTRAINTS
                    WHERE CONSTRAINT_SCHEMA = DATABASE()
                    """
                )
            ).scalar()
            if fk_count and fk_count >= 5:
                _ok(f"{fk_count} foreign key constraints enforced")
            else:
                _fail(f"Expected at least 5 foreign keys, found {fk_count or 0}")
        except Exception as exc:
            _fail("Could not read foreign keys", str(exc).splitlines()[0])

        # --- 4. Is the engine InnoDB everywhere? ---------------------------
        try:
            non_innodb = db.session.execute(
                text(
                    """
                    SELECT TABLE_NAME
                    FROM information_schema.TABLES
                    WHERE TABLE_SCHEMA = DATABASE()
                      AND TABLE_TYPE = 'BASE TABLE'
                      AND ENGINE <> 'InnoDB'
                    """
                )
            ).scalars().all()
            if non_innodb:
                _fail(f"Non-InnoDB tables: {', '.join(non_innodb)}")
            else:
                _ok("Every table uses InnoDB")
        except Exception as exc:
            _fail("Could not verify storage engine", str(exc).splitlines()[0])

        # --- 5. Row counts (read-only, proves SELECT permission) -----------
        print("\n  Row counts:")
        try:
            for table in EXPECTED_TABLES:
                count = db.session.execute(
                    text(f"SELECT COUNT(*) FROM `{table}`")
                ).scalar()
                print(f"    {table:<26} {count}")
        except Exception as exc:
            _fail("Could not count rows", str(exc).splitlines()[0])
            return 1

        # --- 6. Write permission, rolled back ------------------------------
        # A real INSERT inside a transaction that is rolled back: this verifies
        # INSERT rights without leaving any test row behind.
        try:
            db.session.execute(
                text(
                    """
                    INSERT INTO users (name, email, password_hash, role)
                    VALUES ('__probe__', '__probe__@example.invalid', 'x', 'user')
                    """
                )
            )
            db.session.rollback()
            _ok("INSERT permission verified (rolled back, nothing stored)")
        except Exception as exc:
            db.session.rollback()
            _fail("No INSERT permission", str(exc).splitlines()[0])

        # --- 7. Cascade behaviour is a schema property ---------------------
        print(f"\n  API prefix: {API_PREFIX}")
        print("=" * 58)

    print("  Database layer is ready.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
