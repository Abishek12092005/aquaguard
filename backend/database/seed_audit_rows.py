"""Seeds REAL report-email audit rows by calling the live /reports/mail endpoint.

Nothing is written directly: each row is produced by the actual Reports-to-Mail
flow, so what the admin page then shows is what a real request records - the
transport's own verdict included.

    python database/seed_audit_rows.py

FOR LOCAL UI VERIFICATION ONLY. It forces MAIL_SUPPRESS_SEND on, so no message
is ever actually sent - the rows carry an honest "suppressed" verdict rather
than a faked "sent".
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app
from app.extensions import db

app = create_app("development")

# Force a real attempt that the transport refuses on purpose, so the audit gains
# rows without emailing anyone.
app.config["MAIL_SUPPRESS_SEND"] = True
app.config["MAIL_ENABLED"] = True
app.config["MAIL_USERNAME"] = "seed@example.test"
app.config["MAIL_PASSWORD"] = "seed"


def main() -> int:
    with app.app_context():
        db.create_all()

        from app.models import WaterPrediction
        from app.services.identity import current_user_id

        owner = current_user_id()
        prediction = db.session.query(WaterPrediction).filter_by(user_id=owner).first()
        prediction_id = prediction.id if prediction is not None else None

    # One case per location behaviour the audit must distinguish.
    cases = [
        {
            "email": "farmer.karaikudi@example.com",
            "option": "ALL_CSV",
            "device_label": "Windows · Chrome",
            # Consent GRANTED: a place the requester's own device provided.
            "device_location": {
                "source": "browser",
                "name": "Karaikudi",
                "city": "Karaikudi",
                "state": "Tamil Nadu",
                "country": "India",
                "pincode": "630003",
            },
        },
        {
            "email": "field.survey@example.net",
            "option": "ALL_PDF",
            "device_label": "Android · Chrome",
            # Consent GRANTED but fewer fields resolved.
            "device_location": {"source": "browser", "city": "Chennai", "state": "Tamil Nadu"},
        },
        {
            "email": "lab.manager@example.org",
            "option": "ALL_CSV",
            "device_label": "macOS · Safari",
            # NO device_location: permission declined -> "Location unavailable".
        },
        {
            "email": "unknown.person@example.com",
            "option": "ALL_CSV",
            "device_label": "Linux · Firefox",
            # A source the system never legitimately obtained -> must be dropped.
            "device_location": {"source": "ip-geolocation", "city": "Guessed City"},
        },
    ]

    if prediction_id is not None:
        cases.append({
            "email": "single.report@example.com",
            "option": "REPORT_PDF",
            "prediction_id": prediction_id,
            "device_label": "Windows · Edge",
            "device_location": {"source": "browser", "city": "Madurai", "state": "Tamil Nadu"},
        })

    client = app.test_client()
    for case in cases:
        response = client.post("/api/v1/reports/mail", json=case)
        print(f"  {case['email']:<34} -> HTTP {response.status_code}")

    with app.app_context():
        from app.models import ReportEmailAudit

        rows = (
            db.session.query(ReportEmailAudit)
            .order_by(ReportEmailAudit.id.desc())
            .limit(10)
            .all()
        )
        print(f"\n{len(rows)} audit row(s) now recorded (newest first):")
        for row in rows:
            place = row.location_name or row.location_city or "Location unavailable"
            print(
                f"  {row.recipient_email:<34} {row.report_option:<11} "
                f"{row.delivery_status:<12} loc={row.location_source or '-'}/{place}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())