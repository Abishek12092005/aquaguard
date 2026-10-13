"""Verifies the audit endpoint's ADMIN GATE (PROMPT 12 requirement 6).

The console must refuse the audit page while locked, and serve it once
unlocked. Run against a throwaway SQLite database:

    python database/verify_audit_endpoint_auth.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DB_PATH = Path(tempfile.gettempdir()) / f"audit_auth_{uuid.uuid4().hex[:8]}.db"
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

        db.session.add(ReportEmailAudit(
            recipient_email=f"gate_{uuid.uuid4().hex[:8]}@example.test",
            report_option="REPORT_PDF",
            delivery_status="sent",
            created_at=utcnow(),
        ))
        db.session.commit()

        client = app.test_client()

        # LOCKED: the read verb must be refused with 403, and the state-changing
        # verbs with 405 — the route is READ-ONLY, so there is no verb of it that
        # could change anything. Either way nothing may leak.
        response = client.get("/api/admin/report-email-audit")
        check(
            "locked console refuses GET with 403",
            response.status_code == 403,
            f"got {response.status_code}",
        )
        check("locked GET refusal leaks no audit data", b"gate_" not in response.data)

        for method in ("post", "put", "delete", "patch"):
            response = getattr(client, method)("/api/admin/report-email-audit")
            check(
                f"route has no {method.upper()} (405)",
                response.status_code == 405,
                f"got {response.status_code}",
            )
            check(
                f"{method.upper()} refusal leaks no audit data",
                b"gate_" not in response.data,
            )

        # UNLOCKED: the same endpoint now serves the records.
        from app.services.console_session import unlock

        unlock()
        response = client.get("/api/admin/report-email-audit")
        check("unlocked console serves the audit", response.status_code == 200, f"got {response.status_code}")
        body = response.get_json() or {}
        rows = (body.get("data") or [])
        check("unlocked response includes the recorded row", any("gate_" in r.get("recipient_email", "") for r in rows))
        check("response carries pagination meta", isinstance(body.get("meta"), dict))

        from app.services.console_session import lock

        lock()
        response = client.get("/api/admin/report-email-audit")
        check("locking again re-refuses the endpoint", response.status_code == 403, f"got {response.status_code}")

        db.session.remove()
        db.drop_all()

    DB_PATH.unlink(missing_ok=True)
    passed = sum(1 for r in results if r)
    print(f"\n{passed}/{len(results)} checks passed.")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())