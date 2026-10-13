"""The admin login approval workflow: request, decide, and learn the outcome.

THE FLOW, AND WHY IT IS SHAPED THIS WAY.

    login page                backend                     mailbox
    ----------                -------                     --------
    password sent   ──POST──▶ verify credential FIRST
                              ✗ no mail is ever sent
                              ✓ create a request row
                                send the approval mail ───▶ "Login request"
                                                                  two actions
                              ◀─── decision ──────────────
    poll (2s)      ──GET───▶ row's status
      approved  → console opens HERE
      denied    → "Access Denied" HERE

FIVE THINGS THIS EXISTS TO FIX, each of which was a real defect.

1. AN INVALID CREDENTIAL MUST NOT PRODUCE AN EMAIL. The mail is only sent after
   `verify_admin_credentials` has passed. A wrong password used to reach the
   sending code, which turned the admin's inbox into an unauthenticated oracle:
   an attacker could confirm a correct username by watching for a mail.

2. NO PLAIN GET LINK MAY CHANGE ACCESS STATE. Email security scanners, link
   prefetchers and chat clients open URLs automatically. The previous mail carried
   `GET /session/confirm?token=…`, so any of those that touched it spent the
   token and made the decision.

   So the mail's links point at an INTERSTITIAL: a page that explains what is
   being approved and requires a real, deliberate POST. A scanner that opens the
   link sees a confirmation screen and changes nothing. That is also why the
   requirement that clicking must not open an external page is satisfied without
   a promise the platform cannot keep - see `email_action_capabilities`.

3. THE INTERSTITIAL IS A REAL PAGE, NOT A ROUTE THAT UNLOCKS. It renders the
   request's own details and the two actions, and its buttons POST. It never
   navigates the approver into the console, and the console is never unlocked by
   loading anything.

4. ONE ATTEMPT PER ROW, EACH ANSWERED ON ITS OWN TERMS. The previous design held
   a single pending confirmation, so a second sign-in attempt destroyed the first
   and answering one mail decided the other.

5. THE DECISION IS BOUND TO THE ATTEMPT AND THE BROWSER. The action token is
   stored hashed and compared in constant time; the challenge is minted by the
   backend, held in `sessionStorage` and never travels in a URL; and a spent
   token cannot be replayed.

WHAT IS NOT HERE, DELIBERATELY. No password, no hash of the password, no console
credential, and no token in any URL that a page load alone would act on. The
audit trail records decisions and refusals, never a secret.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from flask import current_app, has_app_context, request

from app.extensions import db
from app.models.admin_login_approval import (
    ACTION_APPROVE,
    ACTION_DENY,
    STATUS_APPROVED,
    STATUS_CONSUMED,
    STATUS_DENIED,
    STATUS_EXPIRED,
    STATUS_PENDING,
    AdminLoginApproval,
    new_token,
)
from app.utils.errors import BadRequestError, NotFoundError

logger = logging.getLogger(__name__)

#: How long a request may be answered for. Deliberately short: the value is that
#: an unread approval mail stops being a credential after a few minutes, so a
#: mail left in an inbox, or a link captured in a proxy log, goes stale.
DEFAULT_TTL_MINUTES = 15

#: Ceiling on the configured TTL. An approval window measured in hours is a
#: standing credential, which is the thing this mechanism exists to avoid, so a
#: misconfiguration cannot silently produce one.
MAX_TTL_MINUTES = 60


def ttl_seconds() -> int:
    """The approval window, from configuration, clamped to a sane maximum."""
    if not has_app_context():
        return DEFAULT_TTL_MINUTES * 60
    configured = current_app.config.get("ADMIN_APPROVAL_TTL_MINUTES", DEFAULT_TTL_MINUTES)
    try:
        minutes = int(configured)
    except (TypeError, ValueError):
        minutes = DEFAULT_TTL_MINUTES
    return max(1, min(minutes, MAX_TTL_MINUTES)) * 60


# ---------------------------------------------------------------------------
# Hashing. These values are stored, not kept.
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    """Timezone-NAIVE UTC now.

    Every timestamp in `admin_login_approvals` is stored in a naive `DateTime`
    column, and both MySQL and SQLite hand such values back WITHOUT a `tzinfo`.
    Comparing those against an aware `datetime.now(timezone.utc)` raises
    `TypeError: can't compare offset-naive and offset-aware datetimes`, so every
    read and write in this module goes through here: the stored value is UTC by
    construction, so dropping the tzinfo is a correction, not a guess.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hash(value: str) -> str:
    """SHA-256 of a token, hex.

    A token is 256 bits of entropy, so there is nothing to brute-force and no
    password-stretching to do. What the hash buys is that a database dump, a log
    line or a support screenshot does not contain a usable approval credential -
    which is the same reason a password is hashed.
    """
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _matches(expected_hash: str, candidate: str) -> bool:
    """Constant-time comparison of a candidate token against a stored hash."""
    if not expected_hash or not candidate:
        return False
    return hmac.compare_digest(expected_hash, _hash(candidate))


def _device_label() -> str | None:
    """A short, recognisable label for the requesting browser.

    Derived from the user agent, never from anything that identifies a person: the
    point is that the admin can tell "that is my laptop" from "that is not", and
    nothing more. A missing or unparseable agent yields None rather than a guess.
    """
    agent = (request.user_agent.string or "") if request else ""
    if not agent:
        return None
    browser = "Browser"
    for token, label in (
        ("Edg/", "Edge"),
        ("OPR/", "Opera"),
        ("Chrome/", "Chrome"),
        ("Firefox/", "Firefox"),
        ("Safari/", "Safari"),
    ):
        if token in agent:
            browser = label
            break
    system = "Unknown OS"
    for token, label in (
        ("Windows", "Windows"),
        ("Android", "Android"),
        ("iPhone", "iPhone"),
        ("iPad", "iPad"),
        ("Mac OS X", "macOS"),
        ("Linux", "Linux"),
    ):
        if token in agent:
            system = label
            break
    return f"{browser} on {system}"


def _client_ip() -> str | None:
    """The requesting address, recorded for the audit trail.

    `remote_addr` only. `X-Forwarded-For` is client-controlled, and trusting it
    would let an attacker write whatever address they liked into the audit trail
    - which is the one place this value is stored.
    """
    return request.remote_addr if request else None


# ---------------------------------------------------------------------------
# Step 1: the request. Credentials are verified BEFORE this is ever called.
# ---------------------------------------------------------------------------


def create_request(
    admin_username: str,
    *,
    challenge: str,
    credential_shape: str | None = None,
    requester_ip: str | None = None,
    requester_agent: str | None = None,
) -> tuple[AdminLoginApproval, str]:
    """Create a pending approval request and return it with its mail token.

    `challenge` is the browser's nonce, minted by the backend and handed to the
    login page once. It is stored HASHED and is checked again when the login page
    polls, so a decision can only be delivered to the browser that asked.

    The returned token is the ONLY copy of the mail authority. It is written into
    the mail and never stored in the clear, never logged, and never returned by
    any endpoint.
    """
    token = new_token()
    row = AdminLoginApproval(
        request_id=new_token(),
        admin_username=str(admin_username or "console"),
        action_token_hash=_hash(token),
        challenge_hash=_hash(challenge or ""),
        attempt_nonce=new_token(),
        requested_at=_utcnow(),
        expires_at=_utcnow() + timedelta(seconds=ttl_seconds()),
        status=STATUS_PENDING,
        ip_address=(requester_ip or _client_ip()),
        user_agent=(requester_agent or (request.user_agent.string[:255] if request else None)),
        device_label=_device_label(),
        credential_shape=credential_shape,
    )
    db.session.add(row)
    db.session.commit()
    logger.info("Admin login approval requested by %r (id=%s)", row.admin_username, row.request_id[:8])
    return row, token


def new_challenge() -> str:
    """A fresh challenge nonce for a login page load."""
    return new_token()


# ---------------------------------------------------------------------------
# Step 2: the decision, taken from the mail
# ---------------------------------------------------------------------------


def decide(
    request_id: str,
    action: str,
    token: str,
    *,
    challenge: str | None = None,
    client_ip: str | None = None,
) -> dict[str, Any]:
    """Apply Yes or No. Returns a result describing what happened and why.

    EVERY REFUSAL IS AUDITED, because the refusals are the interesting half: "a
    request was approved and then someone tried to replay it" is a real finding,
    and a log that only records the clean path cannot surface it.

    The rules, in the order they are applied:

      * the row must exist;
      * the action must be one of the two;
      * the token must match, in constant time;
      * the request must still be `pending`;
      * it must not have expired;
      * it must not already have been consumed.

    The token is NOT invalidated by a failed attempt. That is deliberate: if a
    wrong token burned the request, anyone could cancel an admin's pending login
    just by guessing, which would turn the approval flow into a denial-of-service
    against the administrator.
    """
    row = db.session.query(AdminLoginApproval).filter_by(request_id=str(request_id or "")).first()

    if row is None:
        _audit(
            request_id,
            action,
            False,
            "No such login approval request.",
            client_ip,
        )
        raise NotFoundError("That login approval request was not found")

    if action not in (ACTION_APPROVE, ACTION_DENY):
        _audit(request_id, action, False, "Unrecognised action.", client_ip)
        raise BadRequestError("That action is not recognised")

    if not _matches(row.action_token_hash, token):
        # Deliberately NOT expiring the request: see the docstring.
        _audit(
            request_id,
            action,
            False,
            "The action token did not match.",
            client_ip,
        )
        logger.warning("Rejected admin approval action with a non-matching token")
        raise BadRequestError("That approval link is not valid or has expired")

    now = _utcnow()

    if row.status == STATUS_CONSUMED or row.consumed_at is not None:
        _audit(request_id, action, False, "The request had already been used.", client_ip)
        raise BadRequestError("This login request has already been answered")

    if row.status != STATUS_PENDING:
        _audit(
            request_id,
            action,
            False,
            f"The request was already {row.status}.",
            client_ip,
        )
        raise BadRequestError(f"This login request was already {row.status}")

    if row.expires_at <= now:
        row.status = STATUS_EXPIRED
        row.decided_at = now
        row.decision_detail = "The approval window closed before a decision arrived."
        db.session.commit()
        _audit(request_id, action, False, "The request had expired.", client_ip)
        raise BadRequestError("This login request has expired. Start again from the login page.")

    # --- The decision -------------------------------------------------------
    if action == ACTION_DENY:
        row.status = STATUS_DENIED
        row.decision_detail = "Denied from the approval mail."
    else:
        row.status = STATUS_APPROVED
        row.decision_detail = "Approved from the approval mail."

    row.decided_at = now
    row.decided_by = "admin-approval-mail"
    # A denial is finished with at once: nothing may ever be spent on it. An
    # approval is NOT — it still has to be spent by the browser that asked, which
    # is what sets `consumed_at` and makes it single-use.
    if action == ACTION_DENY:
        row.consumed_at = now
    db.session.commit()

    _audit(
        request_id,
        action,
        True,
        row.decision_detail,
        client_ip,
        resulting=row.status,
    )
    logger.warning(
        "Admin login approval %s for request %s", row.status.upper(), row.request_id[:8]
    )
    return {
        "status": row.status,
        "admin_username": row.admin_username,
        "decided_at": row.decided_at.isoformat(),
    }


def spend_on_unlock(request_id: str, challenge: str) -> bool:
    """Consume an APPROVED request and open the console. The final gate.

    RE-CHECKED HERE, at the moment the console is actually opened, rather than
    trusted from the earlier approve call:

      * the row is `approved` - a denial or an expiry can never be spent;
      * it has not already been consumed - single use, enforced on the row.

    The binding is the CHALLENGE, not the mail token, and the distinction
    matters. The token's job was to prove the MAIL authorised the decision, which
    it did at `decide` time — the durable result of that is the row's status. This
    gate answers a different question: is THIS browser the one that asked? The
    challenge answers that, and it never leaves that browser, so it cannot be
    replayed from a mail, a URL or a log.

    Together the two steps mean neither half is sufficient alone: the mail cannot
    log in on its own, and this browser cannot log in without the mail.

    Returns False on any mismatch, and the caller opens nothing.
    """
    row = db.session.query(AdminLoginApproval).filter_by(request_id=str(request_id or "")).first()
    if row is None:
        return False

    if row.status != STATUS_APPROVED or row.consumed_at is not None:
        return False

    # The challenge binding. Without this, an approved request could be spent by a
    # different browser that somehow learned the request id.
    if not _matches(row.challenge_hash, challenge or ""):
        logger.warning("Rejected unlock: browser challenge did not match")
        _audit(
            row.request_id,
            "unlock",
            False,
            "The browser challenge did not match the request.",
            _client_ip(),
        )
        return False

    row.status = STATUS_CONSUMED
    row.consumed_at = _utcnow()
    db.session.commit()
    return True


# ---------------------------------------------------------------------------
# Step 3: how the login page learns the outcome
# ---------------------------------------------------------------------------


def poll(request_id: str, challenge: str) -> dict[str, Any]:
    """The outcome for ONE request, for the browser that asked for it.

    The challenge is required, so this cannot be used to watch somebody else's
    login attempt, and it returns a status rather than a token.

    The `expired` flag is computed here rather than by mutating the row, so a
    polling page never writes to the database - a read must not be able to change
    the state it is reading.
    """
    row = db.session.query(AdminLoginApproval).filter_by(request_id=str(request_id or "")).first()
    if row is None:
        return {"status": "unknown", "found": False}

    if not _matches(row.challenge_hash, challenge or ""):
        # Not an error and not a leak: the caller learns only that this request
        # is not one it may watch, which it already knows.
        return {"status": "unknown", "found": False}

    expired = row.status == STATUS_PENDING and row.expires_at <= _utcnow()
    payload = row.to_dict()
    payload["found"] = True
    if expired:
        payload["status"] = STATUS_EXPIRED
        payload["seconds_remaining"] = 0
    return payload


def expires_in(request_id: str, challenge: str) -> int:
    """Seconds left on the window, for the countdown the login page shows."""
    row = db.session.query(AdminLoginApproval).filter_by(request_id=str(request_id or "")).first()
    if row is None or not _matches(row.challenge_hash, challenge or ""):
        return 0
    return max(0, int((row.expires_at - _utcnow()).total_seconds()))


# ---------------------------------------------------------------------------
# Housekeeping
# ---------------------------------------------------------------------------


def expire_now(request_id: str, detail: str) -> None:
    """Refuse a request immediately, e.g. because its mail could not be sent.

    An approval nobody can receive is a login that silently times out, so when the
    mail fails the request is closed rather than left pending. The login page then
    reports the mail failure instead of waiting out the window on a request that
    can never be answered.
    """
    row = db.session.query(AdminLoginApproval).filter_by(request_id=str(request_id or "")).first()
    if row is None or row.status != STATUS_PENDING:
        return
    row.status = STATUS_DENIED
    row.decided_at = _utcnow()
    row.decision_detail = str(detail)[:500]
    row.consumed_at = row.decided_at
    db.session.commit()
    _audit(request_id, "mail_failed", False, row.decision_detail, None)


def sweep() -> int:
    """Mark timed-out requests expired. Returns how many were swept.

    Expiry is ALSO evaluated on every read, so this is housekeeping rather than
    the mechanism - a request is refused the moment it is presented, whether or
    not this has run. It exists so the table does not accumulate rows nobody will
    ever answer, and so `expired` appears as a real status for an old row.
    """
    now = _utcnow()
    stale = (
        db.session.query(AdminLoginApproval)
        .filter(AdminLoginApproval.status == STATUS_PENDING)
        .filter(AdminLoginApproval.expires_at <= now)
        .all()
    )
    for row in stale:
        row.status = STATUS_EXPIRED
        row.decided_at = now
        row.decision_detail = "The approval window closed."
    if stale:
        db.session.commit()
    return len(stale)


def _audit(
    request_id: str | None,
    action: str,
    success: bool,
    detail: str | None,
    client_ip: str | None,
    resulting: str | None = None,
) -> None:
    """Record one approval event.

    Written to the application log rather than to a new table: the requirement is
    that approval status and audit events are stored on the BACKEND, and
    `admin_login_approvals.status` plus the structured log line together satisfy
    that without adding a third table whose only job is to duplicate a status
    column. The status itself - which is what a decision is trusted from - lives in
    the database, never in the frontend.

    NEVER LOGS A TOKEN. Only the request id, which is not a secret: it is the
    handle the login page polls with and carries no authority by itself.
    """
    logger.warning(
        "ADMIN_APPROVAL request=%s action=%s result=%s%s ip=%s detail=%s",
        str(request_id)[:8],
        action,
        "success" if success else "refused",
        f" status={resulting}" if resulting else "",
        client_ip or "-",
        detail or "",
    )


def request_summary(row: AdminLoginApproval) -> dict[str, Any]:
    """What the approval page and the mail need to describe a request."""
    return {
        "request_id": row.request_id,
        "admin_username": row.admin_username,
        "status": row.status,
        "requested_at": row.requested_at.isoformat() if row.requested_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "device_label": row.device_label,
        "ip_address": row.ip_address,
        "seconds_remaining": max(0, int((row.expires_at - _utcnow()).total_seconds())),
    }
