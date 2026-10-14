"""AquaGuard AI backend package.

The application is created through the factory in this module so that multiple
instances (web server, tests, CLI) can coexist with different configuration.
"""

import logging
import os
import threading
from logging.handlers import RotatingFileHandler

from flask import Flask, current_app, jsonify

from app.config import get_config
from app.constants import API_PREFIX, API_SHORT_PREFIX
from app.extensions import db, init_extensions
from app.utils.errors import AquaGuardError
from app.utils.responses import error_response

__version__ = "0.1.0"

# Imported for their side effect: each model module registers itself on the
# SQLAlchemy metadata so `db.create_all()` and Alembic autogenerate see it.
from app import models  # noqa: E402,F401  (must follow extension creation)


def create_app(config_name: str | None = None) -> Flask:
    """Build, configure and return the Flask application."""
    app = Flask(__name__)
    app.config.from_object(get_config(config_name))

    # Honour an explicit DATABASE_URL that was set AFTER this module was
    # imported. The config classes compute their URI eagerly in their class
    # bodies, so a self-contained test module that sets the variable and only
    # then imports `app` would otherwise be silently ignored, and the test
    # would run against the developer's real database. Re-reading it here,
    # at factory time, makes the override take effect for every caller.
    #
    # Normalised through the SAME helper the config class uses, because a
    # provider URL arrives as `mysql://...?ssl-mode=REQUIRED`, which SQLAlchemy
    # rejects and PyMySQL silently connects WITHOUT TLS. Assigning the raw value
    # here would undo that normalisation on the very path that matters.
    _explicit_db_url = (os.getenv("DATABASE_URL") or "").strip()
    if _explicit_db_url:
        from app.config import _normalise_database_url

        app.config["SQLALCHEMY_DATABASE_URI"] = _normalise_database_url(_explicit_db_url)

    _configure_logging(app)
    init_extensions(app)
    _register_blueprints(app)
    _register_jwt_handlers(app)
    _register_error_handlers(app)
    _register_shell_context(app)
    _register_ai_tools()

    # --- Frontend bundle (single-service deploy) ----------------------------
    # Registered LAST on purpose. The catch-all route below must not shadow any
    # API route, and Flask matches rules in registration order - so every
    # blueprint above is already in the map by the time this runs.
    _register_frontend(app)

    # --- Production pre-flight ---------------------------------------------
    # Run after configuration but BEFORE the app is handed out, so a production
    # deployment with a placeholder secret, debug left on or a wildcard CORS
    # origin fails at boot instead of serving traffic with a known signing key.
    # Development and testing are unaffected.
    if app.config.get("ENV") == "production" or config_name == "production":
        from app.config import validate_production
        validate_production(app)
        app.logger.info("Production configuration validated")

    @app.get("/")
    def index():
        """Small discovery payload — confirms the API is alive.

        The application is OPEN: there is no user login, so there is no auth
        endpoint to advertise. The console is listed only by its own URL and is
        not a public option - it is a separate surface with its own credential.
        """
        return jsonify(
            name="AquaGuard AI API",
            version=__version__,
            api_prefix=API_PREFIX,
            health=f"{API_SHORT_PREFIX}/health",
            endpoints={
                "predictions": f"{API_SHORT_PREFIX}/predictions/predict",
                "dashboard": f"{API_SHORT_PREFIX}/dashboard/overview",
                "locations": f"{API_SHORT_PREFIX}/locations/context",
                "admin_login": f"{API_SHORT_PREFIX}/admin/session",
            },
        )

    # --- Model warm-up -----------------------------------------------------
    # The trained Random Forest is ~30 MB across 300 trees. Importing sklearn
    # and unpickling that artifact took ~8 s, and because it was lazy, all of it
    # landed on whichever unlucky request arrived first - that request, and only
    # that request, took 16 s while every later one took ~0.4 s.
    #
    # So it is loaded HERE, at start-up, before the process accepts traffic. The
    # first prediction now finds the model already in memory and resident in the
    # CPU cache. This changes WHEN the cost is paid, not WHETHER it is paid, and
    # the model is exactly the same one - no re-training, no reduced accuracy.
    #
    # It never blocks boot on failure. A missing artifact is reported here and
    # still surfaces per request as an honest 503, which is the behaviour the
    # predict endpoint promises.
    _warm_up_model(app)

    app.logger.info("AquaGuard AI backend initialised (env=%s)", config_name or os.getenv("FLASK_ENV", "development"))
    return app


def _warm_up_model(app: Flask) -> None:
    """Load the prediction model once, at start-up, off the request path.

    `app` is passed in rather than reached for as `current_app`, because this
    runs on a background thread that has no request and therefore no current
    application to proxy to - reading `current_app` there raises RuntimeError
    (verified, not assumed).
    """

    def _load() -> None:
        from app.ml import water_quality

        # STEP 36 FIX: this thread needs its OWN application context.
        #
        # `water_quality._ml_root()` reads `ML_WATER_QUALITY_DIR` from
        # `current_app`. A background thread has no application context, so every
        # call raised RuntimeError and fell through to the module's hard-coded
        # default - the real `ml/` next to the backend. The configured model
        # directory was therefore silently ignored by the one piece of code that
        # decides which forest gets loaded, and the warm-up permanently pinned
        # `sys.path` and the cached pipeline to the real tree. Measured while
        # testing a missing-model deployment: the app reported
        # `water-quality-rf-v1.0.0` and predicted `safe` from a directory that
        # contained no model at all.
        #
        # Pushing the app context makes the thread read the same configuration
        # every request does, so the artifact that is warmed up is the artifact
        # that is served. It is also why a missing model must still surface as an
        # honest 503 per request rather than a boot failure, so the whole warm-up
        # is contained and cannot take the process down with it.
        try:
            with app.app_context():
                if not water_quality.warm_up():
                    app.logger.warning(
                        "Water quality model not pre-loaded; predictions will report "
                        "unavailable until the artifact is installed."
                    )
        except Exception:  # noqa: BLE001 - start-up optimisation, never fatal
            app.logger.exception("Water quality model warm-up thread failed")

    # Off the critical path: a slow or unreachable model directory delays
    # nothing that is not the model itself, and the app is still serving the
    # moment this thread is spawned.
    thread = threading.Thread(target=_load, name="ml-model-warmup", daemon=True)
    thread.start()


def _configure_logging(app: Flask) -> None:
    """Attach a rotating file handler plus stdout, honouring LOG_LEVEL."""
    level = getattr(logging, str(app.config.get("LOG_LEVEL", "INFO")).upper(), logging.INFO)
    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s in %(module)s: %(message)s"
    )

    app.logger.setLevel(level)

    # Already configured: an earlier create_app in this process has installed the
    # file handler. Return BEFORE building another one.
    #
    # The previous version built the handler first and then discarded it when one
    # already existed, which leaked an open file handle per application instance.
    # The test suite builds an application per fixture, so that leak accumulated
    # until Windows refused to rotate the log - surfacing as
    # "[WinError 32] The process cannot access the file" from deep inside the
    # logging module, nowhere near the code responsible.
    if any(isinstance(h, RotatingFileHandler) for h in app.logger.handlers):
        return
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
    os.makedirs(log_dir, exist_ok=True)

    file_handler = RotatingFileHandler(
        os.path.join(log_dir, "aquaguard.log"),
        maxBytes=2 * 1024 * 1024,
        backupCount=5,
        # `delay=True` opens the file on the first write rather than at
        # construction. That keeps an application which never logs from holding a
        # handle on the log file at all, which is what makes the file
        # replaceable - and it is the difference between a rotation succeeding
        # and WinError 32 on Windows.
        delay=True,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)

    # Errors during rotation are logged, never raised. A full disk or a
    # permission problem must not take the application down: losing log lines is
    # bad, but refusing to serve requests because of it is worse.
    file_handler.handleError = lambda record: None
    app.logger.addHandler(file_handler)


def _register_blueprints(app: Flask) -> None:
    """Register every resource blueprint under the shared API prefix."""
    from app.routes.admin_routes import admin_bp
    from app.routes.ai_routes import ai_bp
    from app.routes.alert_routes import alerts_bp
    from app.routes.dashboard_routes import dashboard_bp
    from app.routes.health_routes import health_bp
    from app.routes.location_routes import location_bp
    from app.routes.prediction_routes import predictions_bp
    from app.routes.report_mail_routes import report_mail_bp
    for blueprint, url_prefix in (
        (health_bp, "/health"),
        (predictions_bp, "/predictions"),
        (dashboard_bp, "/dashboard"),
        (alerts_bp, "/alerts"),
        (ai_bp, "/ai"),
        (location_bp, "/locations"),
        (report_mail_bp, "/reports"),
    ):
        app.register_blueprint(blueprint, url_prefix=f"{API_PREFIX}{url_prefix}")

    # The admin console is mounted at `/api/admin` and deliberately NOT under
    # `/api/v1`. It is an internal surface rather than part of the versioned
    # public contract, and versioning it would imply the same stability promise
    # as the user-facing endpoints, which it does not carry.
    app.register_blueprint(
        admin_bp, url_prefix=f"{API_SHORT_PREFIX}/admin", name="admin"
    )

    # The console is ALSO reachable under the versioned prefix, for the same
    # reason as Aqua AI above: a frontend configured with
    # `VITE_API_BASE_URL=/api/v1` sends every console call to `/api/v1/admin/...`,
    # which had no route at all — so the admin page loaded its shell and then
    # every panel failed with 404. The versioning promise is unaffected: this is
    # an alias onto the same handlers, not a second implementation.
    app.register_blueprint(
        admin_bp, url_prefix=f"{API_PREFIX}/admin", name="admin_versioned"
    )

    # The health blueprint is also mounted at the short, unversioned path
    # `/api/health`. Monitors and load balancers should not have to track an API
    # version to ask whether a process is alive — and a probe URL that changes
    # when the API version changes is a probe that silently breaks.
    app.register_blueprint(health_bp, url_prefix=f"{API_SHORT_PREFIX}/health", name="health_short")

    # Locations are also mounted at the stable, unversioned `/api/locations`,
    # for the same reason as the other stable paths: the frontend's documented
    # contract uses the unversioned form, and a location URL that moves with the
    # API version is a location URL that breaks quietly.
    app.register_blueprint(
        location_bp, url_prefix=f"{API_SHORT_PREFIX}/locations", name="locations_short"
    )

    # Predictions are also mounted at the stable, unversioned
    # `/api/predictions/...`, which is the path the frontend and the API docs
    # specify. Only the predict endpoint is required there, but mounting the
    # whole blueprint keeps the two surfaces identical, so a client cannot end
    # up talking to a different resource set depending on which prefix it used.
    app.register_blueprint(
        predictions_bp,
        url_prefix=f"{API_SHORT_PREFIX}/predictions",
        name="predictions_short",
    )

    # Aqua AI is also mounted at the stable, unversioned `/api/ai`, so the
    # assistant's endpoint is reachable at `/api/ai/aqua-ai/chat` as well as the
    # versioned path. A chat URL that changes with the API version is a chat URL
    # that breaks quietly, and the client contract names the unversioned form.
    app.register_blueprint(ai_bp, url_prefix=f"{API_SHORT_PREFIX}/ai", name="ai_short")
    # The canonical chat path named by the React client contract:
    # `POST /api/aqua-ai/chat`. Mounted directly under `/api` so the assistant's
    # public URL is exactly what the client documents, without depending on the
    # `/ai` sub-prefix. Same blueprint, same handlers — one implementation.
    app.register_blueprint(
        ai_bp, url_prefix=f"{API_SHORT_PREFIX}/aqua-ai", name="aqua_ai_short"
    )

    # Aqua AI under the VERSIONED `/api/v1/aqua-ai` as well.
    #
    # Without this the client's `POST {baseURL}/aqua-ai/chat` becomes
    # `/api/v1/aqua-ai/chat` whenever the frontend sets
    # `VITE_API_BASE_URL=/api/v1`, and the route only existed at
    # `/api/v1/ai/aqua-ai/chat` — so the assistant answered every question with a
    # bare 404 "Resource not found", which reads as a broken chatbot rather than
    # as a prefix mismatch. Mounting the same blueprint here means both the
    # versioned and unversioned base URLs reach one handler.
    app.register_blueprint(ai_bp, url_prefix=f"{API_PREFIX}/aqua-ai", name="aqua_ai_versioned")

    # Dashboard, alerts and reports are ALSO mounted at the short, unversioned
    # paths, for the same reason as every other surface above.
    #
    # The React client's base URL is `/api`, so it calls `/api/dashboard/summary`
    # and `/api/alerts` - and before these aliases existed only the versioned
    # `/api/v1/...` mount did, so every dashboard tile and the alert badge came
    # back as a bare 404 while the rest of the application worked. The versioned
    # path is the documented contract and stays; this is an alias onto the same
    # handlers, not a second implementation.
    for blueprint, url_prefix, alias in (
        (dashboard_bp, "/dashboard", "dashboard_short"),
        (alerts_bp, "/alerts", "alerts_short"),
        (report_mail_bp, "/reports", "reports_short"),
    ):
        app.register_blueprint(
            blueprint, url_prefix=f"{API_SHORT_PREFIX}{url_prefix}", name=alias
        )


def _register_jwt_handlers(app: Flask) -> None:
    # Translate JWT failures into the standard JSON envelope.
    #
    # Without these, an expired token returns Flask-JWT-Extended's own bare
    # {"msg": "Token has expired"} shape. The frontend would then have to
    # special-case two different error formats, and would have no reliable
    # signal for "your session ended, sign in again".
    jwt = app.extensions["flask-jwt-extended"]

    @jwt.user_lookup_loader
    def _user_lookup(jwt_header: dict, jwt_data: dict):
        # Resolve the token's identity to a live account on EVERY request.
        #
        # Without this, a JWT is trusted purely because its signature checks
        # out — so a token issued to an account that has since been deleted
        # keeps working until it expires. That is a real hole: revoking access
        # (deleting a user, disabling an account) would have no effect.
        identity = jwt_data.get("sub")
        try:
            user_id = int(identity)
        except (TypeError, ValueError):
            return None
        from app.models import User
        return db.session.get(User, user_id)

    @jwt.user_lookup_error_loader
    def _user_lookup_failed(jwt_header: dict, jwt_data: dict):
        # The token is valid but its account no longer exists.
        return error_response(
            "Account no longer exists",
            401,
            {"token": "account not found"},
        )

    @jwt.unauthorized_loader
    def _missing_token(reason: str):
        # No Authorization header at all.
        return error_response(
            "Authentication required", 401, {"token": "Missing bearer token"}
        )

    @jwt.invalid_token_loader
    def _invalid_token(reason: str):
        # Signature mismatch, wrong algorithm, or a structurally broken token.
        return error_response("Invalid authentication token", 401, {"token": reason})

    @jwt.expired_token_loader
    def _expired_token(jwt_header, jwt_payload):
        # The client treats this as "session over, sign in again".
        return error_response("Your session has expired", 401, {"token": "expired"})

    @jwt.revoked_token_loader
    def _revoked_token(jwt_header, jwt_payload):
        return error_response("This token has been revoked", 401, {"token": "revoked"})

    @jwt.token_verification_failed_loader
    def _verification_failed(jwt_header, jwt_payload):
        return error_response(
            "Token verification failed", 401, {"token": "verification failed"}
        )


def _register_error_handlers(app: Flask) -> None:
    """Return consistent JSON envelopes for every error class."""

    @app.errorhandler(NotImplementedError)
    def not_implemented(error):
        # A service stub from the architecture phase raises this. Translating it
        # to a 501 keeps the response in the standard envelope and stops an
        # unfinished endpoint from being logged as a server fault. The message
        # is passed through because these stubs name their own phase, which is
        # genuinely useful when reading logs.
        return error_response(
            "This feature is not implemented yet",
            status_code=501,
            errors=str(error),
        )

    @app.errorhandler(AquaGuardError)
    def domain_error(error):
        # Any service-level error that escaped a route's own try/except still
        # gets the standard envelope, rather than a bare 500 traceback.
        return error_response(
            error.message,
            status_code=error.status_code,
            errors=error.errors,
        )

    @app.errorhandler(400)
    def bad_request(error):
        return jsonify(success=False, message="Bad request", error=str(error)), 400

    @app.errorhandler(401)
    def unauthorized(error):
        return jsonify(success=False, message="Unauthorized", error=str(error)), 401

    @app.errorhandler(403)
    def forbidden(error):
        return jsonify(success=False, message="Forbidden", error=str(error)), 403

    @app.errorhandler(404)
    def not_found(error):
        return jsonify(success=False, message="Resource not found", error=str(error)), 404

    @app.errorhandler(405)
    def method_not_allowed(error):
        return jsonify(success=False, message="Method not allowed", error=str(error)), 405

    @app.errorhandler(422)
    def unprocessable(error):
        return jsonify(success=False, message="Unprocessable entity", error=str(error)), 422

    @app.errorhandler(500)
    def internal_error(error):
        app.logger.exception("Unhandled server error: %s", error)
        return jsonify(success=False, message="Internal server error"), 500

    @app.errorhandler(Exception)
    def unhandled_exception(error):
        # HTTPException instances keep their own status code and message.
        from werkzeug.exceptions import HTTPException

        if isinstance(error, HTTPException):
            return (
                jsonify(success=False, message=error.name, error=error.description),
                error.code,
            )
        app.logger.exception("Unhandled exception: %s", error)
        return jsonify(success=False, message="Internal server error"), 500


def _register_ai_tools() -> None:
    """Wire Aqua AI's controlled tool handlers into the tool runner.

    Done at application-factory time so every entrypoint (web server, tests,
    CLI) has the same tools registered, and the assistant can only ever call a
    catalogued tool.
    """
    from app.ai.tools import register_default_tools
    register_default_tools()


def _register_shell_context(app: Flask) -> None:
    """Make models and the db handle available in `flask shell`."""

    @app.shell_context_processor
    def shell_context():
        from app import models as models_module
        from app.extensions import db as _db

        return {"db": _db, "models": models_module}

# ---------------------------------------------------------------------------
# Frontend bundle serving
# ---------------------------------------------------------------------------
# AquaGuard AI ships as a React SPA built by Vite. It can be served two ways:
#
#   1. SPLIT (the original layout): Netlify serves `frontend/dist` and Render
#      serves this API. Two origins, so CORS is load-bearing and the API URL is
#      baked into the bundle at build time.
#
#   2. SINGLE SERVICE (what this block enables): Render runs ONE web service
#      that serves BOTH. `frontend/dist` is copied to `backend/static` during
#      the build, and this module serves it from the same origin as `/api/*`.
#
# The single-service mode is strictly simpler to operate: there is one deploy,
# one URL and no CORS at all, because the browser only ever talks to one origin.
# It is also the ONLY way to get "click the link, get the UI" on the free tier -
# with two origins the visitor waits for a cold Netlify edge AND a cold Render
# dyno, and any failure in either looks like "the backend is broken".
#
# The split layout is NOT removed. If `backend/static` does not exist - which is
# exactly the case for a Netlify-served frontend, for local development and for
# the test suite - this function registers NOTHING and the app behaves exactly
# as it did before. So enabling the single-service deploy cannot break the other
# two, and reverting is a matter of deleting a directory.
#
# Docs: https://flask.palletsprojects.com/en/stable/patterns/favicon/
# ---------------------------------------------------------------------------


def _register_frontend(app: Flask) -> None:
    """Serve the built React bundle, when one has been placed beside the app.

    Registers three things, in this order:

      * a real static route for `/assets/<path>` and friends, so hashed bundle
        files are served by Flask's static handler with correct caching headers
        rather than by the catch-all below;
      * the SPA fallback: any GET that matches no API route and no static file
        returns `index.html` with a 200. Without it a refresh on `/dashboard`
        would 404, because no such file exists on disk - React Router owns that
        path only after the first load;
      * nothing at all when there is no bundle, which keeps dev and tests as
        they were.
    """
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
    index_file = os.path.join(static_dir, "index.html")

    if not os.path.isfile(index_file):
        # No bundle beside the app: this is the Netlify-served or local-dev
        # layout. Registering a catch-all here would swallow 404s that the
        # client contract relies on, so we deliberately register nothing.
        app.logger.info(
            "No frontend bundle at %s - API-only mode (frontend served elsewhere)",
            static_dir,
        )
        return

    from flask import send_from_directory

    # `static_folder` was set to None-ish behaviour by using a distinct path, so
    # this explicit route is what serves the hashed asset files. It is registered
    # BEFORE the catch-all so a missing asset 404s honestly instead of returning
    # index.html with a 200, which would make a broken bundle look like a
    # working page whose stylesheet silently failed.
    @app.get("/assets/<path:filename>")
    def frontend_assets(filename):
        return send_from_directory(os.path.join(static_dir, "assets"), filename)

    # Root-level static files Vite emits beside index.html (favicon, _redirects,
    # manifest, service worker). Served explicitly for the same reason.
    #
    # NOTE the guard: this route is a GET-only catch-all registered AFTER every
    # API rule, so Flask only reaches it when no API route matched. An unknown
    # path under `/api/` must still 404 - if it returned index.html with a 200,
    # a genuinely broken API call would look like a working page whose data
    # silently never arrives, which is precisely the failure this whole deploy
    # exercise exists to eliminate. So anything under the API prefixes is
    # re-raised as a real 404 instead of falling through to the SPA.
    @app.get("/<path:filename>")
    def frontend_static(filename):
        if filename == "api" or filename.startswith(("api/", "api\\")):
            from werkzeug.exceptions import NotFound

            raise NotFound()

        candidate = os.path.join(static_dir, filename)
        if os.path.isfile(candidate):
            return send_from_directory(static_dir, filename)
        # Not a file on disk - hand it to React Router.
        return send_from_directory(static_dir, "index.html")

    app.logger.info("Serving frontend bundle from %s (single-service mode)", static_dir)
