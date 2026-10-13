"""Shared pytest fixtures."""

import pytest

from app import create_app

def _reset_shared_state(application) -> None:
    """Clear state that must not leak between tests.

    WHY THIS IS NEEDED. The test database is a REAL, SHARED MySQL database - not
    a fresh in-memory one per test - so anything a test writes persists into the
    next one. That is how a parameter-limit override set by one test made a later
    test see `ph.min == 6.5` when it expected the built-in `0.0`: the code was
    right and the second test was reading the first test's leftovers.

    Only SINGLETON configuration is cleared here. Accounts, predictions and
    alerts are deliberately left alone: tests create uniquely-named rows (see
    `make_account`, which appends a uuid), so they do not collide, and deleting
    them per test would be both slow and a way to make a failure harder to
    reproduce by hand afterwards.

    `admin_settings` is the one table with a fixed primary key that every test
    shares, so it is the one that has to be reset.

    THE ADMIN CONSOLE IS RESET TOO, and it has to be: the console's unlock is
    process state, not a row, so an unlock from one test would otherwise satisfy
    a later test that should have been refused — which is exactly the bug a
    console gate test exists to catch.
    """
    from sqlalchemy import text
    from app.extensions import db
    with application.app_context():
        from app.services.console_session import lock

        lock()
        try:
            # The single settings row. Removing it means the next read recreates
            # it with the code's defaults, which is the state a test expects.
            db.session.execute(text("DELETE FROM admin_settings"))
            db.session.commit()
        except Exception:  # noqa: BLE001 - a fresh database has no such table yet
            db.session.rollback()


def _prepare_test_database(application) -> None:
    """Prove the test database is usable, or fail with the fix.

    WHY THIS EXISTS AT ALL. Without a check here, a database problem does not
    fail at collection. It fails inside the first fixture that touches the
    database, surfacing as a 500 from whichever endpoint that test was
    exercising -- so the reader sees "the chat endpoint returned 500" and
    starts debugging the chat endpoint when the real problem is the database.

    A CONNECTION TIMEOUT IS SET EXPLICITLY. Without one, an unreachable host
    does not fail: it BLOCKS, and the suite appears to hang with no output.
    That was a real symptom here, and it is the worst failure mode because it
    gives the reader nothing to act on.
    """
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import OperationalError, ProgrammingError, SQLAlchemyError
    from sqlalchemy.pool import NullPool

    uri = application.config.get("SQLALCHEMY_DATABASE_URI", "")
    # `connect_timeout` is a PyMySQL argument; passing it to a SQLite connection
    # (which several self-contained test modules use) raises TypeError on
    # pysqlite2/dbapi2's Connection(), turning "the suite can run anywhere" into
    # "the suite can only run against MySQL". Applied only when the URL is a
    # MySQL one; SQLite fails fast on a bad path by itself, so the bound it
    # guarded is not needed there.
    connect_args = {"connect_timeout": 5} if uri.startswith("mysql") else {}
    engine = create_engine(uri, poolclass=NullPool, connect_args=connect_args)

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            _assert_schema_matches_models(connection)
    except (OperationalError, ProgrammingError) as exc:
        detail = str(getattr(exc, "orig", exc))[:200]
        raise RuntimeError(
            f"Test database unavailable: {detail}"
            + "\n\n"
            + "  Create it and grant access (one time, as a MySQL administrator):\n"
            + "\n"
            + "    powershell -ExecutionPolicy Bypass -File database/provision_test_db.ps1\n"
            + "\n"
            + "  That script creates aquaguard_db_test, applies schema.sql and\n"
            + "  grants the application account access to it. It prompts for the\n"
            + "  MySQL root password and never writes it anywhere.\n"
        ) from None
    except SQLAlchemyError as exc:
        # Anything else -- a bad driver, a malformed URI -- is reported as
        # itself. It is not a missing database and must not be disguised as one.
        raise RuntimeError(f"Test database misconfigured: {exc}") from None
    finally:
        engine.dispose()

    print(f"[conftest] test database ready: {uri.split('?')[0].rsplit('/', 1)[-1]}")


def _assert_schema_matches_models(connection) -> None:
    """Fail with the FIX when the test database is missing a model's columns.

    WHY THIS IS CHECKED HERE. `schema.sql` uses `CREATE TABLE IF NOT EXISTS`, so
    it never adds a column to a table that already exists. A test database that
    was created before a column was added to a model therefore drifts silently,
    and the suite answers with a wall of "Unknown column 'users.reset_code_hash'"
    500s from unrelated endpoints -- which sends the reader to debug the wrong
    thing entirely.

    Detecting it once, up front, turns that into one message naming the fix.
    The check is against the SAME metadata the application uses, so it cannot
    disagree with the models.
    """
    from sqlalchemy import inspect
    from app.extensions import db
    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())
    missing: list[str] = []

    for table in db.metadata.sorted_tables:
        if table.name not in existing_tables:
            # A wholly missing table is the fresh-database case, handled elsewhere.
            continue
        live = {column["name"] for column in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name not in live:
                missing.append(f"{table.name}.{column.name}")

    if missing:
        raise RuntimeError(
            "Test database schema is out of date -- it is missing: "
            + ", ".join(missing)
            + "\n\n"
            + "  Bring it up to date (one time, as a MySQL administrator):\n"
            + "\n"
            + "    powershell -ExecutionPolicy Bypass -File database/provision_test_db.ps1\n"
            + "\n"
            + "  That script re-applies the schema AND runs the additive column\n"
            + "  migrations, so it repairs a database that predates a new column.\n"
        )

@pytest.fixture(autouse=True)
def _isolate_shared_config(app):
    """Reset shared singleton config before every test that uses the app.

    Autouse, and depending on `app`, so it runs for every test in any module that
    takes the application fixture - without each test having to remember. It
    resetting the settings row is what stops a parameter-limit override set by
    one test from being read as the default by the next.
    """
    _reset_shared_state(app)
    yield


@pytest.fixture(scope="session")
def app():
    """A test-configured application instance.

    SKIPS rather than errors when the test database is unavailable. A missing
    database is an environment problem, not a failure of the code under test,
    and pytest reports the two very differently: a skip is visibly "not run",
    whereas 36 ERRORs read as 36 broken endpoints.

    The skip message carries the exact provisioning command, so the fix is one
    copy-paste away rather than a search through the suite.
    """
    application = create_app("testing")
    try:
        _prepare_test_database(application)
    except RuntimeError as exc:
        pytest.skip(str(exc))
    return application


@pytest.fixture()
def unlock_console(app, client):
    """Return a callable that unlocks the admin console.

    THE CONSOLE'S ONLY GATE IS ITS OWN CREDENTIAL, and opening it properly takes
    two steps — prove the password, then confirm the mail it sends. A test cannot
    wait for a mailbox, so this opens the window directly through the same service
    `POST /api/admin/session/confirm` calls. Everything downstream is then
    exercised exactly as a real unlock would leave it.

    Returned as a CALLABLE rather than a fixture that unlocks globally, because
    the unlock is state on the running process: a fixture that unlocked once would
    leak into every later test and hide a route that forgot to check it.
    """
    def _unlock(headers: dict | None = None) -> dict:
        with app.app_context():
            from app.services.console_session import unlock

            unlock()
        return headers or {}

    return _unlock


@pytest.fixture()
def client(app):
    """A Flask test client."""
    return app.test_client()


@pytest.fixture()
def app_context(app):
    """Push an application context for service/model level tests."""
    with app.app_context():
        yield app


def make_test_account(label="u", role="user"):
    """Create a `User` row directly and return (id, name, email).

    THE APPLICATION HAS NO REGISTRATION, so a test cannot obtain an account by
    POSTing to an endpoint any more. Tests that need to distinguish one caller
    from another create the row here instead.

    This is also the ONLY way to get an account that is NOT the shared visitor:
    `app.services.identity` hands every unauthenticated request to one shared
    account, so two "different" browsers would otherwise be the same owner and
    any test about row isolation would pass for the wrong reason.
    """
    import uuid
    from app.extensions import db
    from app.extensions import bcrypt
    from app.models import User

    email = f"{label}_{uuid.uuid4().hex[:10]}@aquaguard.test"
    user = User(
        name=f"Test {label}",
        email=email,
        password_hash=bcrypt.generate_password_hash("SecurePass123").decode("utf-8"),
        role=role,
    )
    db.session.add(user)
    db.session.commit()
    return user.id, user.name, user.email


def headers_for(user_id):
    """Bearer headers that act AS this account.

    There is no login endpoint left to exchange a password for, so a test that
    needs two DISTINCT owners mints the token itself. This is test-only
    scaffolding: production issues no user tokens at all, because the application
    has no user login.
    """
    from flask_jwt_extended import create_access_token

    return {"Authorization": f"Bearer {create_access_token(identity=str(user_id))}"}
