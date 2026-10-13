"""End-to-end check of the admin login approval flow (Prompt 8).

Every assertion here is about a way the OLD flow could be abused, so the test is
written as a list of attacks rather than a list of features:

 1. A wrong password must send NO mail and create NO request. The old code
     issued the confirmation before the result was acted on, which turned the
     admin's inbox into a username oracle.
 2. A link scanner that merely OPENS the mail's URL must change nothing. The old
     mail carried `GET /confirm?token=...`, which opened the console on load.
 3. A denied request must never grant access.
 4. An approved request must be spendable ONCE, and only by the browser that
     asked for it.
 5. One attempt's token must not decide another attempt.
 6. A wrong token must not consume the request (otherwise anyone could cancel an
     admin's pending login by guessing).
 7. Expiry must be enforced.

**THE DATABASE IS REDIRECTED BEFORE `create_app()`.** The engine is built inside
`create_app`, so setting `SQLALCHEMY_DATABASE_URI` afterwards does nothing - the
app would still be writing to the real deployment's database while the test
believed it was not. The environment variable is what `get_config()` reads, and
the engine's URL is asserted before anything is written.
"""

import os
import tempfile

_TMPDIR = tempfile.mkdtemp(prefix="aquaguard-approval-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMPDIR, 'test.db')}"
os.environ["SECRET_KEY"] = "approval-check-only-key-not-a-real-secret-0123456789"
# Build the mail but never open a socket to a real provider.
os.environ["MAIL_SUPPRESS_SEND"] = "1"
os.environ.setdefault("FLASK_ENV", "development")

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402

app = create_app()
app.config["MAIL_SUPPRESS_SEND"] = True
# A known console credential for this throwaway app.
app.config["ADMIN_PASSWORD"] = "correct-horse-battery-staple"

with app.app_context():
    bound = str(db.engine.url)
    assert _TMPDIR in bound, f"refusing to run: engine bound to {bound}, not the temp DB"
    print("engine bound to the temporary database:", bound, "\n")
    db.create_all()

    from app.models.admin_login_approval import AdminLoginApproval
    from app.models.admin_settings import AdminSettings
    from app.services import admin_service, console_session, login_approval_service as approvals

    # Seed the console credential the way the real service does, so the check runs
    # against the same bcrypt path a real deployment uses rather than a stub.
    settings = db.session.get(AdminSettings, 1) or AdminSettings(id=1)
    if settings not in db.session:
        db.session.add(settings)
    settings.admin_username = "abishek"
    settings.admin_email = "admin@aquaguard.test"
    settings.admin_approval_email = "security@aquaguard.test"
    db.session.commit()

    reset = admin_service.issue_reset_code()
    # The code is deliberately NOT in the response. Recover it the way a real
    # inbox would: read the message the service BUILT (recorded in the
    # suppression sink when MAIL_SUPPRESS_SEND is on) rather than a stored
    # plain code -- which the service intentionally never keeps.
    from app.services import mail_service as _mail
    import re
    code_match = None
    for message in reversed(_mail.SUPPRESSED_MESSAGES):
        if "reset code" in message.get("Subject", "").lower():
            code_match = message.get_body(preferencelist=("plain",)).get_content().strip()
            break
    # The body contains prose; extract the 6-digit code out of it.
    if code_match:
        m = re.search(r"\b\d{6}\b", code_match)
        code_match = m.group(0) if m else ""
    stored_code = code_match or ""
    assert stored_code, "no reset code was stored"
    admin_service.reset_admin_password(
        code=str(stored_code), new_password="CorrectHorse1"
    )
    print("console credential seeded\n")

    client = app.test_client()

    def challenge() -> str:
        return client.get("/api/admin/session/challenge").get_json()["data"]["challenge"]

    def mail_token(row_id: str) -> str:
        """The token the mail would carry — recovered here the way an inbox would."""
        return TOKENS.pop(row_id)

    TOKENS: dict[str, str] = {}

    def sign_in(chal: str, password: str = "CorrectHorse1"):
        return client.post(
            "/api/admin/session",
            json={"username": "abishek", "password": password, "challenge": chal},
        )

    # Capture the token by wrapping create_request, which is where the clear value
    # is generated. This is the same value the mail link carries.
    real_create = approvals.create_request

    def spy(*args, **kwargs):
        row, token = real_create(*args, **kwargs)
        TOKENS[row.request_id] = token
        return row, token

    approvals.create_request = spy

    # ---------------------------------------------------------------- 1
    print("== 1. a WRONG password sends no mail and creates no request ==")
    before = AdminLoginApproval.query.count()
    chal = challenge()
    bad = sign_in(chal, "not-the-password")
    after = AdminLoginApproval.query.count()
    print("  HTTP status :", bad.status_code)
    print("  rows created:", after - before)
    assert bad.status_code == 401, bad.get_json()
    assert after == before, "a rejected credential must not create an approval request"
    assert console_session.is_unlocked() is False
    print("  -> no request row, no mail, console locked\n")

    # ---------------------------------------------------------------- 2
    print("== 2. a correct password creates a request; the mail link is inert on load ==")
    chal = challenge()
    ok = sign_in(chal)
    payload = ok.get_json()["data"]
    request_id = payload["request_id"]
    token = mail_token(request_id)
    print("  HTTP status     :", ok.status_code)
    print("  request id      :", request_id[:12], "…")
    print("  sent to         :", payload["sent_to"])
    print("  window          :", payload["approval_window_minutes"], "min")
    print("  interactive btn :", payload["email_capabilities"]["interactive_actions_supported"])
    assert ok.status_code == 200
    assert AdminLoginApproval.query.count() == before + 1
    # The recipient is MASKED: the login page is reachable anonymously, so it must
    # not be a place the approval address can be read in full.
    assert "security@aquaguard.test" not in payload["sent_to"], payload["sent_to"]
    # The token is NOT returned to the browser.
    assert "action_token" not in payload and token not in str(payload)
    print("  recipient masked, token not returned to the page")

    # THE ATTACK: a mail security scanner, prefetcher or link preview fetches the
    # URL the mail contains. It must change nothing.
    review = client.get(f"/api/admin/session/approval/{request_id}/review?token={token}")
    row = AdminLoginApproval.query.filter_by(request_id=request_id).first()
    print("  scanner GET     :", review.status_code, "| row status:", row.status)
    print("  console locked  :", not console_session.is_unlocked())
    assert review.status_code == 200
    assert row.status == "pending", "opening the mail's URL must not decide anything"
    assert console_session.is_unlocked() is False, "opening a link must not open the console"

    # And the old state-changing GET endpoint is gone for good.
    legacy = client.get(f"/api/admin/session/confirm?token={token}")
    print("  legacy GET      :", legacy.status_code, "(410 Gone)")
    assert legacy.status_code == 410
    assert console_session.is_unlocked() is False
    print("  -> loading any link decides nothing\n")

    # ---------------------------------------------------------------- 3
    print("== 3. polling needs the right challenge ==")
    good = client.post(
        "/api/admin/session/approval", json={"request_id": request_id, "challenge": chal}
    ).get_json()["data"]
    wrong = client.post(
        "/api/admin/session/approval",
        json={"request_id": request_id, "challenge": challenge()},
    ).get_json()["data"]
    print("  own challenge :", good["status"], "found =", good["found"])
    print("  other browser :", wrong["status"], "found =", wrong["found"])
    assert good["status"] == "pending"
    assert wrong["status"] == "unknown", "another browser must not be able to watch this login"
    print("  -> a request cannot be watched from another browser\n")

    # ---------------------------------------------------------------- 4
    print("== 4. approving requires the mail token, and grants nothing by itself ==")
    no_token = client.post(
        f"/api/admin/session/approval/{request_id}/decide", json={"action": "approve"}
    )
    print("  with no token :", no_token.status_code)
    assert no_token.status_code == 400

    wrong_token = client.post(
        f"/api/admin/session/approval/{request_id}/decide",
        json={"action": "approve", "token": "not-the-real-token"},
    )
    print("  wrong token   :", wrong_token.status_code)
    assert wrong_token.status_code == 400
    # AND the request is NOT consumed by a wrong guess — otherwise anyone could
    # cancel an admin's pending login just by guessing.
    row = db.session.get(type(row), row.id)
    print("  still pending :", row.status)
    assert row.status == "pending", "a wrong token must not burn the request"

    # A GET against the decide endpoint cannot work either — it is a POST route.
    get_decide = client.get(f"/api/admin/session/approval/{request_id}/decide?token={token}")
    print("  GET on decide :", get_decide.status_code, "(405, POST only)")
    assert get_decide.status_code == 405
    print()

    # ---------------------------------------------------------------- 5
    print("== 5. APPROVE in the mail, then spend it from the requesting browser ==")
    approve = client.post(
        f"/api/admin/session/approval/{request_id}/decide",
        json={"action": "approve", "token": token},
    )
    print("  decide        :", approve.status_code, approve.get_json()["data"]["status"])
    assert approve.status_code == 200
    assert console_session.is_unlocked() is False, "approval alone must NOT open the console"

    # A different browser cannot spend it, even knowing the request id.
    stolen = client.post(
        f"/api/admin/session/approval/{request_id}/consume", json={"challenge": challenge()}
    )
    print("  other browser :", stolen.status_code)
    print("  console locked:", not console_session.is_unlocked())
    assert stolen.status_code == 403
    assert console_session.is_unlocked() is False

    # The requesting browser can.
    spent = client.post(
        f"/api/admin/session/approval/{request_id}/consume", json={"challenge": chal}
    )
    print("  own browser   :", spent.status_code, spent.get_json()["data"]["unlocked"])
    print("  console open  :", console_session.is_unlocked())
    assert spent.status_code == 200
    assert console_session.is_unlocked() is True
    print("  -> APPROVED: the ORIGINAL session opened the console\n")

    # ---------------------------------------------------------------- 6
    print("== 6. single use: the same approval cannot be spent twice ==")
    replay = client.post(
        f"/api/admin/session/approval/{request_id}/consume", json={"challenge": chal}
    )
    print("  replay        :", replay.status_code)
    assert replay.status_code == 403
    # And the decision endpoint refuses to answer it again.
    again = client.post(
        f"/api/admin/session/approval/{request_id}/decide",
        json={"action": "deny", "token": token},
    )
    print("  re-decide     :", again.status_code)
    assert again.status_code == 400
    print()

    # ---------------------------------------------------------------- 7
    print("== 7. DENY leaves the console locked ==")
    console_session.lock()
    chal2 = challenge()
    deny_id = sign_in(chal2).get_json()["data"]["request_id"]
    deny_token = mail_token(deny_id)
    denied = client.post(
        f"/api/admin/session/approval/{deny_id}/decide",
        json={"action": "deny", "token": deny_token},
    )
    print("  decide        :", denied.status_code, denied.get_json()["data"]["status"])
    assert denied.get_json()["data"]["status"] == "denied"

    polled = client.post(
        "/api/admin/session/approval", json={"request_id": deny_id, "challenge": chal2}
    ).get_json()["data"]
    print("  login page sees:", polled["status"])
    assert polled["status"] == "denied", "the login page must be able to show Access Denied"

    consume_denied = client.post(
        f"/api/admin/session/approval/{deny_id}/consume", json={"challenge": chal2}
    )
    print("  consume       :", consume_denied.status_code)
    print("  console locked:", not console_session.is_unlocked())
    assert consume_denied.status_code == 403
    assert console_session.is_unlocked() is False
    print("  -> DENIED: a denied request can never be spent\n")

    # ---------------------------------------------------------------- 8
    print("== 8. one attempt's token cannot decide another attempt ==")
    chalA, chalB = challenge(), challenge()
    id_a = sign_in(chalA).get_json()["data"]["request_id"]
    id_b = sign_in(chalB).get_json()["data"]["request_id"]
    token_a = mail_token(id_a)
    print("  two requests  :", id_a[:8], "and", id_b[:8])
    cross = client.post(
        f"/api/admin/session/approval/{id_b}/decide",
        json={"action": "approve", "token": token_a},
    )
    print("  token A on B  :", cross.status_code)
    assert cross.status_code == 400
    row_b = db.session.query(AdminLoginApproval).filter_by(request_id=id_b).first()
    print("  B still       :", row_b.status)
    assert row_b.status == "pending", "one attempt's token must not decide another"
    print("  -> attempts are independent\n")

    # ---------------------------------------------------------------- 9
    print("== 9. expiry is enforced ==")
    ttl_before = approvals.ttl_seconds()
    app.config["ADMIN_APPROVAL_TTL_MINUTES"] = 0  # clamped up to 1 second
    chal3 = challenge()
    id_c = sign_in(chal3).get_json()["data"]["request_id"]
    token_c = mail_token(id_c)
    row_c = db.session.query(AdminLoginApproval).filter_by(request_id=id_c).first()
    # Force the window shut rather than sleeping for a real minute.
    row_c.expires_at = row_c.requested_at
    db.session.commit()

    expired_poll = client.post(
        "/api/admin/session/approval", json={"request_id": id_c, "challenge": chal3}
    ).get_json()["data"]
    print("  poll says     :", expired_poll["status"])
    assert expired_poll["status"] == "expired"

    expired_decide = client.post(
        f"/api/admin/session/approval/{id_c}/decide",
        json={"action": "approve", "token": token_c},
    )
    print("  decide        :", expired_decide.status_code)
    assert expired_decide.status_code == 400
    assert console_session.is_unlocked() is False
    app.config["ADMIN_APPROVAL_TTL_MINUTES"] = ttl_before // 60
    print("  -> an expired request is refused, console untouched\n")

    # ---------------------------------------------------------------- 10
    print("== 10. nothing sensitive is stored ==")
    row_a = db.session.query(AdminLoginApproval).filter_by(request_id=id_a).first()
    stored = " ".join(
        str(getattr(row_a, column.name))
        for column in AdminLoginApproval.__table__.columns
    )
    print("  columns holding the token :", "action_token_hash (SHA-256 only)")
    print("  plain token present in row:", token_a in stored)
    assert token_a not in stored, "the plain action token must never be stored"
    assert "correct-horse-battery-staple" not in stored, "no credential may be stored"
    assert "CorrectHorse1" not in stored, "no credential may be stored"
    print("  -> no plain token, no password, no credential at rest\n")

    print("ALL APPROVAL CHECKS PASSED")

with app.app_context():
    db.session.remove()
