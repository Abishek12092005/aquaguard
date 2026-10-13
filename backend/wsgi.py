"""Production WSGI entrypoint.

    gunicorn -c gunicorn.conf.py wsgi:app          (Linux / macOS)
    waitress-serve --port=5000 wsgi:app            (Windows)

`wsgi:app` is the object every WSGI server discovers, so the same module serves
gunicorn, uWSGI and waitress without change.

Why this exists separately from `app.py`:

  * `app.py` is the developer entrypoint. It loads `.env`, prints a startup
    report and runs Flask's built-in server, which is single-threaded, not
    hardened, and explicitly not for production.

  * This module assumes configuration comes from the real environment (set by
    systemd, Docker, Kubernetes, a PaaS dashboard). It still reads `.env` when
    one is present, so a single-host deploy can use one, but nothing here
    *requires* a file on disk — a container with secrets injected as environment
    variables needs no writable filesystem.

  * The config name is forced to "production" unless FLASK_ENV says otherwise,
    so deploying this module cannot accidentally serve with development settings
    (debug tracebacks, the fallback signing key).

Any misconfiguration raises at import time, which is deliberate: a WSGI server
that fails to boot is obvious, whereas a server that boots with a placeholder
signing key fails silently and remotely.
"""

import logging
import os
import sys

# Resolve .env relative to THIS file, not the process working directory, so the
# entrypoint behaves the same whether the server is started from the project root
# or from a systemd unit with a different WorkingDirectory.
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    from dotenv import load_dotenv

    # Loaded without override, so real environment variables win. A deploy that
    # sets SECRET_KEY in the environment must not have it replaced by whatever
    # happens to be sitting in a file left over from development.
    load_dotenv(os.path.join(_BACKEND_DIR, ".env"), override=False)
except ImportError:  # pragma: no cover - dotenv is optional at runtime
    # Missing python-dotenv is only fatal if there is no .env AND no environment
    # configuration, which the config layer reports with a precise message.
    pass

from app import create_app  # noqa: E402  (must follow load_dotenv)

# Any value other than an explicit "development"/"testing" resolves to
# production. Defaulting the other way would mean a deploy that forgot to set
# FLASK_ENV runs with debug on and a known signing key.
_config_name = os.getenv("FLASK_ENV", "production")
if _config_name not in ("production", "development", "testing"):
    _config_name = "production"

app = create_app(_config_name)

# --- Logging ---------------------------------------------------------------
# A WSGI server captures stdout/stderr; configuring the root logger here means
# application logs are formatted consistently in that stream rather than falling
# back to the server's own default.
logging.basicConfig(
    level=app.config.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    stream=sys.stdout,
)

# --- Startup banner --------------------------------------------------------
# Reports what was configured WITHOUT printing any secret: the presence of a
# value, never the value. Confirms at a glance that the deployment picked up its
# database, its CORS origins and its provider key.
_database = app.config["SQLALCHEMY_DATABASE_URI"]
_safe_database = _database
if "://" in _database and "@" in _database:
    _scheme, _rest = _database.split("://", 1)
    _credentials, _host = _rest.split("@", 1)
    _safe_database = f"{_scheme}://{_credentials.split(':', 1)[0]}:***@{_host}"

print("  AquaGuard AI — production WSGI entrypoint")
print("  " + "-" * 58)
print(f"  Environment    {app.config.get('ENV')}")
print(f"  Debug          {app.config.get('DEBUG')}")
print(f"  Database       {_safe_database}")
print(f"  CORS origins   {', '.join(app.config.get('CORS_ORIGINS', [])) or 'none'}")
print(f"  JWT secret     {'set' if app.config.get('JWT_SECRET_KEY') else 'MISSING'}")
print(f"  Aqua AI        {'configured' if app.config.get('AI_API_KEY') else 'not configured'}")
print("  " + "-" * 58, flush=True)


if __name__ == "__main__":
    # Running this file directly is a convenience for a quick smoke test on a
    # host without gunicorn/waitress installed. It is NOT the production path:
    # the output says so, so nobody mistakes it for one.
    host = os.getenv("FLASK_HOST", "0.0.0.0")
    port = int(os.getenv("FLASK_PORT", "5000"))
    print(
        "  NOTE: this is the built-in Flask server, for a smoke test only.\n"
        "        For production use:  gunicorn -c gunicorn.conf.py wsgi:app\n"
        "                        or: waitress-serve --port=%d wsgi:app\n" % port,
        flush=True,
    )
    app.run(host=host, port=port, debug=False, use_reloader=False)
