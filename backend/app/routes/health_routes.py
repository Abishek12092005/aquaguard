"""Liveness and readiness endpoints.

Two questions, deliberately kept separate:

    GET /api/health      "is the web server serving requests?"
    GET /api/health/db   "is MySQL reachable?"

Merging them would mean a database blip makes an orchestrator restart a
perfectly healthy web process, so `/api/health` never touches a dependency.
"""

from flask import Blueprint, current_app, jsonify

from app.constants import API_PREFIX
from app.extensions import db
from app.utils.responses import error_response, success_response

health_bp = Blueprint("health", __name__)


@health_bp.get("")
@health_bp.get("/")
def health():
    """Liveness probe.

        {
          "success": true,
          "message": "AquaGuard AI backend is running"
        }
    """
    return jsonify({
        "success": True,
        "message": "AquaGuard AI backend is running",
    }), 200


@health_bp.get("/status")
def health_status():
    """Richer status payload, for dashboards rather than probes.

    Reports configuration completeness without revealing any secret value:
    booleans only, so a developer can see at a glance that a key is missing
    without the response ever carrying it.
    """
    config = current_app.config
    # Multi-provider aware: the key may be configured under one of the provider
    # variables rather than the legacy single `AI_API_KEY`, so the flag asks the
    # same resolver the assistant itself uses. Reporting False while a working
    # Gemini key was set would mislead the developer reading this page.
    from app.ai.providers import resolve_providers

    return success_response(
        data={
            "service": "aquaguard-api",
            "status": "healthy",
            "apiPrefix": API_PREFIX,
            "environment": config.get("ENV", "development"),
            "debug": bool(config.get("DEBUG")),
            "databaseConfigured": bool(config.get("SQLALCHEMY_DATABASE_URI")),
            "aiEnabled": bool(config.get("AI_ENABLED")),
            # Presence flags only, never the values themselves.
            "aiKeyConfigured": bool(
                config.get("AI_API_KEY") or resolve_providers(config)
            ),
            "jwtConfigured": bool(config.get("JWT_SECRET_KEY")),
            "corsOrigins": config.get("CORS_ORIGINS", []),
        },
        message="AquaGuard AI API is running",
    )


@health_bp.get("/database")
@health_bp.get("/db")
def health_database():
    """Verify the MySQL connection and report the active schema.

    This is the endpoint that answers the dependency question, and the only one
    that opens a connection.
    """
    try:
        version = db.session.execute(db.text("SELECT VERSION()")).scalar()
    except Exception as exc:  # reported to the client as a 503
        current_app.logger.error("Database health check failed: %s", exc)
        return error_response(
            "Database is unreachable",
            status_code=503,
            errors=str(exc).splitlines()[0],
        )

    uri = current_app.config.get("SQLALCHEMY_DATABASE_URI", "")
    database = uri.split("?", 1)[0].rsplit("/", 1)[-1] if "/" in uri else "unknown"

    return success_response(
        data={
            "status": "connected",
            "database": database,
            "mysqlVersion": version,
        },
        message="Database connection is healthy",
    )
