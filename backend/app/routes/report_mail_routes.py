"""Reports to Mail — the authenticated REST endpoint that emails report attachments.

    POST /api/v1/reports/mail

Body:

    email           the recipient address (validated server-side)
    option          REPORT_PDF | REPORT_CSV | ALL_PDF | ALL_CSV
    prediction_id   REQUIRED for the two single-report options; the numeric id
                    of the report to attach. OWNERSHIP IS VERIFIED IN SQL — the
                    value from the frontend is only a pointer, never proof.

Responses:

    200  the mail provider ACCEPTED the message (`status: "sent"`), with the
         attachment's name and size echoed back
    400  the body is missing or not valid JSON
    404  the referenced report does not exist OR does not belong to the caller's
         account (both are the same answer, so ids cannot be probed) — or the ALL
         options were requested for an account with no reports
    422  an unknown option, a missing/malformed prediction_id, or an invalid
         recipient address
    502  the attachment could not be generated
    503/502  the mail provider refused or could not be reached — the transport's
         own detail is passed through, and success is NEVER claimed for these
"""

from io import BytesIO

from flask import Blueprint, request, send_file

from app.utils.errors import AquaGuardError, NotFoundError
from app.utils.responses import error_response, success_response

report_mail_bp = Blueprint("report_mail", __name__)


@report_mail_bp.get("/pdf/<int:prediction_id>")
def download_report_pdf(prediction_id: int):
    """Download ONE report as a PDF built by the SAME generator the mail uses.

    THE ONE-GENERATOR RULE. The brief requires that a downloaded report and an
    emailed one carry identical data, timestamp, formatting and watermark. That
    is only guaranteed when both come from `build_pdf` — the server-side
    generator the mail attachment is built with. The browser download used to
    re-derive its own PDF in jsPDF, which drifted: a second layout, a second
    timestamp formatting path and a second watermark implementation.

    OWNERSHIP, SAME AS THE MAIL ROUTE: the id from the URL is only a pointer,
    and the lookup is filtered by the caller's resolved account in SQL — someone
    else's id is indistinguishable from a missing one (both 404).
    """
    from flask import current_app

    from app.extensions import db
    from app.models import WaterPrediction
    from app.services.identity import current_user_id
    from app.services.report_mail_service import _report_id, build_pdf
    from sqlalchemy import select

    user_id = current_user_id()
    prediction = db.session.execute(
        select(WaterPrediction).where(
            WaterPrediction.id == prediction_id,
            WaterPrediction.user_id == user_id,
        )
    ).scalar_one_or_none()
    if prediction is None:
        raise NotFoundError("Report not found")

    try:
        pdf_bytes = build_pdf([prediction], "Single reading report")
    except Exception:  # noqa: BLE001 — a generation crash is a 502, not a 500 lie
        current_app.logger.exception("Report PDF generation failed for id=%s", prediction_id)
        return error_response(
            "The report could not be generated. Please try again.", 502
        )

    filename = f"aquaguard-report-{_report_id(prediction)}.pdf"
    current_app.logger.info(
        "Report PDF downloaded: id=%s user=%s (%d bytes)",
        prediction_id, user_id, len(pdf_bytes),
    )
    return send_file(
        BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename,
    )


@report_mail_bp.get("/pdf")
def download_all_reports_pdf():
    """Download EVERY report the caller owns as one PDF.

    SAME GENERATOR AS EVERYTHING ELSE. This calls the very `build_pdf` the mail
    attachment uses, with the caller's own rows, so a bulk download and an
    emailed ALL_PDF are produced by one function and cannot drift in layout,
    timestamp or watermark.

    OWNERSHIP is resolved through the one shared rule in `app.services.identity`
    and applied in SQL, so the document can only ever contain rows the caller
    owns — never another account's readings.

    The response carries the same ordering the page shows (newest first), so the
    PDF and the reports list describe the records in the same order.
    """
    from flask import current_app

    from app.extensions import db
    from app.models import WaterPrediction
    from app.services.identity import current_user_id
    from app.services.report_mail_service import MAX_REPORTS_PER_EXPORT, build_pdf
    from sqlalchemy import select

    user_id = current_user_id()
    predictions = list(
        db.session.execute(
            select(WaterPrediction)
            .where(WaterPrediction.user_id == user_id)
            .order_by(WaterPrediction.created_at.desc(), WaterPrediction.id.desc())
        ).scalars()
    )
    if not predictions:
        raise NotFoundError("You have no reports to download yet")

    # The same ceiling the mail export applies, for the same reason: one request
    # must not build an unbounded document. The most recent N are included.
    if len(predictions) > MAX_REPORTS_PER_EXPORT:
        predictions = predictions[:MAX_REPORTS_PER_EXPORT]

    try:
        pdf_bytes = build_pdf(
            predictions,
            f"{len(predictions)} reading{'s' if len(predictions) != 1 else ''}",
        )
    except Exception:  # noqa: BLE001 — a generation crash is a 502, not a 500 lie
        current_app.logger.exception("All-reports PDF generation failed user=%s", user_id)
        return error_response(
            "The reports could not be generated. Please try again.", 502
        )

    filename = "aquaguard-reports-all.pdf"
    current_app.logger.info(
        "All-reports PDF downloaded: user=%s rows=%d (%d bytes)",
        user_id, len(predictions), len(pdf_bytes),
    )
    return send_file(
        BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename,
    )


@report_mail_bp.post("/mail")
def mail_reports():
    """Email the caller's own report(s) as an attachment to a given address.

    NO TOKEN IS REQUIRED: the application is open, so "the caller's reports" is
    whatever account the request resolves to (`app.services.identity`).

    Flow, in order:

        request -> body validation -> option validation
                -> ownership-verified report lookup (SQL, against the resolved id)
                -> attachment generation (PDF or CSV, real data)
                -> SMTP send through the shared mail transport
                -> 200 ONLY when the provider accepted the message

    Every failure mode maps to the status code documented in the module header,
    and the response body says WHAT failed — generation and sending are
    reported separately, because they fail for different reasons and the user
    needs to know which one it was.
    """
    if not request.is_json:
        return error_response("Request body must be JSON", 400)

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return error_response("Request body must be a JSON object", 400)

    try:
        from app.services.report_mail_service import send_reports_mail

        outcome = send_reports_mail(payload)
    except AquaGuardError as exc:
        return error_response(exc.message, exc.status_code, exc.errors)
    except Exception:  # noqa: BLE001 — a generation crash is a 502, not a 500 lie
        from flask import current_app

        current_app.logger.exception("Reports to Mail: attachment generation failed")
        return error_response(
            "The report attachment could not be generated. Please try again.",
            502,
        )

    # SUCCESS MEANS THE PROVIDER ACCEPTED THE MAIL. Anything else — suppressed,
    # disabled, unconfigured, refused — is reported honestly and distinctly
    # rather than dressed up as success.
    if outcome["status"] == "sent":
        return success_response(
            data={
                "sent": True,
                "recipient": outcome["recipient"],
                "option": outcome["option"],
                "reports_included": outcome["reports_included"],
                "attachment_name": outcome["attachment_name"],
                "attachment_size": outcome["attachment_size"],
            },
            message=f"Report emailed to {outcome['recipient']}",
        )

    # The transport refused or was not allowed to run. Map its own status to a
    # status code the client can distinguish: configuration problems are 503,
    # provider refusals are 502.
    transport_status = outcome["status"]
    if transport_status in ("disabled", "unconfigured", "suppressed"):
        code = 503
        message = (
            "Email sending is not available right now"
            + (f" ({transport_status})" if transport_status != "suppressed" else "")
        )
    else:
        code = 502
        message = outcome["detail"] or "The email could not be sent"
    return error_response(message, code, {"status": transport_status})
