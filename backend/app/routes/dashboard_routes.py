"""Dashboard blueprint — aggregated data for the landing screen.

    GET /api/v1/dashboard/overview      KPI cards + latest prediction
    GET /api/v1/dashboard/charts        Recharts-ready time series / distributions
    GET /api/v1/dashboard/parameters    feature metadata for the input form

NO TOKEN IS REQUIRED on any of these. The application is open, so the figures are
scoped to whatever account the request resolves to - see `app.services.identity`.
"""

from flask import Blueprint

from app.utils.errors import AquaGuardError
from app.utils.responses import error_response, success_response

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.get("/overview")
def overview():
    """Headline figures: totals, safety ratio, average confidence, open alerts."""
    try:
        from app.services.dashboard_service import get_overview

        return success_response(data=get_overview())
    except AquaGuardError as exc:
        return error_response(exc.message, exc.status_code, exc.errors)


@dashboard_bp.get("/charts")
def charts():
    """Data sets shaped for the Recharts components on the dashboard."""
    try:
        from app.services.dashboard_service import get_charts

        return success_response(data=get_charts())
    except AquaGuardError as exc:
        return error_response(exc.message, exc.status_code, exc.errors)


@dashboard_bp.get("/summary")
def summary():
    """KPI counters and chart series for the caller."""
    try:
        from app.services.dashboard_service import get_summary
        return success_response(data=get_summary())
    except AquaGuardError as exc:
        return error_response(exc.message, exc.status_code, exc.errors)

@dashboard_bp.get("/recent")
def recent():
    """Recent predictions (activity) and recent alerts for the caller."""
    try:
        from flask import request
        from app.services.dashboard_service import get_recent
        limit = request.args.get("limit", 5)
        return success_response(data=get_recent(int(limit)))
    except AquaGuardError as exc:
        return error_response(exc.message, exc.status_code, exc.errors)

@dashboard_bp.get("/parameters")
def parameters():
    """Canonical parameter metadata (order, units, bounds) for the frontend form.

    Serving this from the backend guarantees the form can never drift from the
    validation and model contract.
    """
    try:
        from app.services.dashboard_service import get_parameter_metadata

        return success_response(data=get_parameter_metadata())
    except AquaGuardError as exc:
        return error_response(exc.message, exc.status_code, exc.errors)
