"""Check automatic admin-approval status synchronization.

The property under test is the one the feature exists for: once the administrator
answers the mail, the REQUESTING session learns the outcome on its own — with no
manual refresh and no second access request — and an offline session retrieves
that outcome when it next connects.

Written as the situations that actually break a hand-rolled sync:

  1. ONLINE: while the requester's page polls, an approval in the mail becomes
     visible to it, and only then can it spend the approval to open the console.
  2. OFFLINE: the answer arrives while the requester is not talking to the server
     (no polls running). Nothing is lost — the status is durable in the database,
     and the NEXT poll after reconnect reports it. This is what "retrieve on next
     connect" means; the test proves the row is the source of truth, not any
     in-memory flag.
  3. DENIED: reported as denied, and the console stays locked.
  4. EXPIRED: reported as expired, and can never be spent.
  5. CONSUMED (revoked/used): a spent approval reports consumed and cannot open
     anything again.
  6. PENDING: reported as pending with a live countdown, and never as an outcome.
  7. NO SECRETS: the poll payload contains no token, no challenge and no hash.
  8. WRONG CHALLENGE: another browser is told `unknown`, never the real status.

**THE DATABASE IS REDIRECTED BEFORE `create_app()`**, exactly as the sibling
approval tests do, so this can never write to a real deployment's database.
"""

import os
import re
import tempfile

_TMPDIR = tempfile.mkdtemp(prefix="aquaguard-sync-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMPDIR, 'test.db')}"
os.environ["SECRET_KEY"] = "sync-check-only-key-not-a-real-secret-0123456789"
os.environ["MAIL_SUPPRESS_SEND"] = "1"
os.environ.setdefault("FLASK_ENV", "development")

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402

app = create_app()
app.config["MAIL_SUPPRESS_SEND"] = True
app.config["ADMIN_PASSWORD"] = "correct-horse-battery-staple"
# A short window so the expiry case is exercised without sleeping a minute.
app.config["ADMIN_APPROVAL_TTL_MINUTES"] = 15

with app.app_context():
    bound = str(db.engine.url)
    assert _TMPDIR in bound, f"refusing to run: engine bound to {bound}"
    print("engine bound to the temporary database:", bound, "\n")
    db.create_all()

    from datetime import datetime, timezone

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

    TOKENS: dict[str, str] = {}
    real_create = approvals.create_request

    def spy(*args, **kwargs):
        row, token = real_create(*args, **kwargs)
        TOKENS[row.request_id] = token
        return row, token

    approvals.create_request = spy

    def poll(request_id: str, chal: str) -> dict:
        return client.post(
            "/api/admin/session/approval",
            json={"request_id": request_id, "challenge": chal},
        ).get_json()["data"]

    # ---------------------------------------------------------------- 1
    print("== 1. ONLINE: an approval in the mail reaches the requesting session ==")
    chal = challenge()
    request_id = sign_in(chal).get_json()["data"]["request_id"]
    token = TOKENS[request_id]

    seen = poll(request_id, chal)
    print("  first poll        :", seen["status"], "| seconds_left:", seen["seconds_remaining"])
    assert seen["status"] == "pending" and seen["found"] is True
    assert seen["seconds_remaining"] > 0, "a pending request must report a live countdown"
    assert console_session.is_unlocked() is False

    # The admin presses Approve in the mail (the /decide endpoint the mail uses).
    decided = client.post(
        f"/api/admin/session/approval/{request_id}/decide",
        json={"action": "approve", "token": token},
    )
    assert decided.status_code == 200
    # The requester's NEXT poll — no manual refresh, no new request — sees it.
    after = poll(request_id, chal)
    print("  next poll         :", after["status"])
    assert after["status"] == "approved", "the same session must see the approval by polling"
    assert console_session.is_unlocked() is False, "seeing it is not yet access"

    # Spending it opens the console for THIS session.
    spent = client.post(
        f"/api/admin/session/approval/{request_id}/consume", json={"challenge": chal}
    )
    print("  consume           :", spent.status_code, "| open:", console_session.is_unlocked())
    assert spent.status_code == 200 and console_session.is_unlocked() is True
    print("  -> approval propagated to the requesting session\n")

    # ---------------------------------------------------------------- 2
    print("== 2. OFFLINE: the answer waits in the database until reconnect ==")
    console_session.lock()
    chal2 = challenge()
    id2 = sign_in(chal2).get_json()["data"]["request_id"]
    token2 = TOKENS[id2]

    # The requester goes offline: NO polls happen while the admin decides.
    client.post(
        f"/api/admin/session/approval/{id2}/decide",
        json={"action": "approve", "token": token2},
    )
    # Prove nothing about the decision was cached in a process-local flag: read
    # the row straight from the database, which is what a fresh poll trusts.
    row2 = db.session.query(AdminLoginApproval).filter_by(request_id=id2).first()
    db.session.expire(row2)
    refreshed = db.session.query(AdminLoginApproval).filter_by(request_id=id2).first()
    print("  decided while away:", refreshed.status)
    assert refreshed.status == "approved", "the approval must be durable, not in-memory"

    # Reconnect: the first poll after coming back reports the held outcome.
    back = poll(id2, chal2)
    print("  first poll after  :", back["status"])
    assert back["status"] == "approved", "reconnect must retrieve the stored outcome"
    opened = client.post(
        f"/api/admin/session/approval/{id2}/consume", json={"challenge": chal2}
    )
    print("  consume           :", opened.status_code, "| open:", console_session.is_unlocked())
    assert opened.status_code == 200 and console_session.is_unlocked() is True
    print("  -> offline approval retrieved on reconnect\n")

    # ---------------------------------------------------------------- 3
    print("== 3. DENIED is reported and never grants access ==")
    console_session.lock()
    chal3 = challenge()
    id3 = sign_in(chal3).get_json()["data"]["request_id"]
    token3 = TOKENS[id3]
    client.post(
        f"/api/admin/session/approval/{id3}/decide",
        json={"action": "deny", "token": token3},
    )
    denied = poll(id3, chal3)
    print("  poll              :", denied["status"])
    assert denied["status"] == "denied"
    consume = client.post(
        f"/api/admin/session/approval/{id3}/consume", json={"challenge": chal3}
    )
    print("  consume           :", consume.status_code, "| locked:", not console_session.is_unlocked())
    assert consume.status_code == 403 and console_session.is_unlocked() is False
    print("  -> denied stays denied\n")

    # ---------------------------------------------------------------- 4
    print("== 4. EXPIRED is reported and can never be spent ==")
    chal4 = challenge()
    id4 = sign_in(chal4).get_json()["data"]["request_id"]
    token4 = TOKENS[id4]
    row4 = db.session.query(AdminLoginApproval).filter_by(request_id=id4).first()
    # Force the window shut rather than sleeping.
    row4.expires_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.session.commit()

    expired = poll(id4, chal4)
    print("  poll              :", expired["status"], "| seconds_left:", expired["seconds_remaining"])
    assert expired["status"] == "expired" and expired["seconds_remaining"] == 0
    late = client.post(
        f"/api/admin/session/approval/{id4}/decide",
        json={"action": "approve", "token": token4},
    )
    print("  late approve      :", late.status_code)
    assert late.status_code == 400 and console_session.is_unlocked() is False
    print("  -> expired is refused\n")

    # ---------------------------------------------------------------- 5
    print("== 5. CONSUMED (already used / revoked) is reported and inert ==")
    console_session.lock()
    chal5 = challenge()
    id5 = sign_in(chal5).get_json()["data"]["request_id"]
    token5 = TOKENS[id5]
    client.post(
        f"/api/admin/session/approval/{id5}/decide",
        json={"action": "approve", "token": token5},
    )
    first = client.post(
        f"/api/admin/session/approval/{id5}/consume", json={"challenge": chal5}
    )
    assert first.status_code == 200
    console_session.lock()
    used = poll(id5, chal5)
    print("  poll              :", used["status"])
    assert used["status"] == "consumed", "a spent approval must report consumed"
    # ...and it can never open anything again.
    again = client.post(
        f"/api/admin/session/approval/{id5}/consume", json={"challenge": chal5}
    )
    print("  re-consume        :", again.status_code)
    assert again.status_code == 403 and console_session.is_unlocked() is False
    print("  -> consumed is terminal\n")

    # ---------------------------------------------------------------- 6
    print("== 6. the poll payload carries NO secret ==")
    chal6 = challenge()
    id6 = sign_in(chal6).get_json()["data"]["request_id"]
    token6 = TOKENS[id6]
    raw = client.post(
        "/api/admin/session/approval", json={"request_id": id6, "challenge": chal6}
    ).get_data(as_text=True)
    print("  payload keys      :", sorted(poll(id6, chal6).keys()))
    for forbidden in (token6, "action_token", "token_hash", "challenge_hash"):
        assert forbidden not in raw, f"the poll must not expose {forbidden!r}"
    assert "password" not in raw.lower()
    # The CHALLENGE the browser holds is never echoed back (only its hash is kept).
    assert chal6 not in raw, "the challenge must not be reflected in the response"
    print("  -> no token, no challenge, no hash, no credential\n")

    # ---------------------------------------------------------------- 7
    print("== 7. another browser learns nothing about this request ==")
    other = poll(id6, challenge())
    print("  other browser     :", other["status"], "| found =", other["found"])
    assert other["status"] == "unknown" and other["found"] is False
    print("  -> the poll is scoped to the requesting browser\n")

    print("ALL SYNC CHECKS PASSED")

with app.app_context():
    db.session.remove()


def test_admin_approval_sync():
    """Pytest entry point for the checks above.

    This module IS a script: the checks run at import time inside a
    ``with app.app_context():`` block, which pytest does not collect — pytest
    reported the file as "collected 0 items" and exited 1, so the approval-sync
    behaviour was silently NOT part of the automated suite. It only ever ran
    when someone remembered to execute the file by hand.

    The body is left exactly as it was, so the file still works when run
    directly (``python tests/test_admin_approval_sync.py``). This wrapper
    re-runs the script in a SUBPROCESS and asserts it exits 0, which makes the
    whole flow a real node in ``pytest tests`` again: any failed assertion in
    the body surfaces here as a failing test rather than as an empty
    collection.

    A subprocess rather than an in-process call, because the module body has
    already executed once at import (it binds its own SQLite database via
    ``DATABASE_URL`` before ``create_app``), and re-running it in-process would
    re-bind a database and collide with that state.
    """
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).resolve()
    # A generous timeout: the script seeds a credential, hashes with bcrypt and
    # drives several full sign-in/approve/consume round trips.
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, (
        "admin approval sync checks failed:\n"
        + (result.stdout or "")[-4000:]
        + "\n"
        + (result.stderr or "")[-2000:]
    )
    assert "ALL SYNC CHECKS PASSED" in result.stdout
