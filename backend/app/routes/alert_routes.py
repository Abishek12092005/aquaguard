"""Alerts blueprint — list, acknowledge and resolve unsafe-water alerts.

    GET   /api/v1/alerts               paginated alerts (filterable by status)
    GET   /api/v1/alerts/summary       unread / severity counters for the bell
    PATCH /api/v1/alerts/<id>/ack      acknowledge an alert
    PATCH /api/v1/alerts/<id>/read     mark one alert read
    PATCH /api/v1/alerts/read-all      mark every alert read
    PATCH /api/v1/alerts/<id>/resolve  mark an alert resolved (persisted)
    PATCH /api/v1/alerts/<id>/unresolve reopen a resolved alert

NO TOKEN IS REQUIRED on any of these. The application is open; "the caller's
alerts" is resolved by the one shared rule in `app.services.identity`.
"""

from flask import Blueprint, request

from app.utils.errors import AquaGuardError
from app.utils.pagination import parse_pagination
from app.utils.responses import error_response, success_response

alerts_bp = Blueprint("alerts", __name__)


@alerts_bp.get("")
def list_alerts():
    """Return the caller's alerts, newest first."""
    try:
        from app.services.alert_service import list_user_alerts

        page, per_page = parse_pagination()
        items, meta = list_user_alerts(
            page, per_page, status=request.args.get("status"), severity=request.args.get("severity")
        )
        return success_response(data=items, meta=meta)
    except AquaGuardError as exc:
        return error_response(exc.message, exc.status_code, exc.errors)


@alerts_bp.get("/summary")
def alert_summary():
    """Counters used by the notification bell badge."""
    try:
        from app.services.alert_service import get_alert_summary

        return success_response(data=get_alert_summary())
    except AquaGuardError as exc:
        return error_response(exc.message, exc.status_code, exc.errors)


@alerts_bp.patch("/<int:alert_id>/read")
def mark_alert_read(alert_id: int):
    """Mark one of the caller's alerts as read.

    Idempotent: marking an already-read alert returns 200 with `changed: false`
    rather than an error, so a retried request is not punished.

    Status codes: 200 on success; 404 when the alert does not exist *or* belongs
    to another account, so its existence cannot be probed by comparing the two.
    No token is required.
    """
    try:
        from app.services.alert_service import mark_alert_read as mark_read
        return success_response(data=mark_read(alert_id), message="Alert marked as read")
    except AquaGuardError as exc:
        return error_response(exc.message, exc.status_code, exc.errors)

@alerts_bp.patch("/read-all")
def mark_all_alerts_read():
    """Mark every unread alert the caller owns as read."""
    try:
        from app.services.alert_service import mark_all_alerts_read as mark_all
        return success_response(data=mark_all(), message="All alerts marked as read")
    except AquaGuardError as exc:
        return error_response(exc.message, exc.status_code, exc.errors)

@alerts_bp.patch("/<int:alert_id>/ack")
def acknowledge_alert(alert_id: int):
    """Mark an alert as acknowledged by the user."""
    try:
        from app.services.alert_service import acknowledge_alert
        return success_response(
            data=acknowledge_alert(alert_id), message="Alert acknowledged"
        )
    except AquaGuardError as exc:
        return error_response(exc.message, exc.status_code, exc.errors)


@alerts_bp.patch("/<int:alert_id>/resolve")
def resolve_alert(alert_id: int):
    """Mark an alert as resolved."""
    try:
        from app.services.alert_service import resolve_alert as resolve

        return success_response(data=resolve(alert_id), message="Alert resolved")
    except AquaGuardError as exc:
        return error_response(exc.message, exc.status_code, exc.errors)


@alerts_bp.patch("/<int:alert_id>/unresolve")
def unresolve_alert(alert_id: int):
    """Reopen a resolved alert.

    The counterpart to resolve. Exposing it is what makes the resolve button safe
    to press: a mis-click is one press to undo rather than something the user has
    to live with.
    """
    try:
        from app.services.alert_service import unresolve_alert as unresolve

        return success_response(data=unresolve(alert_id), message="Alert reopened")
    except AquaGuardError as exc:
        return error_response(exc.message, exc.status_code, exc.errors)
