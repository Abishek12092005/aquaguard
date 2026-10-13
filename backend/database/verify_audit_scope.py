"""Verifies the audit's STATE/COUNTRY SCOPE enforcement (PROMPT 12 requirement 6).

When the console has configured a location scope, out-of-scope audit rows must
be withheld entirely - not shown with the location blanked, which would leak
which locations exist. Rows with NO recorded location are always shown, because
"Location unavailable" is the honest answer for them.

    python database/verify_audit_scope.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DB_PATH = Path(tempfile.gettempdir()) / f"audit_scope_{uuid.uuid4().hex[:8]}.db"
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402


def main() -> int:
    app = create_app("testing")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}"
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {}

    results: list[bool] = []

    def check(label: str, condition: bool, detail: str = "") -> None:
        results.append(condition)
        print(f"{'PASS' if condition else 'FAIL'}  {label}" + (f"  -> {detail}" if detail else ""))

    with app.app_context():
        db.drop_all()
        db.create_all()

        from app.models import ReportEmailAudit
        from app.models.mixins import utcnow
        from app.services import admin_service
        from app.services.admin_service import list_report_email_audits

        def seed(tag: str, **location) -> str:
            email = f"{tag}_{uuid.uuid4().hex[:8]}@example.test"
            db.session.add(ReportEmailAudit(
                recipient_email=email,
                report_option="REPORT_PDF",
                delivery_status="sent",
                created_at=utcnow(),
                **location,
            ))
            db.session.commit()
            return email

        in_scope = seed("tn", location_source="browser", location_state="Tamil Nadu")
        other = seed("kl", location_source="browser", location_state="Kerala")
        unknown = seed("none")

        # No scope configured: everything is visible.
        items, meta = list_report_email_audits(per_page=50)
        check("no scope shows every row", len(items) == 3, f"got {len(items)}")
        check("no scope reports no scope mode", meta["scope"]["mode"] is None)

        # Configure a STATE scope, as the console's Location access tab does.
        original_getter = admin_service.get_location_scope
        admin_service.get_location_scope = lambda: {
            "mode": "state", "state": "Tamil Nadu", "country": None,
        }
        try:
            items, meta = list_report_email_audits(per_page=50)
            emails = {i["recipient_email"] for i in items}
            check("in-scope row is kept", in_scope in emails)
            check("out-of-scope row is withheld", other not in emails)
            check("row with no location is still shown", unknown in emails)
            check("scope mode is reported to the UI", meta["scope"]["mode"] == "state")

            # A COUNTRY scope behaves the same way.
            admin_service.get_location_scope = lambda: {
                "mode": "country", "state": None, "country": "India",
            }
            items, meta = list_report_email_audits(per_page=50)
            emails = {i["recipient_email"] for i in items}
            check("country scope keeps an Indian row", in_scope in emails)
            check("country scope reports its mode", meta["scope"]["mode"] == "country")
        finally:
            admin_service.get_location_scope = original_getter

        db.session.remove()
        db.drop_all()

    DB_PATH.unlink(missing_ok=True)
    passed = sum(1 for r in results if r)
    print(f"\n{passed}/{len(results)} checks passed.")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())