"""Prediction blueprint — run a prediction and query prediction history.

This is the core REST surface of the project:

    POST /api/v1/predictions          submit parameters -> prediction
    POST /api/v1/predictions/predict  the model-first predict endpoint (step 8)
    GET  /api/v1/predictions          paginated prediction list
    GET  /api/v1/predictions/<id>     single prediction detail
    GET  /api/v1/predictions/latest   most recent prediction
    GET  /api/v1/predictions/stats    aggregated statistics for charts
"""

from flask import Blueprint, request

from app.utils.errors import AquaGuardError
from app.utils.pagination import parse_pagination
from app.utils.responses import error_response, success_response

predictions_bp = Blueprint("predictions", __name__)


@predictions_bp.post("")
def create_prediction():
    """Validate -> preprocess -> Random Forest -> persist -> alert if unsafe."""
    try:
        from app.services.prediction_service import run_prediction

        return success_response(
            data=run_prediction(),
            message="Prediction completed",
            status_code=201,
        )
    except AquaGuardError as exc:
        return error_response(exc.message, exc.status_code, exc.errors)


@predictions_bp.post("/predict")
def predict_water_quality():
    """Run the trained model for the caller and persist the result.

    Request flow, in order:

        request -> validation -> preprocessing -> ML model -> prediction
                -> confidence -> MySQL -> response
    Registered at both `/api/v1/predictions/predict` (canonical) and
    `/api/predictions/predict` (the stable, unversioned path the frontend and
    the API docs use), so the client contract does not move with the version.

    Status codes:

        201  the model produced a verdict and it was stored
        400  body missing or not valid JSON
        422  understood, but one or more parameters were invalid
        503  the model artifact is unavailable — never a fabricated verdict

    NO TOKEN IS REQUIRED. The application is open, so this endpoint refuses no
    caller. A request that happens to carry a valid bearer token is filed under
    that account; every other request is filed under the shared visitor account
    (see `app.services.identity`).
    """
    try:
        from app.services.prediction_service import predict_only
        return success_response(
            data=predict_only(),
            message="Prediction completed",
            status_code=201,
        )
    except AquaGuardError as exc:
        return error_response(exc.message, exc.status_code, exc.errors)

def _history_payload():
    """Shared body for `GET /predictions` and `GET /predictions/history`.

    Both endpoints list the caller's own records with the same filters; they
    differ only in which path a client prefers. Sharing the implementation
    means a new filter cannot land on one of them and miss the other.
    """
    from app.constants import RISK_LEVELS
    from app.services.prediction_service import list_user_predictions
    from app.utils.query_params import parse_choice_arg, parse_search_term

    page, per_page = parse_pagination()

    # An unknown risk_level is treated as "no filter" rather than an error, so
    # a bookmarked URL holding a stale value still shows the user their history.
    risk_level = parse_choice_arg("risk_level", tuple(RISK_LEVELS))
    search = parse_search_term()
    sort = parse_choice_arg("sort", ("newest", "oldest", "confidence"), "newest")

    items, meta = list_user_predictions(
        page, per_page, risk_level=risk_level, search=search, sort=sort
    )
    # Echo the applied filters so the UI renders its state from the server's
    # answer instead of assuming everything it sent was understood.
    meta["filters"] = {"risk_level": risk_level, "search": search, "sort": sort}
    return success_response(data=items, meta=meta)


@predictions_bp.get("/history")
def prediction_history():
    """Paginated prediction history for the authenticated user only.

    Query parameters, all optional:

        page        1-based page number (default 1)
        per_page    records per page, clamped to 1..100 (default 20)
        risk_level  safe | moderate | unsafe
        search      matches the verdict or any recorded parameter reading
        sort        newest (default) | oldest | confidence

    The account is resolved by the one shared rule in `app.services.identity`
    (a valid token means that account, no token means the shared visitor) and
    never from the request, so this can only ever return rows the caller owns.
    Filters run in SQL, so they cover the whole history rather than just the page
    being viewed.

    Responses: 200 with `data` and pagination `meta`. No token is required.
    """
    try:
        return _history_payload()
    except AquaGuardError as exc:
        return error_response(exc.message, exc.status_code, exc.errors)


@predictions_bp.get("")
def list_predictions():
    """Return the caller's predictions, newest first."""
    try:
        return _history_payload()
    except AquaGuardError as exc:
        return error_response(exc.message, exc.status_code, exc.errors)


@predictions_bp.get("/latest")
def latest_prediction():
    """Return the most recent prediction, or null when there is none yet."""
    try:
        from app.services.prediction_service import get_latest_prediction

        return success_response(data=get_latest_prediction())
    except AquaGuardError as exc:
        return error_response(exc.message, exc.status_code, exc.errors)


@predictions_bp.get("/counts")
def prediction_counts():
    """The caller's verdict counts, counted from the real stored records.

    Powers the Reports page's filter chips (All / Safe / Moderate / Unsafe).
    The numbers are grouped and counted in SQL against the caller's OWN rows,
    so they describe the whole history rather than a fetched page, and they can
    never be a hard-coded or browser-computed figure.
    """
    try:
        from app.services.prediction_service import get_prediction_counts
        return success_response(data=get_prediction_counts())
    except AquaGuardError as exc:
        return error_response(exc.message, exc.status_code, exc.errors)


@predictions_bp.get("/stats")
def prediction_stats():
    """Aggregated stats powering the dashboard cards and Recharts panels."""
    try:
        from app.services.prediction_service import get_prediction_stats

        return success_response(data=get_prediction_stats(request.args.get("range", "30d")))
    except AquaGuardError as exc:
        return error_response(exc.message, exc.status_code, exc.errors)


@predictions_bp.get("/<int:prediction_id>")
def get_prediction(prediction_id: int):
    """Return one prediction the caller owns."""
    try:
        from app.services.prediction_service import get_prediction_by_id

        return success_response(data=get_prediction_by_id(prediction_id))
    except AquaGuardError as exc:
        return error_response(exc.message, exc.status_code, exc.errors)


@predictions_bp.delete("/<int:prediction_id>")
def delete_prediction(prediction_id: int):
    """Delete one of the caller's predictions."""
    try:
        from app.services.prediction_service import delete_prediction as delete

        delete(prediction_id)
        return success_response(message="Prediction deleted")
    except AquaGuardError as exc:
        return error_response(exc.message, exc.status_code, exc.errors)
