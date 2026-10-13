"""Check the refined admin approval email workflow.

The refinement this test pins down is one property, stated as attacks:

  1. The mail's Yes / No links must be INERT. A link scanner, link prefetcher or
     chat-client preview GETs every URL in a message; if that GET decided, the
     scanner would cast the vote. So fetching the links the mail actually sends
     must change NO row and unlock NOTHING.
  2. The two provider-relevant behaviours: the decision requires a POST (JSON or a
     plain form), and the response is served by THIS application (no external
     redirect).
  3. APPROVE through the confirmation step works, and only the sign-in browser can
     spend it.
  4. DENY through the confirmation step works and never grants access.
  5. Replay is refused: a token is single-use.
  6. Nothing that acts is carried in the mail as a plain one-click GET.

**THE DATABASE IS REDIRECTED BEFORE `create_app()`**, exactly as the sibling
approval test does, so this can never write to a real deployment's database.
"""

import os
import re
import tempfile

_TMPDIR = tempfile.mkdtemp(prefix="aquaguard-mail-flow-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMPDIR, 'test.db')}"
os.environ["SECRET_KEY"] = "mail-flow-check-only-key-not-a-real-secret-01234567"
os.environ["MAIL_SUPPRESS_SEND"] = "1"
os.environ.setdefault("FLASK_ENV", "development")

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402

app = create_app()
app.config["MAIL_SUPPRESS_SEND"] = True
app.config["ADMIN_PASSWORD"] = "correct-horse-battery-staple"

with app.app_context():
    bound = str(db.engine.url)
    assert _TMPDIR in bound, f"refusing to run: engine bound to {bound}"
    print("engine bound to the temporary database:", bound, "\n")
    db.create_all()

    from app.models.admin_login_approval import AdminLoginApproval
    from app.models.admin_settings import AdminSettings
    from app.services import admin_service, console_session, login_approval_service as approvals
    from app.services import mail_service

    settings = db.session.get(AdminSettings, 1) or AdminSettings(id=1)
    if settings not in db.session:
        db.session.add(settings)
    settings.admin_username = "abishek"
    settings.admin_email = "admin@aquaguard.test"
    settings.admin_approval_email = "security@aquaguard.test"
    db.session.commit()

    # Seed the console credential through the real reset path.
    admin_service.issue_reset_code()
    code = ""
    for message in reversed(mail_service.SUPPRESSED_MESSAGES):
        if "reset code" in message.get("Subject", "").lower():
            body = message.get_body(preferencelist=("plain",)).get_content()
            m = re.search(r"\b\d{6}\b", body)
            code = m.group(0) if m else ""
            break
    assert code, "no reset code was built"
    admin_service.reset_admin_password(code=code, new_password="CorrectHorse1")
    print("console credential seeded\n")

    client = app.test_client()

    def challenge() -> str:
        return client.get("/api/admin/session/challenge").get_json()["data"]["challenge"]

    def sign_in(chal: str):
        return client.post(
            "/api/admin/session",
            json={"username": "abishek", "password": "CorrectHorse1", "challenge": chal},
        )

    # Capture the mail token the way an inbox would: wrap the one place the clear
    # value is generated.
    TOKENS: dict[str, str] = {}
    real_create = approvals.create_request

    def spy(*args, **kwargs):
        row, token = real_create(*args, **kwargs)
        TOKENS[row.request_id] = token
        return row, token

    approvals.create_request = spy

    def latest_mail():
        """The approval message the service actually built (suppression sink)."""
        for message in reversed(mail_service.SUPPRESSED_MESSAGES):
            if "login request" in message.get("Subject", "").lower():
                return message
        return None

    # ---------------------------------------------------------------- 1
    print("== 1. the links the mail ACTUALLY sends are inert on GET ==")
    chal = challenge()
    request_id = sign_in(chal).get_json()["data"]["request_id"]
    token = TOKENS[request_id]

    message = latest_mail()
    assert message is not None, "no approval mail was built"
    body = message.get_body(preferencelist=("plain",)).get_content()

    # Recover the two action links from the message text, as a scanner would.
    approve_link = re.search(r"Approve Access:\s*(\S+)", body)
    deny_link = re.search(r"Deny Access:\s*(\S+)", body)
    assert approve_link and deny_link, f"decision links not found in the mail:\n{body}"
    approve_path = approve_link.group(1).split("localhost:5000")[-1]
    deny_path = deny_link.group(1).split("localhost:5000")[-1]
    print("  approve link path :", approve_path.split("token=")[0] + "token=<redacted>")
    print("  deny link path    :", deny_path.split("token=")[0] + "token=<redacted>")

    # THE ATTACK: a scanner follows BOTH links with plain GETs.
    before = AdminLoginApproval.query.filter_by(request_id=request_id).first().status
    g1 = client.get(approve_path)
    g2 = client.get(deny_path)
    row = AdminLoginApproval.query.filter_by(request_id=request_id).first()
    print("  GET approve       :", g1.status_code, "| row:", row.status)
    print("  GET deny          :", g2.status_code, "| row:", row.status)
    print("  console unlocked  :", console_session.is_unlocked())
    assert g1.status_code == 200 and g2.status_code == 200
    assert row.status == before == "pending", "a scanner GET must not decide anything"
    assert console_session.is_unlocked() is False, "a scanner GET must not unlock the console"
    # And the mail does NOT carry a one-click GET that decides (the old `/mail`
    # endpoint), so there is nothing for a scanner to trigger.
    assert "/mail?action=" not in body, "the mail must not carry an auto-deciding link"
    print("  -> following the links decides nothing\n")

    # ---------------------------------------------------------------- 2
    print("== 2. the decision requires a POST; GET on decide is refused ==")
    decide_path = approve_path.split("?")[0].replace("/review", "/decide")
    get_decide = client.get(decide_path)
    print("  GET  decide       :", get_decide.status_code, "(405, POST only)")
    row = AdminLoginApproval.query.filter_by(request_id=request_id).first()
    assert get_decide.status_code == 405
    assert row.status == "pending"
    print("  -> only a POST can decide\n")

    # ---------------------------------------------------------------- 3
    print("== 3. APPROVE via the JSON post (the script path) ==")
    approve = client.post(
        decide_path, json={"action": "approve", "token": token}
    )
    print("  approve           :", approve.status_code, approve.get_json()["data"]["status"])
    assert approve.status_code == 200
    assert approve.get_json()["data"]["status"] == "approved"
    assert console_session.is_unlocked() is False, "the decision alone must not open the console"
    # Only the requesting browser may spend it.
    stolen = client.post(
        f"/api/admin/session/approval/{request_id}/consume", json={"challenge": challenge()}
    )
    print("  other browser     :", stolen.status_code)
    assert stolen.status_code == 403 and console_session.is_unlocked() is False
    spent = client.post(
        f"/api/admin/session/approval/{request_id}/consume", json={"challenge": chal}
    )
    print("  sign-in browser   :", spent.status_code, "| open:", console_session.is_unlocked())
    assert spent.status_code == 200 and console_session.is_unlocked() is True
    print("  -> APPROVED on the original session only\n")

    # ---------------------------------------------------------------- 4
    print("== 4. replay is refused: single-use token ==")
    replay_post = client.post(decide_path, json={"action": "deny", "token": token})
    replay_spend = client.post(
        f"/api/admin/session/approval/{request_id}/consume", json={"challenge": chal}
    )
    print("  re-decide         :", replay_post.status_code)
    print("  re-spend          :", replay_spend.status_code)
    assert replay_post.status_code == 400, "a spent token must not decide again"
    assert replay_spend.status_code == 403
    print("  -> a used link stops working\n")

    # ---------------------------------------------------------------- 5
    print("== 5. DENY via a plain FORM post (the no-JavaScript path) ==")
    console_session.lock()
    chal2 = challenge()
    deny_id = sign_in(chal2).get_json()["data"]["request_id"]
    deny_token = TOKENS[deny_id]
    form_deny = client.post(
        f"/api/admin/session/approval/{deny_id}/decide",
        data={"action": "deny", "token": deny_token},  # form-encoded, not JSON
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    print("  form post         :", form_deny.status_code, form_deny.content_type)
    assert form_deny.status_code == 200
    assert "text/html" in form_deny.content_type, "a form post must get a page back"
    html = form_deny.get_data(as_text=True)
    assert "Denied" in html or "denied" in html, "the page must state the outcome"
    # NO EXTERNAL REDIRECT: the response is this app's own page, not a 3xx away.
    assert form_deny.status_code == 200, "must not redirect off-site"
    # The page must not send the browser anywhere else — no meta-refresh, no
    # off-host link the approver could be bounced to.
    lowered = html.lower()
    assert "http-equiv=\"refresh\"" not in lowered, "no auto-redirect may be present"
    assert "example.com" not in lowered and "bit.ly" not in lowered
    row = AdminLoginApproval.query.filter_by(request_id=deny_id).first()
    print("  row status        :", row.status)
    assert row.status == "denied"
    # A denied request can never be spent.
    consume = client.post(
        f"/api/admin/session/approval/{deny_id}/consume", json={"challenge": chal2}
    )
    print("  consume denied    :", consume.status_code, "| locked:", not console_session.is_unlocked())
    assert consume.status_code == 403 and console_session.is_unlocked() is False
    polled = client.post(
        "/api/admin/session/approval", json={"request_id": deny_id, "challenge": chal2}
    ).get_json()["data"]
    print("  login page sees   :", polled["status"])
    assert polled["status"] == "denied"
    print("  -> DENIED, console stays locked\n")

    # ---------------------------------------------------------------- 6
    print("== 6. a wrong token is refused and does not burn the request ==")
    chal3 = challenge()
    id3 = sign_in(chal3).get_json()["data"]["request_id"]
    bad = client.post(
        f"/api/admin/session/approval/{id3}/decide",
        json={"action": "approve", "token": "not-the-real-token"},
    )
    row3 = AdminLoginApproval.query.filter_by(request_id=id3).first()
    print("  wrong token       :", bad.status_code, "| row:", row3.status)
    assert bad.status_code == 400 and row3.status == "pending"
    print("  -> a guess cannot cancel a pending request\n")

    print("ALL MAIL-FLOW CHECKS PASSED")

with app.app_context():
    db.session.remove()


def test_admin_approval_mail_flow():
    """Pytest entry point for the checks above.

    This module IS a script: the checks run at import time inside a
    ``with app.app_context():`` block, which pytest does not collect — pytest
    reported the file as "collected 0 items" and exited 1, so the mail-link
    safety behaviour was silently NOT part of the automated suite.

    The body is left exactly as it was, so the file still works when run
    directly (``python tests/test_admin_approval_mail_flow.py``). This wrapper
    re-runs the script in a SUBPROCESS and asserts it exits 0, so the whole flow
    becomes a real node in ``pytest tests``: a failed assertion in the body
    surfaces here as a failing test rather than as an empty collection.

    A subprocess rather than an in-process call, because the module body has
    already executed once at import (binding its own SQLite database via
    ``DATABASE_URL`` before ``create_app``), and re-running it in-process would
    collide with that state.
    """
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).resolve()
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, (
        "admin approval mail-flow checks failed:\n"
        + (result.stdout or "")[-4000:]
        + "\n"
        + (result.stderr or "")[-2000:]
    )
    assert "ALL MAIL-FLOW CHECKS PASSED" in result.stdout
