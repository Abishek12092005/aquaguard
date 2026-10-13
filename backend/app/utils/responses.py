"""Uniform JSON response envelopes.

Every endpoint returns the same top-level shape so the Axios layer and the
React error handling can stay generic:

    { "success": true,  "message": "...", "data": {...}, "meta": {...} }
    { "success": false, "message": "...", "errors": {...} }
"""

from typing import Any, Mapping

from flask import jsonify


def success_response(
    data: Any = None,
    message: str = "OK",
    status_code: int = 200,
    meta: Mapping[str, Any] | None = None,
):
    """Build a successful response."""
    payload: dict[str, Any] = {"success": True, "message": message, "data": data}
    if meta is not None:
        payload["meta"] = dict(meta)
    return jsonify(payload), status_code


def error_response(
    message: str = "Something went wrong",
    status_code: int = 400,
    errors: Any = None,
):
    """Build a failure response."""
    payload: dict[str, Any] = {"success": False, "message": message}
    if errors is not None:
        payload["errors"] = errors
    return jsonify(payload), status_code
