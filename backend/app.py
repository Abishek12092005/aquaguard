"""AquaGuard AI — Flask backend entrypoint.

    python app.py

This is a thin bootstrap around the application factory in `app/__init__.py`.
It exists so the conventional `python app.py` works, while the real wiring stays
in the package where tests and WSGI servers can import it too.

For anything beyond local development use a WSGI server instead of the built-in
one:

    waitress-serve --port=5000 app:app        (Windows)
    gunicorn -w 4 -b 0.0.0.0:5000 app:app     (Linux / macOS)
"""

import os
import sys

from dotenv import load_dotenv

# Load .env before importing the app, so configuration is resolved from the
# environment rather than from defaults.
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from app import create_app  # noqa: E402  (must follow load_dotenv)

app = create_app(os.getenv("FLASK_ENV", "development"))


def _startup_report() -> None:
    """Print what was configured, without printing any secret value."""
    config = app.config
    database = config["SQLALCHEMY_DATABASE_URI"]
    # Strip the password before it can reach a terminal or a log file.
    safe_database = database
    if "://" in database and "@" in database:
        scheme, rest = database.split("://", 1)
        credentials, host = rest.split("@", 1)
        safe_database = f"{scheme}://{credentials.split(':', 1)[0]}:***@{host}"

    checks = [
        ("Environment", config.get("ENV", "development")),
        ("Database", safe_database),
        ("CORS origins", ", ".join(config.get("CORS_ORIGINS", [])) or "none"),
        ("JWT secret", "set" if config.get("JWT_SECRET_KEY") else "MISSING"),
        ("Aqua AI key", "set" if config.get("AI_API_KEY") else "not configured"),
    ]

    print("\n  AquaGuard AI backend")
    print("  " + "-" * 56)
    for label, value in checks:
        print(f"  {label:<14} {value}")
    print("  " + "-" * 56)
    print(f"  Health         http://127.0.0.1:{os.getenv('FLASK_PORT', '5000')}/api/health")
    print(f"  Database       http://127.0.0.1:{os.getenv('FLASK_PORT', '5000')}/api/health/db\n")


def main() -> int:
    host = os.getenv("FLASK_HOST", "127.0.0.1")
    port = int(os.getenv("FLASK_PORT", "5000"))
    debug = str(os.getenv("DEBUG", "true")).lower() in {"1", "true", "yes", "on"}

    _startup_report()
    # use_reloader is off in debug mode here: the reloader spawns a second
    # process, which makes startup output confusing and doubles every side
    # effect. Turn it on explicitly if you want hot reload.
    app.run(host=host, port=port, debug=debug, use_reloader=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
