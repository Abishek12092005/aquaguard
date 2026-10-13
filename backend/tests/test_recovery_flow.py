"""Prompt 9 end-to-end checks: forgot password with OTP, and verified email management."""
import hashlib
import os
import tempfile

_TMPDIR = tempfile.mkdtemp(prefix="aquaguard-recovery-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMPDIR, 'test.db')}"
os.environ["SECRET_KEY"] = "recovery-check-key-not-real-0123456789abcdef"
os.environ["MAIL_SUPPRESS_SEND"] = "1"

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402

app = create_app()

with app.app_context():
    bound = str(db.engine.url)
    assert _TMPDIR in bound, f"engine bound to {bound}"
    db.create_all()
    from app.models.admin_login_approval import AdminLoginApproval
    from app.services import admin_service as A, console_session
    from app.services import login_approval_service as L

    client = app.test_client()
    errors = []

    def check(name, condition, detail=""):
        print(("  PASS " if condition else "  FAIL ") + name + (f"  [{detail}]" if detail and not condition else ""))
        if not condition:
            errors.append(name)

    def plant_code(code, expires=9999999999):
        row = A.get_settings().get_reset_code()
        row["code_hash"] = hashlib.sha256(code.encode()).hexdigest()
        row["expires_at"] = expires
        A.get_settings().set_reset_code(row)
        db.session.commit()

    def clear_cooldown():
        """Backdate the last issue so the 60s cooldown does not gate the test."""
        row = A.get_settings().get_reset_code()
        if row:
            row["issued_at"] = 0
            row["issued_history"] = [t - 7200 for t in (row.get("issued_history") or [0])]
            A.get_settings().set_reset_code(row)
            db.session.commit()

    def unlock_console():
        real = L.create_request
        box = {}
        def spy(*a, **k):
            row, t = real(*a, **k); box["t"] = t; return row, t
        L.create_request = spy
        ch = client.get("/api/admin/session/challenge").get_json()["data"]["challenge"]
        client.post("/api/admin/session", json={"password": "NewStrong1", "challenge": ch})
        L.create_request = real
        latest = AdminLoginApproval.query.order_by(AdminLoginApproval.id.desc()).first()
        client.post(f"/api/admin/session/approval/{latest.request_id}/decide", json={"action": "approve", "token": box["t"]})
        client.post(f"/api/admin/session/approval/{latest.request_id}/consume", json={"challenge": ch})

    print("== forgot password with OTP ==")
    r = client.post("/api/admin/password/forgot")
    check("forgot returns 200", r.status_code == 200, str(r.get_json()))
    d = r.get_json()["data"]
    check("recipient masked", "***" in d["sent_to"], d["sent_to"])
    check("plain code not in response", "code" not in d)
    try:
        A.issue_reset_code()
        check("resend cooldown enforced", False)
    except Exception as e:
        check("resend cooldown enforced", "recently" in str(e))
    check("no plain code stored at rest", "code_hash" in (A.get_settings().get_reset_code() or {}))

    for i in range(5):
        A.verify_reset_code(f"00000{i}")
    check("5 wrong attempts burn the code", not A.get_settings().get_reset_code().get("code_hash"))
    check("burned code verifies False", A.verify_reset_code("123456") is False)

    clear_cooldown()
    A.issue_reset_code()
    plant_code("654321")
    r = client.post("/api/admin/password/reset", json={"code": "654321", "new_password": "weak"})
    check("weak password refused (422)", r.status_code == 422, str(r.status_code))
    r = client.post("/api/admin/password/reset", json={"code": "654321", "new_password": "NewStrong1"})
    check("reset with valid OTP succeeds", r.status_code == 200, str(r.get_json()))
    check("OTP invalidated after reset", not A.get_settings().get_reset_code().get("code_hash"))
    check("console locked after reset", not console_session.is_unlocked())
    r = client.post("/api/admin/password/reset", json={"code": "654321", "new_password": "NewStrong1"})
    check("OTP replay refused", r.status_code in (401, 422), str(r.status_code))
    ch = client.get("/api/admin/session/challenge").get_json()["data"]["challenge"]
    r = client.post("/api/admin/session", json={"password": "NewStrong1", "challenge": ch})
    check("login with NEW password creates approval request", r.status_code == 200)

    print("== email management (authenticated) ==")
    r = client.post("/api/admin/email/change/request", json={"new_email": "x@y.com"})
    check("email change refused when locked (403)", r.status_code == 403, str(r.status_code))
    unlock_console()
    check("console unlocked for settings", console_session.is_unlocked())
    r = client.post("/api/admin/email/change/request", json={"same_as_recovery": True})
    check("same-as-recovery sync works", r.status_code == 200 and r.get_json()["data"]["mode"] == "synced_to_recovery")
    r = client.post("/api/admin/email/change/request", json={"new_email": "newboss@example.com"})
    check("verification code sent to new address", r.status_code == 200 and "***" in r.get_json()["data"]["sent_to"])
    r = client.post("/api/admin/email/change/confirm", json={"code": "111111"})
    check("wrong code refused (422)", r.status_code == 422)
    s = A.get_settings(); p = s.get_unlock_confirmation()
    p["email_change"]["code_hash"] = hashlib.sha256(b"246810").hexdigest()
    s.set_unlock_confirmation(p); db.session.commit()
    r = client.post("/api/admin/email/change/confirm", json={"code": "246810"})
    check("correct code activates change", r.status_code == 200)
    check("approval email updated to verified address", A.get_settings().get_admin_approval_email() == "newboss@example.com")
    r = client.post("/api/admin/email/change/confirm", json={"code": "246810"})
    check("email-change code single use", r.status_code == 422, str(r.status_code))

    print()
    if errors:
        print("FAILED:", errors)
        raise SystemExit(1)
    print("ALL RECOVERY CHECKS PASSED")


def test_recovery_flow():
    """Pytest entry point for the checks above.

    This module is a script that ran at import time, which made pytest collect
    NOTHING from it -- the whole flow was silently not part of the suite (and
    re-ran from scratch on every import). The checks live in the module body so
    they keep working when the file is executed directly, and this wrapper makes
    the outcome a real test result: pytest now reports it as one passing (or
    failing) node instead of an empty collection.
    """
    assert not errors, f"recovery flow failed: {errors}"
