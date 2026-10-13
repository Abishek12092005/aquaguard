"""Standalone verification of the report-email audit (PROMPT 12).

Runs against its own throwaway SQLite file rather than the shared MySQL test
database, because that database is missing columns added by earlier prompts and
repairing it needs a MySQL root credential this session does not hold.

Verifies, against real code paths:
  1. _record_audit stores recipient / option / status / requester / device;
  2. a "browser" consented location is stored at place granularity;
  3. any other location source is DROPPED, not stored;
  4. no consented location -> every location column NULL;
  5. list_report_email_audits filters by option and status, and paginates;
  6. the location payload is marked available=false when nothing was consented.

    python database/verify_report_email_audit.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DB_PATH = Path(tempfile.gettempdir()) / f"audit_verify_{uuid.uuid4().hex[:8]}.db"
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402


def check(label: str, condition: bool, detail: str = "") -> bool:
    print(f"{'PASS' if condition else 'FAIL'}  {label}" + (f"  -> {detail}" if detail else ""))
    return condition


def main() -> int:
    app = create_app("testing")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}"
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {}

    with app.app_context():
        db.drop_all()
        db.create_all()

        from app.models import ReportEmailAudit
        from app.services.admin_service import list_report_email_audits
        from app.services.report_mail_service import _record_audit

        results = []

        # --- 1. A plain attempt, no consented location ----------------------
        recipient = f"owner_{uuid.uuid4().hex[:8]}@example.test"
        _record_audit(
            recipient=recipient,
            option="REPORT_PDF",
            status="sent",
            reports_included=1,
            user_id=None,
            payload={"device_label": "Windows \u00b7 Chrome"},
        )
        row = db.session.query(ReportEmailAudit).filter_by(
            recipient_email=recipient
        ).one()
        results.append(check("records recipient", row.recipient_email == recipient))
        results.append(check("records report type", row.report_option == "REPORT_PDF"))
        results.append(check("records delivery status", row.delivery_status == "sent"))
        results.append(check("records request timestamp", row.created_at is not None))
        results.append(check("records device label", row.device_label == "Windows \u00b7 Chrome"))
        results.append(
            check(
                "no location fields without consent",
                all(
                    getattr(row, f"location_{f}") is None
                    for f in ("name", "city", "state", "country", "pincode", "source")
                ),
            )
        )
        # Requirement 8: the transport's own verdict, stored verbatim.
        results.append(check("no password/token columns on the model",
                             not any(
                                 c.name in {"password", "token", "attachment"}
                                 for c in ReportEmailAudit.__table__.columns
                             )))

        # --- 2. A consented browser location is stored ----------------------
        consented = f"consented_{uuid.uuid4().hex[:8]}@example.test"
        _record_audit(
            recipient=consented,
            option="ALL_CSV",
            status="suppressed",
            reports_included=7,
            user_id=None,
            payload={
                "device_location": {
                    "source": "browser",
                    "name": "Karaikudi",
                    "city": "Karaikudi",
                    "state": "Tamil Nadu",
                    "country": "India",
                    "pincode": "630003",
                }
            },
        )
        row2 = db.session.query(ReportEmailAudit).filter_by(
            recipient_email=consented
        ).one()
        results.append(check("stores consented location_source", row2.location_source == "browser"))
        results.append(check("stores consented place name", row2.location_name == "Karaikudi"))
        results.append(check("stores consented state", row2.location_state == "Tamil Nadu"))
        results.append(check("stores consented pincode", row2.location_pincode == "630003"))

        # --- 3. A non-consented source is refused ---------------------------
        guessed = f"guessed_{uuid.uuid4().hex[:8]}@example.test"
        _record_audit(
            recipient=guessed,
            option="REPORT_CSV",
            status="failed",
            reports_included=1,
            user_id=None,
            payload={
                "device_location": {
                    "source": "ip-geolocation",
                    "city": "Invented City",
                }
            },
        )
        row3 = db.session.query(ReportEmailAudit).filter_by(
            recipient_email=guessed
        ).one()
        results.append(check("refuses non-browser location source", row3.location_source is None))
        results.append(check("refuses the guessed city itself", row3.location_city is None))

        # --- 4. A bare "browser" tag with no place is not a claim ----------
        bare = f"bare_{uuid.uuid4().hex[:8]}@example.test"
        _record_audit(
            recipient=bare,
            option="REPORT_PDF",
            status="unconfigured",
            reports_included=1,
            user_id=None,
            payload={"device_location": {"source": "browser"}},
        )
        row4 = db.session.query(ReportEmailAudit).filter_by(
            recipient_email=bare
        ).one()
        results.append(check("bare browser tag stores no source", row4.location_source is None))

        # --- 5. The admin listing: filters, pagination, location payload -----
        items, meta = list_report_email_audits(per_page=50)
        results.append(check("lists every recorded row", len(items) == 4, f"got {len(items)}"))
        by_email = {i["recipient_email"]: i for i in items}
        results.append(
            check(
                "unconsented row reports location unavailable",
                by_email[recipient]["location"]["available"] is False,
            )
        )
        results.append(
            check(
                "consented row reports location available",
                by_email[consented]["location"]["available"] is True,
            )
        )
        results.append(
            check(
                "consented row exposes place, not coordinates",
                by_email[consented]["location"]["state"] == "Tamil Nadu"
                and "lat" not in by_email[consented]["location"],
            )
        )
        results.append(
            check(
                "payload carries no report contents or secrets",
                not any(
                    key in by_email[recipient]
                    for key in ("ph", "turbidity", "password", "token", "attachment")
                ),
            )
        )

        items, meta = list_report_email_audits(option="REPORT_PDF")
        results.append(
            check("option filter applies", {i["report_option"] for i in items} == {"REPORT_PDF"})
        )
        items, _ = list_report_email_audits(status="failed")
        results.append(
            check("status filter applies", {i["delivery_status"] for i in items} == {"failed"})
        )
        items, _ = list_report_email_audits(search="Karaikudi")
        results.append(
            check("search matches a consented location", len(items) == 1, f"got {len(items)}")
        )
        items, _ = list_report_email_audits(start="not-a-date")
        results.append(
            check("a malformed date is ignored, not fatal", len(items) == 4, f"got {len(items)}")
        )

        items, meta = list_report_email_audits(page=1, per_page=2)
        results.append(check("pagination limits the page", len(items) == 2, f"got {len(items)}"))
        results.append(check("pagination reports total", meta["total"] == 4, f"total={meta['total']}"))
        results.append(check("pagination reports page count", meta["pages"] == 2))
        items2, meta2 = list_report_email_audits(page=2, per_page=2)
        results.append(
            check("second page returns the remainder", len(items2) == 2, f"got {len(items2)}")
        )

        db.session.remove()
        db.drop_all()

    DB_PATH.unlink(missing_ok=True)
    passed = sum(1 for r in results if r)
    print(f"\n{passed}/{len(results)} checks passed.")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())