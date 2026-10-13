"""Pre-deployment readiness check.

    python preflight.py

Run this BEFORE starting the server. It answers the one question a deploy needs
answered - "will this actually work here?" - without starting anything.

Every check is read-only: it connects to MySQL and rolls back, loads the model
without predicting, and never writes a row. Exit code 0 means ready; 1 means at
least one check failed, and the failures are printed with the fix.

Nothing here is a substitute for the application's own production guards: those
refuse to boot on a bad secret. This catches the things a boot cannot - a
database that is reachable in config but not in fact, a missing model artifact,
or an API URL the browser could never resolve.
"""

from __future__ import annotations

import os
import sys

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

OK = "  ok  "
WARN = " warn "
FAIL = " FAIL "

results: list[tuple[str, str, str]] = []


def check(name: str, status: str, detail: str = "") -> None:
    results.append((name, status, detail))
    print("[%s] %s%s" % (status, name, (" - " + detail) if detail else ""))


def section(title: str) -> None:
    print()
    print("=== " + title + " ===")


def main() -> int:
    print("AquaGuard AI - pre-deployment check")
    print("Backend: " + BACKEND_DIR)

    # ---------------------------------------------------------------- config
    section("Configuration")

    from app.config import _env_first

    config_name = os.getenv("FLASK_ENV", "development")
    check("FLASK_ENV", OK, config_name)
    if config_name != "production":
        check(
            "Running as production",
            WARN,
            "FLASK_ENV is not 'production'; production guards will not run",
        )

    secret = _env_first("SECRET_KEY")
    if not secret:
        check("SECRET_KEY", FAIL, "unset - tokens cannot be signed")
    elif secret.startswith("replace-me") or len(secret) < 32:
        check("SECRET_KEY", FAIL, "placeholder or shorter than 32 characters")
    else:
        check("SECRET_KEY", OK, "set, %d characters" % len(secret))

    jwt_secret = _env_first("JWT_SECRET", "JWT_SECRET_KEY")
    if not jwt_secret:
        check("JWT_SECRET", FAIL, "unset")
    elif jwt_secret == secret:
        check("JWT_SECRET", FAIL, "identical to SECRET_KEY; they must differ")
    else:
        check("JWT_SECRET", OK, "set and distinct from SECRET_KEY")

    origins = [o.strip() for o in (_env_first("CORS_ORIGINS") or "").split(",") if o.strip()]
    if not origins:
        check("CORS_ORIGINS", FAIL, "empty - no browser origin could call this API")
    elif "*" in origins:
        check("CORS_ORIGINS", FAIL, "contains a wildcard; refused in production")
    else:
        check("CORS_ORIGINS", OK, ", ".join(origins))

    # ------------------------------------------------------------- application
    section("Application")

    try:
        from app import create_app

        app = create_app(config_name)
        check("Application factory", OK, "create_app() succeeded")
    except Exception as exc:
        check("Application factory", FAIL, "%s: %s" % (type(exc).__name__, exc))
        _summarise()
        return 1

    check("Debug mode", WARN if app.config.get("DEBUG") else OK, str(app.config.get("DEBUG")))
    check("JWT secret resolved", OK if app.config.get("JWT_SECRET_KEY") else FAIL)
    if app.config.get("AI_API_KEY"):
        check("Aqua AI provider", OK, "key present")
    else:
        check(
            "Aqua AI provider",
            WARN,
            "no key configured - the assistant will report itself unavailable",
        )

    # ---------------------------------------------------------------- database
    section("Database")

    with app.app_context():
        from sqlalchemy import text

        from app.extensions import db

        uri = app.config["SQLALCHEMY_DATABASE_URI"]
        safe = uri
        if "://" in uri and "@" in uri:
            scheme, rest = uri.split("://", 1)
            credentials, host = rest.split("@", 1)
            safe = "%s://%s:***@%s" % (scheme, credentials.split(":", 1)[0], host)
        check("Connection string", OK, safe)

        try:
            version = db.session.execute(text("SELECT VERSION()")).scalar()
            check("MySQL reachable", OK, "server version %s" % version)
        except Exception as exc:
            check("MySQL reachable", FAIL, str(exc)[:160])
            _summarise()
            return 1

        # Confirm the tables the application actually needs are present, rather
        # than only that a connection succeeded: an empty database connects
        # happily and then fails on the first query.
        #
        # The expected names come from the ORM metadata, NOT from a hand-written
        # list. A hardcoded list is how this check first reported the AI tables
        # as missing when the real names were aqua_ai_conversations /
        # aqua_ai_messages - the check was wrong, not the schema. Deriving them
        # from the models means the two cannot disagree.
        required = sorted(t.name for t in db.metadata.tables.values())
        try:
            rows = db.session.execute(
                text("SELECT table_name FROM information_schema.tables WHERE table_schema = DATABASE()")
            ).scalars().all()
            present = {str(r).lower() for r in rows}
            missing = [t for t in required if t.lower() not in present]
            if missing:
                check("Schema", FAIL, "missing tables: " + ", ".join(missing))
            else:
                check(
                    "Schema",
                    OK,
                    "all %d model tables present (%d tables in database)"
                    % (len(required), len(present)),
                )
        except Exception as exc:
            check("Schema", FAIL, str(exc)[:160])

        db.session.rollback()

    # --------------------------------------------------------------------- ML
    section("Machine learning")

    with app.app_context():
        try:
            from app.ml import water_quality

            if water_quality.is_available():
                meta = {}
                try:
                    meta = water_quality.metadata() or {}
                except Exception:
                    meta = {}
                check(
                    "Model artifact",
                    OK,
                    "version %s" % (meta.get("model_version") or "unknown"),
                )
            else:
                check(
                    "Model artifact",
                    FAIL,
                    "not found - predictions would return 503. Run the training script.",
                )
        except Exception as exc:
            check("Model artifact", FAIL, "%s: %s" % (type(exc).__name__, exc))

        # A load proves the artifact deserialises with the installed
        # scikit-learn, which a file-exists check does not.
        try:
            from app.ml.predictor import predict

            sample = {
                "ph": 7.1,
                "turbidity": 1.2,
                "tds": 280.0,
                "temperature": 18.0,
                "dissolved_oxygen": 8.4,
            }
            out = predict(sample)
            check(
                "Inference",
                OK,
                "verdict=%s confidence=%.3f" % (out.get("risk_level"), float(out.get("confidence", 0))),
            )
        except Exception as exc:
            check("Inference", FAIL, "%s: %s" % (type(exc).__name__, exc))

    # ------------------------------------------------------------------- Aqua AI
    section("Aqua AI")

    with app.app_context():
        try:
            from app.ai.tool_runner import AVAILABLE_TOOLS
            from app.utils.ai_tools import get_tool_names

            advertised = set(get_tool_names())
            registered = set(AVAILABLE_TOOLS)
            check(
                "Tool catalogue",
                OK,
                "%d advertised, %d with server handlers" % (len(advertised), len(registered)),
            )
        except Exception as exc:
            check("Tool catalogue", FAIL, "%s: %s" % (type(exc).__name__, exc))

        try:
            from app.ai.safety import SAFETY_RULES

            check("Safety rules", OK, "%d rules loaded" % len(SAFETY_RULES))
        except Exception as exc:
            check("Safety rules", FAIL, "%s: %s" % (type(exc).__name__, exc))

        try:
            from app.ai.prompts import build_system_prompt

            prompt = build_system_prompt()
            check("System prompt", OK, "%d characters" % len(prompt))
        except Exception as exc:
            check("System prompt", FAIL, "%s: %s" % (type(exc).__name__, exc))

    # ------------------------------------------------------------------ routes
    section("Routes")

    try:
        rules = [r for r in app.url_map.iter_rules() if not str(r).startswith("/static")]
        check("Registered", OK, "%d routes" % len(rules))
        # The routes a deployment cannot work without. This application is
        # deliberately OPEN: there is no user login, so there are no
        # `/auth/register` or `/auth/login` endpoints to check. The one
        # credential in the system is the admin console's, reached through
        # `/admin/session`, which is checked instead.
        expected = [
            "/api/v1/health",
            "/api/v1/admin/session",
            "/api/v1/predictions/predict",
            "/api/v1/dashboard/overview",
            "/api/v1/alerts",
            "/api/v1/ai/chat",
        ]
        paths = {str(r) for r in rules}
        missing = [p for p in expected if p not in paths]
        if missing:
            check("Critical routes", FAIL, "missing: " + ", ".join(missing))
        else:
            check("Critical routes", OK, "all %d present" % len(expected))
    except Exception as exc:
        check("Routes", FAIL, "%s: %s" % (type(exc).__name__, exc))

    return _summarise()


def _summarise() -> int:
    counts = {OK: 0, WARN: 0, FAIL: 0}
    for _, status, _ in results:
        counts[status] += 1

    print()
    print("=" * 66)
    print(
        "TOTAL %d  |  ok %d  |  warn %d  |  FAIL %d"
        % (len(results), counts[OK], counts[WARN], counts[FAIL])
    )
    failures = [r for r in results if r[1] == FAIL]
    warnings = [r for r in results if r[1] == WARN]
    if failures:
        print()
        print("FAILURES (must be fixed before deploying):")
        for name, _, detail in failures:
            print("  - %s%s" % (name, (": " + detail) if detail else ""))
    if warnings:
        print()
        print("WARNINGS (deployment works, but review):")
        for name, _, detail in warnings:
            print("  - %s%s" % (name, (": " + detail) if detail else ""))
    print("=" * 66)
    if counts[FAIL]:
        print("NOT READY")
        return 1
    print("READY")
    return 0


if __name__ == "__main__":
    sys.exit(main())
