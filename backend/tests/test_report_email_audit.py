"""PROMPT 12 — the report-email audit trail, end to end.

Covers the three things the brief's acceptance criteria name:

  1. a real Reports-to-Mail attempt is recorded (recipient, option, timestamp,
     delivery verdict, requester identity);
  2. the admin endpoint serves those records, paged and filtered, behind the
     console unlock;
  3. location is stored ONLY when the request explicitly carries a consented
     "browser" location, and "Location unavailable" (a null location) is what
     an unconsented request produces — never a guessed place.
"""

import uuid

import pytest


def _unique_email() -> str:
    return f"audit_{uuid.uuid4().hex[:10]}@aquaguard.test"


def _mail_payload(**overrides) -> dict:
    """A valid /reports/mail body for the ALL_CSV option (no id needed)."""
    payload = {
        "email": _unique_email(),
        "option": "ALL_CSV",
        "device_label": "Windows · Chrome",
    }
    payload.update(overrides)
    return payload


def _seed_row(app, **overrides) -> int:
    """Insert one audit row directly and return its id."""
    from app.extensions import db
    from app.models import ReportEmailAudit
    from app.models.mixins import utcnow

    fields = {
        "recipient_email": _unique_email(),
        "report_option": "REPORT_PDF",
        "delivery_status": "sent",
        "reports_included": 1,
        "user_id": None,
        "requester_name": None,
        "admin_username": None,
        "device_label": "Windows · Chrome",
        "created_at": utcnow(),
    }
    fields.update(overrides)
    row = ReportEmailAudit(**fields)
    db.session.add(row)
    db.session.commit()
    return row.id


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

def test_mail_request_records_audit_row(app, client, app_context, monkeypatch):
    """A real (suppressed-transport) mail attempt writes one audit row."""
    from app.extensions import db
    from app.models import ReportEmailAudit

    # Suppress the transport: the attempt still happens, the verdict is honest.
    from flask import current_app

    monkeypatch.setitem(current_app.config, "MAIL_SUPPRESS_SEND", True)
    monkeypatch.setitem(current_app.config, "MAIL_USERNAME", "tester@example.test")
    monkeypatch.setitem(current_app.config, "MAIL_PASSWORD", "not-a-secret")
    monkeypatch.setitem(current_app.config, "MAIL_ENABLED", True)

    recipient = _unique_email()
    response = client.post(
        "/api/v1/reports/mail", json=_mail_payload(email=recipient)
    )
    # Suppressed send answers 503 — a real attempt, honestly reported.
    assert response.status_code == 503

    row = (
        db.session.query(ReportEmailAudit)
        .filter_by(recipient_email=recipient)
        .one_or_none()
    )
    assert row is not None
    assert row.report_option == "ALL_CSV"
    assert row.delivery_status == "suppressed"
    assert row.created_at is not None
    assert row.device_label == "Windows · Chrome"
    # No consented location was sent: every location field stays NULL.
    assert row.location_source is None
    assert row.location_name is None


def test_mail_request_records_consented_location(app, client, app_context, monkeypatch):
    """An explicitly consented browser location is stored at place level."""
    from app.extensions import db
    from app.models import ReportEmailAudit

    from flask import current_app

    monkeypatch.setitem(current_app.config, "MAIL_SUPPRESS_SEND", True)
    monkeypatch.setitem(current_app.config, "MAIL_USERNAME", "tester@example.test")
    monkeypatch.setitem(current_app.config, "MAIL_PASSWORD", "not-a-secret")
    monkeypatch.setitem(current_app.config, "MAIL_ENABLED", True)

    recipient = _unique_email()
    client.post(
        "/api/v1/reports/mail",
        json=_mail_payload(
            email=recipient,
            device_location={
                "source": "browser",
                "name": "Karaikudi",
                "city": "Karaikudi",
                "state": "Tamil Nadu",
                "country": "India",
                "pincode": "630003",
            },
        ),
    )

    row = db.session.query(ReportEmailAudit).filter_by(
        recipient_email=recipient
    ).one()
    assert row.location_source == "browser"
    assert row.location_state == "Tamil Nadu"
    assert row.location_pincode == "630003"


def test_nonconsented_location_source_is_refused(app, client, app_context, monkeypatch):
    """A location claiming any source but 'browser' is dropped, not stored."""
    from app.extensions import db
    from app.models import ReportEmailAudit

    from flask import current_app

    monkeypatch.setitem(current_app.config, "MAIL_SUPPRESS_SEND", True)
    monkeypatch.setitem(current_app.config, "MAIL_USERNAME", "tester@example.test")
    monkeypatch.setitem(current_app.config, "MAIL_PASSWORD", "not-a-secret")
    monkeypatch.setitem(current_app.config, "MAIL_ENABLED", True)

    recipient = _unique_email()
    client.post(
        "/api/v1/reports/mail",
        json=_mail_payload(
            email=recipient,
            device_location={"source": "ip-geolocation", "city": "Guessed City"},
        ),
    )
    row = db.session.query(ReportEmailAudit).filter_by(
        recipient_email=recipient
    ).one()
    assert row.location_source is None
    assert row.location_city is None


# ---------------------------------------------------------------------------
# The admin endpoint
# ---------------------------------------------------------------------------

def test_audit_endpoint_requires_unlock(app, client):
    """Locked console -> the endpoint answers 403, showing nothing."""
    response = client.get("/api/admin/report-email-audit")
    assert response.status_code == 403


def test_audit_endpoint_lists_and_filters(app, client, unlock_console):
    """Unlocked console: rows are served, filtered, paged, scoped labelled."""
    import json

    with app.app_context():
        own_id = _seed_row(app, admin_username="console-admin")
    unlock_console()

    response = client.get("/api/admin/report-email-audit")
    assert response.status_code == 200
    body = json.loads(response.data)
    items = body.get("data") or []
    ids = {item.get("id") for item in items}
    assert own_id in ids
    assert "meta" in body

    # The delivered shape distinguishes a real location from no location.
    mine = next(item for item in items if item.get("id") == own_id)
    assert mine["location"]["available"] is False

    # Status filter.
    response = client.get(
        "/api/admin/report-email-audit?status=failed"
    )
    items = json.loads(response.data).get("data") or []
    assert all(item["delivery_status"] == "failed" for item in items)

    # Option filter.
    response = client.get(
        "/api/admin/report-email-audit?option=REPORT_PDF"
    )
    items = json.loads(response.data).get("data") or []
    assert all(item["report_option"] == "REPORT_PDF" for item in items)


def test_audit_endpoint_paginates(app, client, unlock_console):
    import json

    unlock_console()
    response = client.get(
        "/api/admin/report-email-audit?page=1&per_page=1"
    )
    assert response.status_code == 200
    body = json.loads(response.data)
    assert len(body.get("data") or []) <= 1
    assert body["meta"]["per_page"] == 1


def test_audit_rows_carry_no_secrets(app, client, unlock_console):
    """Requirement 7: the payload exposes no password, token or report body."""
    import json

    unlock_console()
    response = client.get("/api/admin/report-email-audit")
    text = response.data.decode("utf-8").lower()
    for forbidden in ("password", "token", "ph\"", "turbidity"):
        # "password"/"token" must not appear as field names of any row.
        assert f'"{forbidden}"' not in text
