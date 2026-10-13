"""Seeds enough report-email audit rows to exercise the admin page's pagination.

Goes through the live /reports/mail endpoint so every row is a real recorded
request. FOR LOCAL UI VERIFICATION ONLY - the transport is suppressed, so the
verdicts are honest "suppressed" rows and no mail is ever sent.

    python database/seed_many_audit_rows.py 30
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app

COUNT = int(sys.argv[1]) if len(sys.argv) > 1 else 30

app = create_app("development")
app.config["MAIL_SUPPRESS_SEND"] = True
app.config["MAIL_ENABLED"] = True
app.config["MAIL_USERNAME"] = "seed@example.test"
app.config["MAIL_PASSWORD"] = "seed"


def main() -> int:
    client = app.test_client()
    places = [
        None,
        {"source": "browser", "city": "Karaikudi", "state": "Tamil Nadu"},
        {"source": "browser", "city": "Chennai", "state": "Tamil Nadu"},
        {"source": "browser", "city": "Madurai", "state": "Tamil Nadu"},
    ]
    created = 0
    for i in range(COUNT):
        body = {
            "email": f"bulk.user{i:02d}@example.com",
            "option": "ALL_CSV",
            "device_label": "Windows · Chrome",
        }
        location = places[i % len(places)]
        if location:
            body["device_location"] = location
        if client.post("/api/v1/reports/mail", json=body).status_code in (200, 502, 503):
            created += 1

    print(f"recorded {created} audit row(s)")

    with app.app_context():
        from app.extensions import db
        from app.models import ReportEmailAudit

        print(f"table now holds {db.session.query(ReportEmailAudit).count()} row(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())