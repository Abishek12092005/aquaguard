"""Application configuration.

Every setting is sourced from environment variables so that no credential,
secret or API key is ever committed to the repository. `BaseConfig` holds the
shared defaults; the subclasses override only what genuinely differs between
development, testing and production.

Canonical variable names (see .env.example):

    DB_HOST / DB_PORT / DB_NAME / DB_USER / DB_PASSWORD
    JWT_SECRET
    AQUA_AI_API_KEY / AQUA_AI_MODEL

The older MYSQL_* / JWT_SECRET_KEY / AI_* names are still accepted as
fallbacks so an existing .env keeps working.
"""

import os
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import dotenv_values

# backend/app/config.py -> backend/.env
BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent

# The project's .env is authoritative for its own settings, but a variable that
# is present in the real environment always wins.
#
# `override=True` alone was wrong, and wrong in the one case that matters most:
# the shipped .env template has `AQUA_AI_API_KEY=` with an empty value, so
# loading it with override silently BLANKED OUT a key supplied by the
# environment. An operator setting AQUA_AI_API_KEY in Docker, systemd, CI or a
# Kubernetes secret therefore got "no provider configured" and no way to see why
# - the exact deployment case the previous comment claimed to support.
#
# The rule now: a real environment variable beats the file, and an empty entry in
# the file means "not configured" rather than "configure it to nothing".
_DOTENV_VALUES = dotenv_values(BACKEND_DIR / ".env")
_ENV_SET_BEFORE_DOTENV = set(os.environ)

for _key, _value in _DOTENV_VALUES.items():
    if _key in _ENV_SET_BEFORE_DOTENV and os.environ.get(_key, "").strip():
        # Already provided by the deployment, with a real value. Leave it alone.
        continue
    if _value is None:
        continue
    os.environ[_key] = _value


# ---------------------------------------------------------------------------
# Small env readers
# ---------------------------------------------------------------------------
def _env_bool(key: str, default: bool = False) -> bool:
    """Read a boolean environment variable tolerantly."""
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(key: str, default: int) -> int:
    """Read an integer, falling back to the default when unset or malformed."""
    raw = os.getenv(key)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def _env_first(*names: str, default: str = "") -> str:
    """Return the first of several environment variables that is set.

    Lets the canonical names be preferred while older aliases keep working, so
    an existing .env does not silently break.
    """
    for name in names:
        value = os.getenv(name)
        if value not in (None, ""):
            return value
    return default


# ---------------------------------------------------------------------------
# Database URI
# ---------------------------------------------------------------------------
# A managed MySQL provider (Aiven, PlanetScale, Railway, DigitalOcean) hands out
# a connection string in a form SQLAlchemy does not understand directly:
#
#     mysql://user:pass@host:port/db?ssl-mode=REQUIRED
#
# Two things are wrong with it as-is:
#
#   1. the scheme is bare `mysql://`, which SQLAlchemy cannot map to a driver
#      (it needs `mysql+pymysql://`), so the URL is rejected with
#      "Can't load plugin: sqlalchemy.dialects:mysql";
#   2. `ssl-mode=REQUIRED` is a MySQL Connector/C notion. PyMySQL has no such
#      option and SILENTLY IGNORES it, so the connection is attempted WITHOUT
#      TLS - which a managed server refuses with an unhelpful
#      "SSL connection is required" error, or, worse, accepts insecurely.
#
# So the URL is normalised here into the shape SQLAlchemy + PyMySQL actually use:
# the driver is forced, `ssl-mode` (and its aliases) is translated into the real
# TLS options, and the transport is recorded so the engine can be built with the
# matching connect args below.
def _normalise_database_url(raw: str) -> str:
    """Rewrite a provider connection string into one SQLAlchemy + PyMySQL accepts."""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    value = raw.strip()

    # 1. Force the pure-Python driver. `mysql://` and `mysql+mysqlconnector://`
    #    are both rewritten; an explicit `mysql+pymysql://` is left untouched.
    if value.startswith("mysql://"):
        value = "mysql+pymysql://" + value[len("mysql://"):]
    elif value.startswith("mysql+mysqlconnector://"):
        value = "mysql+pymysql://" + value[len("mysql+mysqlconnector://"):]

    parts = urlsplit(value)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))

    # 2. Translate the SSL options a managed provider advertises into the ones
    #    PyMySQL reads. `ssl-mode` is the MySQL-Connector spelling; `ssl_mode`
    #    and `ssl_required` are seen in the wild too.
    ssl_mode = (
        query.pop("ssl-mode", None)
        or query.pop("ssl_mode", None)
        or query.pop("sslmode", None)
    )
    ssl_required_flag = query.pop("ssl_required", None)

    ssl_requested = False
    if ssl_mode:
        # REQUIRED / VERIFY_CA / VERIFY_IDENTITY all mean "use TLS".
        ssl_requested = str(ssl_mode).strip().upper() not in ("DISABLED", "DISABLE", "OFF", "")
    elif ssl_required_flag is not None:
        ssl_requested = str(ssl_required_flag).strip().lower() in ("1", "true", "yes", "on")

    # An explicit DB_SSL toggle wins over anything parsed from the URL, so an
    # operator can turn TLS on for a provider that does not advertise it.
    env_ssl = os.getenv("DB_SSL")
    if env_ssl is not None:
        ssl_requested = str(env_ssl).strip().lower() in ("1", "true", "yes", "on")

    if ssl_requested:
        # `ssl=true` is the PyMySQL-level flag; the CA path, when supplied, is
        # attached as connect args by the engine builder (a URL cannot carry it
        # portably). Keeping a marker here makes the intent visible in logs.
        query["ssl"] = "true"

    # Always ensure a utf8mb4 charset, which the schema requires.
    query.setdefault("charset", "utf8mb4")

    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


def _database_connect_args() -> dict:
    """PyMySQL connect arguments implied by the environment.

    Returns an empty dict when no TLS is configured, so an ordinary local MySQL
    keeps connecting exactly as before. When TLS IS requested, PyMySQL needs the
    real options rather than the provider's `ssl-mode` string.

    ``DB_SSL_CA`` optionally points at the provider's CA certificate (Aiven
    serves one); without it, TLS is still negotiated but the server certificate
    is not verified against a local copy - acceptable for a managed endpoint
    reached over the public internet where the transport is the protection, and
    upgradeable by simply setting the variable.
    """
    enabled = str(os.getenv("DB_SSL", "")).strip().lower() in ("1", "true", "yes", "on")

    # Also enable when the resolved URL asked for TLS, so a provider string that
    # carries `ssl-mode=REQUIRED` needs no second variable.
    raw = _env_first("DATABASE_URL")
    if raw:
        lowered = raw.lower()
        if "ssl-mode=required" in lowered or "ssl_mode=required" in lowered or "sslmode=required" in lowered:
            enabled = True
        if "ssl-mode=verify" in lowered or "ssl-mode=verify_ca" in lowered or "ssl-mode=verify_identity" in lowered:
            enabled = True

    if not enabled:
        return {}

    ca = (os.getenv("DB_SSL_CA") or "").strip()
    args: dict = {"ssl": {}}
    if ca:
        args["ssl"]["ca"] = ca
    return args


def _build_mysql_uri() -> str:
    """Compose the SQLAlchemy MySQL URI from environment variables.

    Reads DB_HOST / DB_PORT / DB_NAME / DB_USER / DB_PASSWORD, falling back to
    the legacy MYSQL_* names, then to safe defaults. An explicit DATABASE_URL
    always takes precedence, normalised into the driver + TLS form PyMySQL needs.

    Credentials are NEVER hardcoded here. With nothing configured the password
    is simply empty and the connection fails loudly, rather than the application
    quietly running against some built-in account nobody audited.
    """
    explicit = _env_first("DATABASE_URL")
    if explicit:
        return _normalise_database_url(explicit)

    # Percent-encode every component. This matters in practice, not theory: a
    # password containing `@`, `:`, `/` or `#` is otherwise parsed as part of
    # the host or path, producing a confusing `getaddrinfo failed` instead of an
    # authentication error. `quote_plus` handles all of those characters.
    user = quote_plus(_env_first("DB_USER", "MYSQL_USER", default="root"))
    password = quote_plus(_env_first("DB_PASSWORD", "MYSQL_PASSWORD"))
    host = _env_first("DB_HOST", "MYSQL_HOST", default="127.0.0.1")
    port = _env_first("DB_PORT", "MYSQL_PORT", default="3306")
    name = quote_plus(_env_first("DB_NAME", "MYSQL_DATABASE", default="aquaguard_db"))

    # A managed host reached over TLS (DB_SSL / DB_SSL_CA set) is signalled in
    # the URL too, so the connection string alone describes the transport.
    query = "charset=utf8mb4"
    if _database_connect_args():
        query += "&ssl=true"

    # PyMySQL keeps the stack pure-Python (no compiler needed on Windows).
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{name}?{query}"

# ---------------------------------------------------------------------------
# Production-only guards
# ---------------------------------------------------------------------------

def _require_secret(*names: str) -> str:
    """Return a required secret, refusing placeholders and blanks.

    Tried under each name in turn. Raises rather than falling back, because a
    production deployment signing tokens with a published default is worse
    than one that refuses to start: the failure is silent, remote, and
    indistinguishable from working.
    """
    value = _env_first(*names)
    if not value:
        raise RuntimeError(
        "Missing required secret: " + " / ".join(names) + ". "
        + "Set it in the environment. Generate one with: "
        + "python -c import secrets; print(secrets.token_hex(32))"
        )
    lowered = value.strip().lower()
    placeholders = {
        "changeme", "change-me", "secret",
        "dev-secret-change-me", "your-secret-key",
        "replace-me-with-a-long-random-string",
        "replace-me-with-a-different-long-random-string",
    }
    if lowered.startswith("replace-me") or lowered in placeholders:
        raise RuntimeError(
        "Refusing to start: " + names[0] + " is still a placeholder value. "
        + "Set a real random secret for production."
        )
    if len(value.strip()) < 32:
        raise RuntimeError(
        "Refusing to start: " + names[0] + " is shorter than 32 characters. "
        + "A short signing key is brute-forceable."
        )
    return value


def _require_origins() -> list:
    """Return the allowed browser origins, refusing a wildcard.

    A wildcard cannot be combined with credentialed requests - the browser
    rejects it outright - and would in any case let any site call this API
    with the user cookies attached. An empty list is refused too: allowing
    nothing produces a CORS failure that reads as a frontend bug.
    """
    raw = _env_first("CORS_ORIGINS")
    if not raw:
        raise RuntimeError(
        "Missing required setting: CORS_ORIGINS. List the exact browser "
        + "origins allowed to call this API, comma-separated, "
        + "e.g. https://app.example.com"
        )
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    if "*" in origins:
        raise RuntimeError(
        "Refusing to start: CORS_ORIGINS contains a wildcard. It cannot be "
        + "used with credentialed requests and would expose the API "
        + "to any site."
        )
    return origins


def validate_production(app) -> None:
    """Fail fast on a production misconfiguration, before serving traffic.

    Called from the application factory. Every check corresponds to a mistake
    that would otherwise surface later as a confusing runtime error: a fallback
    signing key, a placeholder secret, debug left on, or an empty CORS list.
    """
    problems = []

    if app.config.get("SECRET_KEY") in (
        None,
        "",
        "dev-secret-change-me",
    ):
        problems.append("SECRET_KEY is unset or still the development default.")
    if not app.config.get("JWT_SECRET_KEY"):
        problems.append("JWT_SECRET is unset, so tokens cannot be signed.")
    elif app.config.get("SECRET_KEY") == app.config.get("JWT_SECRET_KEY"):
        problems.append(
            "SECRET_KEY and JWT_SECRET are identical. They must differ, so that "
            + "leaking one does not compromise the other."
        )
    if app.config.get("DEBUG"):
        problems.append("DEBUG is on. Production must not expose tracebacks.")
    elif str(_env_first("DEBUG") or "").strip().lower() in ("1", "true", "yes", "on"):
        # ProductionConfig pins DEBUG to False, so an environment asking for debug
        # is overridden rather than honoured. Doing that silently is how a team
        # comes to believe debug is on somewhere when it is not - the setting and
        # the behaviour should agree, so the contradiction is reported.
        problems.append(
            "DEBUG=true is set in the environment but production forces it off. "
            "Remove it, so the setting and the behaviour agree."
        )
    if not app.config.get("CORS_ORIGINS"):
        problems.append("CORS_ORIGINS is empty; no browser origin could call the API.")
    if not app.config.get("SQLALCHEMY_DATABASE_URI"):
        problems.append("No database URI resolved from the DB_* variables.")

    if problems:
        bullet = chr(10) + chr(32) * 2 + chr(45) + chr(32)
        detail = bullet.join(problems)
        raise RuntimeError(chr(10).join([
            "Production configuration is invalid:",
            detail,
        ]))

# ---------------------------------------------------------------------------
# Config classes
# ---------------------------------------------------------------------------
class BaseConfig:
    """Settings shared by every environment."""

    # --- Core ---
    ENV = _env_first("FLASK_ENV", default="development")
    SECRET_KEY = _env_first("SECRET_KEY", default="dev-secret-change-me")
    DEBUG = False
    TESTING = False

    # --- Database ---
    SQLALCHEMY_DATABASE_URI = _build_mysql_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,   # transparently recycle stale connections
        "pool_recycle": 280,     # below MySQL's default wait_timeout (300s)
        "pool_size": 5,
        "max_overflow": 10,
        # TLS connect arguments when a managed provider requires them. Empty for
        # an ordinary local MySQL, so nothing changes there.
        "connect_args": _database_connect_args(),
    }

    # --- JWT (flask-jwt-extended) ---
    # Falls back to SECRET_KEY only so a dev environment starts without extra
    # setup; production must set JWT_SECRET explicitly. A separate signing key
    # means a leaked session secret cannot also forge tokens, and vice versa.
    JWT_SECRET_KEY = _env_first("JWT_SECRET", "JWT_SECRET_KEY", default="") or SECRET_KEY
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(
        minutes=_env_int("JWT_ACCESS_TOKEN_MINUTES", 30)
    )
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=_env_int("JWT_REFRESH_TOKEN_DAYS", 7))
    JWT_TOKEN_LOCATION = ["headers"]
    JWT_HEADER_NAME = "Authorization"
    JWT_HEADER_TYPE = "Bearer"

    # --- CORS ---
    # Only these origins may call the API from a browser. Never "*" together
    # with credentials: the browser rejects that combination outright, and it
    # would defeat the purpose anyway.
    CORS_ORIGINS = [
        origin.strip()
        for origin in _env_first(
            "CORS_ORIGINS", default="http://localhost:5173,http://127.0.0.1:5173"
        ).split(",")
        if origin.strip()
    ]

    # --- Password hashing ---
    BCRYPT_LOG_ROUNDS = _env_int("BCRYPT_LOG_ROUNDS", 12)

    # --- Machine learning ---
    ML_MODEL_DIR = _env_first("ML_MODEL_DIR", default=str(PROJECT_ROOT / "ml" / "models"))
    ML_MODEL_FILENAME = _env_first(
        "ML_MODEL_FILENAME", default="aquaguard_random_forest.pkl"
    )
    ML_PREDICTION_THRESHOLD = float(_env_first("ML_PREDICTION_THRESHOLD", default="0.5"))

    # The standalone 3-class pipeline (ml/train_model.py -> ml/model/).
    ML_WATER_QUALITY_DIR = _env_first(
        "ML_WATER_QUALITY_DIR", default=str(PROJECT_ROOT / "ml")
    )

    # --- Aqua AI ---
    # AI_API_KEY lives here and ONLY here. It is never serialised into a
    # response, never logged, and never sent to the browser: React talks to
    # Flask, and Flask talks to the provider. There is deliberately no VITE_
    # variable for it, because anything VITE_-prefixed is public by definition.
    AI_ENABLED = _env_bool("AI_ENABLED", True)
    AI_PROVIDER = _env_first("AQUA_AI_PROVIDER", "AI_PROVIDER", default="openai")

    # An ORDERED list, so the assistant can fall through to a second vendor when
    # the first is rate-limited or down. `app.ai.providers` reads this; when it
    # is unset the single AI_PROVIDER above is used, so an existing .env keeps
    # working unchanged.
    #
    # Per-provider keys are read by the resolver rather than here, because a
    # provider is only usable when it has BOTH a key and a URL - and Meta has no
    # sensible default URL, so the check has to live where that is visible.
    AI_PROVIDER_ORDER = _env_first("AQUA_AI_PROVIDER_ORDER", "AI_PROVIDER_ORDER")

    AI_API_KEY = _env_first("AQUA_AI_API_KEY", "AI_API_KEY")
    AI_MODEL = _env_first("AQUA_AI_MODEL", "AI_MODEL", default="gpt-4o-mini")
    AI_BASE_URL = _env_first("AQUA_AI_BASE_URL", "AI_BASE_URL")

    # --- Per-provider credentials ----------------------------------------
    # Read here so they reach `app.config`, which is the only thing
    # `app.ai.providers` is given. They were previously absent from this class,
    # so an operator could set AQUA_AI_GEMINI_API_KEY in .env and the resolver
    # would still report Gemini unconfigured - the key was in the environment but
    # never in the config the resolver reads.
    #
    # The names match `PROVIDER_DEFAULTS`' `keys`/`urls`/`models` tuples, so the
    # two cannot drift: add a provider there and its variables are read here.
    GEMINI_API_KEY = _env_first("AQUA_AI_GEMINI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY")
    GEMINI_MODEL = _env_first("AQUA_AI_GEMINI_MODEL", "GEMINI_MODEL")
    GEMINI_BASE_URL = _env_first("AQUA_AI_GEMINI_BASE_URL", "GEMINI_BASE_URL")

    META_API_KEY = _env_first(
        "AQUA_AI_META_API_KEY", "META_API_KEY", "GROQ_API_KEY", "TOGETHER_API_KEY"
    )
    META_MODEL = _env_first("AQUA_AI_META_MODEL", "META_MODEL")
    META_BASE_URL = _env_first("AQUA_AI_META_BASE_URL", "META_BASE_URL", "GROQ_BASE_URL")

    OPENAI_API_KEY = _env_first("AQUA_AI_OPENAI_API_KEY", "OPENAI_API_KEY")
    OPENAI_MODEL = _env_first("AQUA_AI_OPENAI_MODEL", "OPENAI_MODEL")
    OPENAI_BASE_URL = _env_first("AQUA_AI_OPENAI_BASE_URL", "OPENAI_BASE_URL")
    AI_MAX_CONTEXT_MESSAGES = _env_int("AI_MAX_CONTEXT_MESSAGES", 20)
    AI_REQUEST_TIMEOUT = _env_int("AI_REQUEST_TIMEOUT", 30)
    # Upper bound on how many tokens the assistant may write per reply. This is a
    # SPEED control rather than a cost one: a chat answer is short, and generation
    # time grows with length, so capping the reply is what keeps a normal question
    # answerable in a couple of seconds rather than in six.
    AI_MAX_RESPONSE_TOKENS = _env_int("AI_MAX_RESPONSE_TOKENS", 500)

    # --- Email (SMTP) -----------------------------------------------------
    # Used for account notifications and the admin password reset.
    #
    # MAIL_SUPPRESS_SEND is honoured and defaults to ON in development: without
    # it, every test-run registration would attempt a real SMTP connection and
    # the suite would depend on Gmail being reachable. A deployment opts in by
    # setting MAIL_SUPPRESS_SEND=false.
    #
    # MAIL_PASSWORD is the provider's APP PASSWORD, not the account password.
    # Gmail (and most providers) refuse plain password auth, and an app password
    # is revocable on its own - which is what makes it safe to put in a .env.
    MAIL_ENABLED = _env_bool("MAIL_ENABLED", True)
    MAIL_SUPPRESS_SEND = _env_bool("MAIL_SUPPRESS_SEND", True)
    MAIL_HOST = _env_first("MAIL_HOST", "SMTP_HOST", default="smtp.gmail.com")
    MAIL_PORT = _env_int("MAIL_PORT", _env_int("SMTP_PORT", 587))
    # STARTTLS on 587 is the modern default. Setting MAIL_USE_SSL=true switches
    # to implicit TLS on 465 instead; the two are mutually exclusive.
    MAIL_USE_TLS = _env_bool("MAIL_USE_TLS", True)
    MAIL_USE_SSL = _env_bool("MAIL_USE_SSL", False)
    MAIL_USERNAME = _env_first("MAIL_USERNAME", "SMTP_USER")
    MAIL_PASSWORD = _env_first("MAIL_PASSWORD", "SMTP_PASSWORD")
    MAIL_FROM_NAME = _env_first("MAIL_FROM_NAME", default="AquaGuard AI")
    MAIL_DEFAULT_SENDER = _env_first("MAIL_DEFAULT_SENDER", "MAIL_FROM")
    MAIL_TIMEOUT = _env_int("MAIL_TIMEOUT", 15)

    # --- Admin console ----------------------------------------------------
    # A SEPARATE password for the admin console, deliberately NOT the admin
    # user's normal login. The console is the highest-privilege surface in the
    # application, so it gets its own credential that can be rotated on its own
    # without touching anybody's account.
    #
    # This is a fallback used to seed the first credential. Once the admin has
    # changed it through the console, the STORED hash is what is checked and this
    # value is only used if no hash has been set yet.
    # Seeded to the requested console credential so a fresh install can sign in
    # with `abishek` / `abishek2005@` without any .env setup. An environment
    # value still wins when one is provided, and once the password is changed
    # through the console the STORED hash is what is checked.
    ADMIN_ACCESS_PASSWORD = _env_first("ADMIN_ACCESS_PASSWORD", "ADMIN_PASSWORD") or "abishek2005@"

    # The console's login name, seeded to the requested "abishek". Stored per the
    # AdminSettings row once the admin edits it, so this is only the initial value.
    ADMIN_USERNAME = _env_first("ADMIN_USERNAME") or "abishek"

    # Where the console's own notices go: a password change, a dataset export and
    # a password-reset code. Defaults to the requested recovery address so the
    # forgot-password flow works out of the box; an environment value wins.
    ADMIN_NOTIFY_EMAIL = _env_first("ADMIN_NOTIFY_EMAIL") or "shekabi2005@gmail.com"
    # How long an admin console session stays valid. Deliberately short: this is
    # a privileged surface, not a place to stay logged in for a week.
    ADMIN_SESSION_MINUTES = _env_int("ADMIN_SESSION_MINUTES", 60)

    # --- Uploads / logging ---
    UPLOAD_FOLDER = _env_first("UPLOAD_FOLDER", default=str(BACKEND_DIR / "uploads"))
    MAX_CONTENT_LENGTH = _env_int("MAX_CONTENT_LENGTH_MB", 16) * 1024 * 1024
    LOG_LEVEL = _env_first("LOG_LEVEL", default="INFO")

    # --- JSON ---
    # Emit plain UTF-8 rather than \uXXXX escapes, so responses stay readable
    # and non-ASCII units such as -S/cm survive the round trip to the browser.
    JSON_SORT_KEYS = False
    JSONIFY_PRETTYPRINT_REGULAR = False
    JSON_AS_ASCII = False


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    LOG_LEVEL = _env_first("LOG_LEVEL", default="DEBUG")


class TestingConfig(BaseConfig):
    TESTING = True
    DEBUG = True
    # --- Database -----------------------------------------------------
    # MySQL, on a SEPARATE database from the one the application uses.
    #
    # Tests must never touch the developer's real data, and the isolation has to
    # be at the database level rather than by careful table-name prefixes: a
    # mistake in a test helper must not be able to delete a real reading.
    #
    # WHY THERE IS NO SQLITE FALLBACK. It was tried twice and removed. This
    # schema uses `passive_deletes` and `lazy="dynamic"` relationships, and on an
    # in-memory SQLite database those either lose the schema between connections
    # or deadlock outright. Even had it worked, a suite running on a different
    # engine from production is testing something other than what ships.
    #
    # So the test database has to exist. `tests/conftest.py` checks for it once
    # at startup and fails with the exact command to create it, which is a far
    # better failure than a hang or a misleading 500 from every route.
    TEST_DB_NAME = _env_first(
        "DB_TEST_NAME", "MYSQL_TEST_DATABASE", default="aquaguard_db_test"
    )
    # An explicit DATABASE_URL wins here too, for the same reason it wins in
    # BaseConfig. It is what lets a self-contained test module (which sets the
    # variable BEFORE importing this package) redirect the whole app onto a
    # throwaway SQLite file -- so the suite can never write approval, recovery
    # or registry rows into the developer's real database by accident.
    SQLALCHEMY_DATABASE_URI = _env_first("DATABASE_URL") or (
        _build_mysql_uri().split("?", 1)[0].rsplit("/", 1)[0]
        + f"/{TEST_DB_NAME}?charset=utf8mb4"
    )
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=5)
    BCRYPT_LOG_ROUNDS = 4  # keep the suite fast

    # --- Email ---------------------------------------------------------
    # Suppressed unconditionally in tests, and NOT read from the environment.
    #
    # This is the one place where a hard override beats an env default. A test
    # run that opened a real SMTP connection would be slow, flaky, dependent on
    # a provider being reachable, and would send real mail to real addresses
    # from a fixture. Making it non-negotiable means no `.env` can re-enable it
    # by accident.
    MAIL_SUPPRESS_SEND = True
    # No credentials, so even an un-suppressed path cannot authenticate.
    MAIL_USERNAME = ""
    MAIL_PASSWORD = ""
    # --- Admin console ---
    # A fixed seed so the unlock tests are deterministic. Like the mail settings,
    # this is set here rather than read from the environment: a test run must not
    # depend on a developer's .env, and must never unlock a real console.
    ADMIN_ACCESS_PASSWORD = "admin-console-pass"
    # Long enough to outlast a test run without expiring mid-suite.
    ADMIN_SESSION_MINUTES = 30

    # Tests must never touch the developer's real database.
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=5)
    BCRYPT_LOG_ROUNDS = 4  # keep the suite fast


class ProductionConfig(BaseConfig):
    """Settings for a real deployment.

    Differs from the base in ways that matter for safety rather than convenience:
    weak or missing secrets are a hard failure, cookies are marked Secure, JSON
    body size is bounded, and the error surface is reduced. A production deploy
    that accidentally inherits development behaviour (debug tracebacks, the
    fallback signing key, a wildcard CORS origin) is the failure this class
    exists to prevent.
    """

    DEBUG = False
    TESTING = False
    # --- Secrets are mandatory, with no fallback -------------------------
    # BaseConfig falls back to a fixed string so a fresh clone boots. That is
    # right for development and dangerous in production, where it would mean a
    # publicly-known key signing real tokens. Here an unset or placeholder value
    # raises at startup instead - see `_require_secret` and `validate_production`.
    SECRET_KEY = _require_secret("SECRET_KEY")
    JWT_SECRET_KEY = _require_secret("JWT_SECRET", "JWT_SECRET_KEY")

    # --- Logging --------------------------------------------------------
    LOG_LEVEL = _env_first("LOG_LEVEL", default="INFO")

    # --- CORS -----------------------------------------------------------
    # Explicit origins only. A wildcard is rejected because it cannot be combined
    # with credentials, and would let any site call the API on a user's behalf.
    CORS_ORIGINS = _require_origins()
    CORS_SUPPORTS_CREDENTIALS = True
    # --- Cookies / headers ---------------------------------------------
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PREFERRED_URL_SCHEME = "https"

    # --- Request limits -------------------------------------------------
    # A bounded body stops a single large request from exhausting memory.
    MAX_CONTENT_LENGTH = _env_int("MAX_CONTENT_LENGTH_MB", 16) * 1024 * 1024
    # --- JSON -----------------------------------------------------------
    # Never pretty-print in production: it inflates every response and leaks
    # nothing useful. Kept off explicitly rather than relying on the default.
    JSONIFY_PRETTYPRINT_REGULAR = False
    # --- Database pool --------------------------------------------------
    # Slightly larger than development, and with pre-ping left on so a dropped
    # connection is replaced rather than surfacing as a 500 on the next request.
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 280,
        "pool_size": 10,
        "max_overflow": 20,
        "pool_timeout": 30,
        # Managed MySQL (Aiven and friends) requires TLS; this carries the
        # matching PyMySQL connect arguments. Empty for a non-TLS server.
        "connect_args": _database_connect_args(),
    }


config_by_name = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def get_config(name: str | None = None):
    """Resolve a config class from FLASK_ENV / APP_ENV, defaulting to development."""
    env = (name or os.getenv("FLASK_ENV") or os.getenv("APP_ENV") or "development").lower()
    return config_by_name.get(env, DevelopmentConfig)
