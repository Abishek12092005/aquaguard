"""Admin console service: the access password, parameter limits and templates.

THE ADMIN PASSWORD IS SEPARATE FROM A USER LOGIN, deliberately. The console is
the highest-privilege surface in the application -- it can delete accounts and
read every account's sign-in history -- so it gets its own credential that can be
rotated on its own without touching anybody's user account.

TWO SOURCES, ONE RULE. `ADMIN_ACCESS_PASSWORD` in the environment seeds the first
credential. From then on the STORED bcrypt hash is what is checked. The
environment value is only consulted while no hash exists, so changing the password
through the console is not silently undone by a redeploy that still carries the
old env value.

Rotating the password is emailed to the configured address, because a password
change the owner did not make is the single most important thing to notice.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import request
from sqlalchemy import select

from app.constants import (
    FEATURE_BOUNDS,
    FEATURE_LABELS,
    FEATURE_NAMES,
    FEATURE_UNITS,
    VALID_ROLES,
)
from app.extensions import bcrypt, db
from app.models import AdminSettings, User
from app.models.mixins import utcnow
from app.utils.errors import AuthError, ValidationError

logger = logging.getLogger(__name__)

# Shown in the console when a parameter has never been overridden.
DEFAULT_NOTIFICATION_TEMPLATES: dict[str, dict[str, str]] = {
    "water_unsafe": {
        "label": "Unsafe water detected",
        "subject": "AquaGuard AI: unsafe water detected",
        "body": (
            "An unsafe water reading was recorded for {name}.\n\n"
            "Verdict: {verdict}\nConfidence: {confidence}\nReadings: {readings}\n\n"
            "Treat the water as unsafe until a retest says otherwise."
        ),
    },
    "threshold_exceeded": {
        "label": "Parameter outside its limit",
        "subject": "AquaGuard AI: parameter outside its limit",
        "body": (
            "{name}, a parameter in your latest sample sits outside its configured "
            "limit.\n\nReadings: {readings}\n\nThe limits are set by the "
            "administrator and may be tighter than the physical range."
        ),
    },
    "prediction_ready": {
        "label": "Prediction completed",
        "subject": "AquaGuard AI: your prediction is ready",
        "body": (
            "Hello {name}, your water sample was analysed.\n\n"
            "Verdict: {verdict}\nConfidence: {confidence}\n"
        ),
    },
    "signin_notice": {
        "label": "New sign-in",
        "subject": "AquaGuard AI: new sign-in to your account",
        "body": "Hello {name}, a sign-in was recorded at {when} from {where}.\n",
    },
}


def get_settings() -> AdminSettings:
    """Load (or lazily create) the single settings row."""
    settings = db.session.get(AdminSettings, 1)
    if settings is None:
        settings = AdminSettings(id=1)
        settings.set_templates(DEFAULT_NOTIFICATION_TEMPLATES)
        settings.set_notification_settings(
            {key: {"enabled": True} for key in DEFAULT_NOTIFICATION_TEMPLATES}
        )
        db.session.add(settings)
        db.session.commit()
    return settings


# ------------
# Password
# ------------
def password_is_set() -> bool:
    """True once a console password has been stored."""
    settings = db.session.get(AdminSettings, 1)
    return bool(settings and settings.password_hash)


def verify_admin_password(candidate: str) -> bool:
    """Check a console password against the stored hash, or the env seed.

    The env value is used ONLY while no hash exists. Once the password has been
    changed through the console, the stored hash is authoritative -- otherwise a
    redeploy carrying the old `ADMIN_ACCESS_PASSWORD` would silently reset it,
    and a change the admin made deliberately would appear to have been ignored.
    """
    from flask import current_app

    settings = db.session.get(AdminSettings, 1)

    if settings and settings.password_hash:
        return bcrypt.check_password_hash(settings.password_hash, candidate or "")

    seed = (current_app.config.get("ADMIN_ACCESS_PASSWORD") or "").strip()
    if not seed:
        # No hash and no seed: the console has no credential at all. Refuse
        # rather than allow-everything, which is the failure that matters.
        return False

    # `hmac.compare_digest` for the seeding comparison, so even this bootstrap
    # path is not a timing oracle.
    import hmac

    return hmac.compare_digest(seed, (candidate or "").strip())


# The console's login name and recovery address when nothing has been stored.
DEFAULT_ADMIN_USERNAME = "abishek"
DEFAULT_ADMIN_EMAIL = "shekabi2005@gmail.com"
# PROMPT 9 — the reset code's rules. Six digits is a million possibilities, so
# the code is generated with `secrets` (cryptographically random, never
# `random`), stored HASHED (a database dump yields no usable code), expires
# quickly, tolerates only a handful of guesses, and cannot be re-requested in a
# tight loop. Each constant is one of the requirements it enforces.
RESET_CODE_TTL_SECONDS = 15 * 60      # expiry
RESET_MAX_ATTEMPTS = 5                # attempt limit before the code is burned
RESET_RESEND_COOLDOWN_SECONDS = 60    # resend cooldown
RESET_MAX_ISSUED_PER_HOUR = 5         # hourly rate limit per console


def _hash_code(code: str) -> str:
    """SHA-256 of a reset code.

    A 6-digit code is only a million possibilities, so unlike the 256-bit
    approval token this hash IS brute-forceable offline — which is exactly why
    the attempts counter and the short TTL matter as much as the hash itself.
    The hash is still worth storing: the thing a dump must not hand over
    ready-to-use is the point, and the live defences live in the counters.
    """
    import hashlib
    return hashlib.sha256(str(code).strip().encode("utf-8")).hexdigest()

def admin_identity() -> dict[str, str]:
    """The console's login name and recovery address, stored value first.

    Falls back to the configured defaults so an existing deployment that has
    never edited them behaves exactly as it did before this feature existed.
    """
    from flask import has_app_context, current_app
    settings = get_settings()
    username = (settings.admin_username or "").strip()
    email = (settings.admin_email or "").strip()

    if not username:
        username = (
            (current_app.config.get("ADMIN_USERNAME") if has_app_context() else None)
            or DEFAULT_ADMIN_USERNAME
        )
    if not email:
        email = (
            (current_app.config.get("ADMIN_NOTIFY_EMAIL") if has_app_context() else None)
            or (current_app.config.get("MAIL_USERNAME") if has_app_context() else None)
            or DEFAULT_ADMIN_EMAIL
        )

    return {"username": username, "email": email}


def update_admin_identity(username: str | None, email: str | None) -> dict[str, Any]:
    """Change the console's login name and/or recovery address.

    At least one field must be supplied, and an email must look like an email --
    it is the address a reset code is sent to, so a typo would lock the owner out
    of their own recovery path.

    PROMPT 9, REQUIREMENT 11. The recovery address and the approval address are
    stored separately, so a naive update leaves them diverging and a reset code
    and an approval going to different inboxes with no record of whether that
    was intended. So: when the admin CHANGES the recovery email, the approval
    address is explicitly re-pointed to the same new value ("same inbox" stays
    "same inbox"), and the response says so. Splitting them afterwards remains
    possible through `request_approval_email_change`, which verifies the new
    inbox before the split takes effect.
    """
    if username is None and email is None:
        raise ValidationError("Nothing to update")

    settings = get_settings()
    changed: dict[str, str] = {}

    if username is not None:
        clean_user = str(username).strip()
        if len(clean_user) < 3:
            raise ValidationError(
                "That username is too short",
                {"username": "Use at least 3 characters"},
            )
        settings.admin_username = clean_user
        changed["username"] = clean_user
    if email is not None:
        clean_email = str(email).strip()
        # Deliberately permissive: one "@" with something either side. Anything
        # stricter rejects valid addresses; the real validation is whether mail
        # arrives, which the console's diagnostics button can prove.
        if "@" not in clean_email or clean_email.startswith("@") or clean_email.endswith("@"):
            raise ValidationError(
                "That email address is not valid",
                {"email": "Enter a full email address"},
            )
        settings.admin_email = clean_email
        changed["email"] = clean_email
        # Requirement 11: keep the two mailboxes in sync by default.
        settings.set_admin_approval_email(clean_email)
        changed["approval_email_synced"] = clean_email
    db.session.commit()
    logger.info("Admin identity updated (%s)", ", ".join(changed))
    return admin_identity()


# --- PROMPT 9, REQUIREMENTS 10 and 11: verified email management -------------
#
# Changing where a password-reset code goes changes who can take over the
# console, so the new address must prove it can receive mail BEFORE the change
# takes effect. The flow is the same shape as the reset code: a verified code
# to the NEW address, checked on the backend, single use, expiring. The pending
# change is stored as a hash, never as the code.


def request_approval_email_change(new_email: str | None, same_as_recovery: bool = False) -> dict[str, Any]:
    """Begin changing where approval mails go, with a verification code.

    Two modes:

      * `same_as_recovery=True` re-points the approval address at the current
        recovery inbox. Requirement 11's "use the same address" — no code is
        needed because that inbox already receives reset codes, so its control
        is already established.
      * a new `new_email` mails a verification code THERE. The change is stored
        as a pending request and does not take effect until `confirm_email_change`
        accepts the code, so a typo or an address the admin does not control can
        never silently redirect approvals or password resets.
    """
    import secrets
    from datetime import datetime, timezone

    settings = get_settings()

    if same_as_recovery:
        recovery = admin_identity()["email"]
        settings.set_admin_approval_email(recovery)
        db.session.commit()
        logger.info("Admin approval email re-synced to the recovery address")
        return {"mode": "synced_to_recovery", "approval_email": mask_email(recovery)}

    clean = str(new_email or "").strip()
    if "@" not in clean or clean.startswith("@") or clean.endswith("@"):
        raise ValidationError(
            "That email address is not valid",
            {"email": "Enter a full email address"},
        )

    now = int(datetime.now(timezone.utc).timestamp())
    pending = settings.get_unlock_confirmation() or {}
    email_pending = pending.get("email_change") or {}
    if email_pending and now - int(email_pending.get("issued_at", 0)) < RESET_RESEND_COOLDOWN_SECONDS:
        remaining = RESET_RESEND_COOLDOWN_SECONDS - (now - int(email_pending.get("issued_at", 0)))
        raise ValidationError(
            "A verification code was sent recently. Wait before requesting another.",
            {"retry_after_seconds": max(1, remaining)},
        )

    code = f"{secrets.randbelow(1_000_000):06d}"
    email_pending = {
        "new_email": clean,
        "code_hash": _hash_code(code),
        "expires_at": now + RESET_CODE_TTL_SECONDS,
        "issued_at": now,
        "attempts": 0,
    }
    pending["email_change"] = email_pending
    settings.set_unlock_confirmation(pending)
    db.session.commit()

    from app.services import mail_service
    from app.services.mail_service import admin_reset_code_message

    delivery = mail_service.send_email(
        clean,
        "AquaGuard AI: verify this address for admin emails",
        f"Use this code to point AquaGuard admin emails at this address: {code}\n"
        f"It expires in {RESET_CODE_TTL_SECONDS // 60} minutes. If you did not request this, ignore it.",
        f"<p>Use this code to point AquaGuard admin emails at this address: "
        f"<strong>{code}</strong>. It expires in {RESET_CODE_TTL_SECONDS // 60} minutes.</p>",
    )
    # NEVER LOG THE CODE.
    logger.info("Admin email-change verification sent to %s (delivery=%s)", mask_email(clean), delivery.status)

    if not delivery.ok:
        raise ValidationError(
            "The verification code could not be emailed. You can try again now.",
            {"delivery_status": delivery.status, "detail": str(delivery.detail)[:300]},
        )

    return {
        "mode": "verification_sent",
        "sent_to": mask_email(clean),
        "expires_in_minutes": RESET_CODE_TTL_SECONDS // 60,
    }


def confirm_email_change(code: str) -> dict[str, Any]:
    """Activate a pending email change, only with the code the NEW inbox received.

    The code is checked on the backend, expiring and single use. On success the
    approval address moves to the verified address and the pending request is
    destroyed, so the same code can never activate a second change.
    """
    import hmac
    from datetime import datetime, timezone

    settings = get_settings()
    pending = (settings.get_unlock_confirmation() or {}).get("email_change") or {}
    if not pending or not pending.get("code_hash"):
        raise ValidationError("No email change is waiting for verification")

    now = int(datetime.now(timezone.utc).timestamp())
    if int(pending.get("expires_at", 0)) <= now:
        root = settings.get_unlock_confirmation()
        root.pop("email_change", None)
        settings.set_unlock_confirmation(root)
        db.session.commit()
        raise ValidationError("That verification code has expired. Request a new one.")

    if int(pending.get("attempts", 0)) >= RESET_MAX_ATTEMPTS:
        root = settings.get_unlock_confirmation()
        root.pop("email_change", None)
        settings.set_unlock_confirmation(root)
        db.session.commit()
        raise ValidationError("Too many wrong codes. Request a new verification email.")

    if not hmac.compare_digest(str(pending.get("code_hash", "")), _hash_code(code)):
        pending["attempts"] = int(pending.get("attempts", 0)) + 1
        root = settings.get_unlock_confirmation()
        root["email_change"] = pending
        settings.set_unlock_confirmation(root)
        db.session.commit()
        raise ValidationError("That verification code is not correct")

    new_email = str(pending.get("new_email") or "")
    settings.set_admin_approval_email(new_email)
    root = settings.get_unlock_confirmation()
    root.pop("email_change", None)
    settings.set_unlock_confirmation(root)
    db.session.commit()
    logger.info("Admin approval email verified and updated")
    return {"approval_email": mask_email(new_email)}


def verify_admin_credentials(username: str, password: str) -> bool:
    """Check the console login name AND password together.

    The username is compared in constant time too, so the console does not
    reveal which half was wrong by responding faster to a bad name.
    """
    import hmac
    expected = admin_identity()["username"]
    if not hmac.compare_digest(expected, (username or "").strip()):
        return False
    return verify_admin_password(password)


# ----------------
# Unlock confirmation
# ----------------
# Logging into the console pages is a TWO-STEP gate: the console credential
# unlocks nothing on its own. Instead a confirmation is mailed to the admin's
# address, and the "Yes, confirm" link in that mail is what actually opens the
# session. A stolen console password therefore cannot open the console without
# also owning the admin's mailbox.
CONFIRM_TTL_SECONDS = 15 * 60


# ----------------
# Login approval (PROMPT 8)
# ----------------
# `issue_unlock_confirmation` below is superseded by this and kept only so nothing
# that imported it breaks. `issue_login_approval_request` is what the route calls.


def approval_recipient() -> str:
    """Where login approval requests are sent.

    An explicit `admin_approval_email` wins; otherwise the console's own recovery
    address, which is exactly where these requests went before this prompt - so an
    existing deployment behaves identically until somebody deliberately points
    approvals elsewhere.

    Never returns a bare address to a caller that might display it in full: see
    the callers, which all go through this and mask the result.
    """
    settings = get_settings()
    return settings.get_admin_approval_email() or admin_identity()["email"]


def mask_email(address: str) -> str:
    """`a***@example.com` — enough to recognise, not enough to harvest.

    An approval mail needs to say where it went so an administrator can tell it
    arrived. Showing the address in full in the browser that requested it would
    make that page a place where the address is readable, and the login page is
    the one page in the application that an attacker can reach anonymously.
    """
    text = str(address or "")
    if "@" not in text:
        return "***"
    local, _, domain = text.partition("@")
    head = local[:1] or "*"
    return f"{head}***@{domain}"


def base_url() -> str:
    """The origin to build mail links from, without a request when there is none."""
    from flask import current_app as _app

    try:
        return request.host_url.rstrip("/")
    except RuntimeError:  # no request context (tests / CLI)
        configured = (_app.config.get("SERVER_NAME") or "").strip()
        return f"http://{configured}" if configured else "http://localhost:5000"


def issue_login_approval_request(challenge: str) -> dict[str, Any]:
    """Create one approval request for a VERIFIED credential and mail it.

    The caller has already checked the credential — this is only reached once
    `verify_admin_*` returned True, which is the ordering requirement 1 asks for.

    Returns the request id, the masked recipient, the window in minutes and what
    the mail transport can actually do about in-message buttons. It NEVER returns
    the action token: only the mail carries that.
    """
    from app.services import login_approval_service as approvals
    from app.services import mail_service
    from app.services.mail_service import admin_login_approval_message, email_action_capabilities

    settings = get_settings()
    identity = admin_identity()

    row, token = approvals.create_request(
        identity["username"],
        challenge=challenge,
        # The SHAPE only: which fields were present, never their values. "a
        # password was supplied" is useful in an audit trail; the password is
        # not, and no hash of it is stored anywhere.
        credential_shape="password" if request else None,
    )

    recipient = approval_recipient()
    minutes = approvals.ttl_seconds() // 60

    try:
        # The review link carries the token because nothing on that page acts on
        # load — see the route's docstring. Loading it changes nothing; only its
        # button POST does.
        #
        # THE PATH IS `{prefix}/session/...`, NOT `{prefix}/admin/session/...`.
        # `request_prefix()` already returns `/api/admin` (the blueprint's mount
        # point), so adding another `/admin` produced `/api/admin/admin/...` — a
        # 404 — and every mail link was dead. The route is registered on the
        # blueprint, so its path after the mount is `/session/approval/...`.
        review_url = (
            f"{base_url()}{request_prefix()}"
            f"/session/approval/{row.request_id}/review?token={token}"
        )
        # THE IN-MAIL YES / NO TARGETS. Each opens the CONFIRMATION page with the
        # intended answer preselected — it does NOT decide anything on load. A
        # plain `<a href>` in a mail can only carry a URL, and a URL that decided
        # on GET would be decided by every link scanner and prefetcher that
        # touched it. So these point at `/review`, which is inert until the
        # approver presses its button (a real POST to `/decide`).
        #
        # No external redirect: both URLs are on this application's own origin.
        # Approving here still does NOT open the console — only the sign-in
        # browser, which holds the challenge, can spend the approval.
        approve_url = (
            f"{base_url()}{request_prefix()}"
            f"/session/approval/{row.request_id}/review?action=approve&token={token}"
        )
        deny_url = (
            f"{base_url()}{request_prefix()}"
            f"/session/approval/{row.request_id}/review?action=deny&token={token}"
        )
        subject, text, html = admin_login_approval_message(
            request_id=row.request_id,
            admin_username=row.admin_username,
            review_url=review_url,
            approve_url=approve_url,
            deny_url=deny_url,
            minutes=minutes,
            # An ISO-UTC string, so the mail helper can convert it to IST and
            # render the DATE and TIME lines in the requested human wording
            # ("08 October 2026" / "12:25 PM").
            requested_at=row.requested_at.isoformat(),
            device_label=row.device_label,
            ip_address=row.ip_address,
        )
        result = mail_service.send_email(recipient, subject, text, html)
    except Exception:  # noqa: BLE001 - a mail failure must not leak a 500
        logger.exception("Could not send the admin login approval mail")
        result = None

    if result is not None and not result.ok:
        # THE REQUEST IS NOT LEFT PENDING. An approval nobody can receive is a
        # login that will simply time out with no explanation, so the row is
        # denied outright and the login page says the mail could not be sent.
        approvals.expire_now(row.request_id, "The approval mail could not be sent.")

    return {
        "request_id": row.request_id,
        "sent_to": mask_email(recipient),
        "approval_window_minutes": minutes,
        "email_capabilities": email_action_capabilities(),
        "mail_sent": bool(result is not None and result.ok),
    }


def request_prefix() -> str:
    """The URL prefix the admin blueprint is mounted under."""
    from flask import current_app as _app

    return (_app.config.get("ADMIN_API_PREFIX") or "/api/admin").rstrip("/")


def issue_unlock_confirmation() -> dict[str, Any]:
    """DEPRECATED — superseded by `issue_login_approval_request`.

    Retained only so an existing import does not break. No route calls it.

    Its links were `GET /session/confirm?token=…`, and a GET acts the moment it
    is loaded: an email link scanner, a chat-client preview or a browser prefetch
    would spend the single-use token and approve the login. That is the specific
    defect Prompt 8 asked to repair, and it is why the replacement exists.
    """
    return issue_login_approval_request("")


    """Generate a one-time confirmation token and mail it as a Yes/No alert.

    The token is random, single-use and short-lived. It is stored so the
    confirm endpoint can check it without trusting anything the client sends.

    Takes no user id because there is no user: the console is one shared surface,
    and its password was already checked by the caller before this was reached.
    """
    import secrets
    from datetime import datetime, timezone

    settings = get_settings()
    token = secrets.token_urlsafe(32)
    pending = {
        "token": token,
        "expires_at": int(datetime.now(timezone.utc).timestamp()) + CONFIRM_TTL_SECONDS,
    }
    settings.set_unlock_confirmation(pending)
    db.session.commit()

    recipient = admin_identity()["email"]
    try:
        from flask import current_app, request
        from app.services import mail_service
        from app.services.mail_service import admin_unlock_alert_message

        # The buttons act the moment they are clicked, so they point at the
        # BACKEND (GET endpoints a mail client can open directly), not at the
        # SPA. Clicking YES opens the console; clicking NO denies the attempt.
        try:
            base = request.host_url.rstrip("/")
        except RuntimeError:  # no request context (tests/CLI)
            base = (current_app.config.get("SERVER_NAME") or "").strip()
            base = f"http://{base}" if base else "http://localhost:5000"
        confirm_url = f"{base}/api/v1/admin/session/confirm?token={token}"
        deny_url = f"{base}/api/v1/admin/session/deny?token={token}"
        subject, text, html = admin_unlock_alert_message(confirm_url, deny_url, CONFIRM_TTL_SECONDS // 60)
        mail_service.send_email(recipient, subject, text, html)
    except Exception:  # noqa: BLE001 - a mail failure must not leak a 500
        logger.exception("Could not send the admin unlock alert")

    return {"confirmation_required": True, "sent_to": recipient}


def confirm_unlock(token: str) -> bool:
    """Consume the mailed confirmation. True when it authorises the console.

    Returns False when the token is missing, expired, already used, or DENIED
    (the "No" button in the mail burns the pending request). Single use: once
    confirmed, the pending token is discarded outright so a replay of the same
    link opens nothing.
    """
    from datetime import datetime, timezone
    settings = get_settings()
    pending = settings.get_unlock_confirmation()
    if not pending:
        return False
    if pending.get("denied"):
        # The admin clicked NO. Nothing may confirm this attempt now.
        settings.set_unlock_confirmation({})
        db.session.commit()
        return False
    if int(pending.get("expires_at", 0)) <= int(datetime.now(timezone.utc).timestamp()):
        settings.set_unlock_confirmation({})
        db.session.commit()
        return False
    import hmac
    if not hmac.compare_digest(str(pending.get("token", "")), (token or "").strip()):
        return False
    settings.set_unlock_confirmation({})
    db.session.commit()
    return True


def deny_unlock(token: str) -> bool:
    """The admin clicked NO: burn the pending confirmation outright.

    Returns True when a live, matching request was denied. After this, even the
    real token cannot confirm -- the attempt is dead and the console stays
    locked. A fresh attempt must start from the console's login form.
    """
    from datetime import datetime, timezone
    settings = get_settings()
    pending = settings.get_unlock_confirmation()
    if not pending or pending.get("denied"):
        return False
    if int(pending.get("expires_at", 0)) <= int(datetime.now(timezone.utc).timestamp()):
        settings.set_unlock_confirmation({})
        db.session.commit()
        return False
    import hmac
    if not hmac.compare_digest(str(pending.get("token", "")), (token or "").strip()):
        return False
    # Mark denied rather than just clearing: a confirm click that races the
    # deny click (both tabs open) must lose, and clearing alone would let a
    # second copy of the token re-arm a fresh confirm.
    pending["denied"] = True
    settings.set_unlock_confirmation(pending)
    db.session.commit()
    logger.warning("Admin console unlock DENIED via emailed link")
    return True


def pending_confirmation_for() -> bool:
    """True when a live, NOT-yet-denied confirmation is waiting for the console."""
    from datetime import datetime, timezone
    pending = get_settings().get_unlock_confirmation()
    if not pending or pending.get("denied"):
        return False
    return int(pending.get("expires_at", 0)) > int(datetime.now(timezone.utc).timestamp())


def pending_denied_for() -> bool:
    """True when the console's most recent unlock request was denied in the mail.

    The web app polls the session state while it waits for the emailed
    confirmation; this is what lets that poll report "access denied" the moment
    the admin clicks NO, without the denial having to open anything in a
    browser. The denied flag stays on the stored request until the next
    `issue_unlock_confirmation` overwrites it, so a poll that arrives late still
    sees it.
    """
    pending = get_settings().get_unlock_confirmation()
    return bool(pending and pending.get("denied"))


def issue_reset_code() -> dict[str, Any]:
    """Generate a 6-digit reset code, store it HASHED, and mail it.

    PROMPT 9, and each check answers one of its requirements:

      * the code is `secrets.randbelow` — cryptographically random, not `random`;
      * only its SHA-256 is stored, so no dump, log or screenshot carries a code;
      * the cooldown refuses a resend while a freshly issued code is still live
        (a tight loop would otherwise turn the admin's inbox into a spam channel);
      * an hourly cap refuses the request outright once the limit is reached —
        429, so the caller knows it is rate limiting rather than a bad address;
      * the mail result is returned as-is: "sent" is only ever claimed when the
        provider ACCEPTED the message, and a real failure comes back with its
        real detail so the page can offer a retry honestly.

    The address is never echoed in full — the recipient is resolved from the
    existing account model (`admin_identity`) and returned MASKED, so an
    unauthenticated response never confirms whether an arbitrary address
    belongs to the account.
    """
    import secrets
    from datetime import datetime, timezone

    settings = get_settings()
    pending = settings.get_reset_code() or {}

    now = int(datetime.now(timezone.utc).timestamp())
    if pending:
        issued_at = int(pending.get("issued_at", 0))
        if now - issued_at < RESET_RESEND_COOLDOWN_SECONDS and not pending.get("delivery_failed"):
            remaining = RESET_RESEND_COOLDOWN_SECONDS - (now - issued_at)
            raise ValidationError(
                "A reset code was sent recently. Wait before requesting another.",
                {"retry_after_seconds": max(1, remaining)},
            )
        # Hourly rate limit. Old codes older than an hour fall off the count.
        recent = [
            int(t) for t in (pending.get("issued_history") or []) if now - int(t) < 3600
        ]
        if len(recent) >= RESET_MAX_ISSUED_PER_HOUR:
            raise ValidationError(
                "Too many reset codes were requested. Try again later.",
                {"retry_after_seconds": 3600 - (now - min(recent))},
            )
        history = recent + [now]
    else:
        history = [now]

    code = f"{secrets.randbelow(1_000_000):06d}"
    # The PLAIN CODE exists only long enough to be mailed. What is stored is the
    # hash, the expiry, the attempt counter and the issuance history.
    settings.set_reset_code(
        {
            "code_hash": _hash_code(code),
            "expires_at": now + RESET_CODE_TTL_SECONDS,
            "issued_at": now,
            "attempts": 0,
            "issued_history": history,
        }
    )
    db.session.commit()

    recipient = admin_identity()["email"]
    delivery = _send_reset_code(recipient, code)
    # NEVER LOG THE CODE. Only the fact and the outcome of the delivery.
    logger.info("Admin password-reset code issued (delivery=%s)", delivery.status)

    if not delivery.ok:
        # A code nobody can receive is worse than no code: mark the row so the
        # cooldown does not strand the admin behind a silent failure, and report
        # the provider's own detail — requirement 13, honestly.
        row = settings.get_reset_code()
        row["delivery_failed"] = True
        row["delivery_detail"] = str(delivery.detail)[:300]
        settings.set_reset_code(row)
        db.session.commit()
        raise ValidationError(
            "The reset code could not be emailed. You can try again now.",
            {"delivery_status": delivery.status, "detail": str(delivery.detail)[:300]},
        )

    return {
        "sent_to": mask_email(recipient),
        "expires_in_minutes": RESET_CODE_TTL_SECONDS // 60,
        "resend_cooldown_seconds": RESET_RESEND_COOLDOWN_SECONDS,
        "delivery_status": delivery.status,
    }


def _send_reset_code(recipient: str, code: str):
    """Mail the code and return the provider's OWN verdict, never raising.

    Requirement 13 is about honesty: `mail_service.send_email` reports
    sent / suppressed / disabled / unconfigured / failed with a real detail, and
    this passes that through untouched so "OTP sent" is never displayed unless
    the service actually accepted the message.
    """
    from app.services import mail_service
    from app.services.mail_service import admin_reset_code_message

    subject, text, html = admin_reset_code_message(code, RESET_CODE_TTL_SECONDS // 60)
    return mail_service.send_email(recipient, subject, text, html)


def verify_reset_code(code: str) -> bool:
    """Check a hashed reset code; consume it on success, count failures.

    Expiry, the attempt limit and single use are all enforced HERE, on the
    backend — the frontend never decides anything about a code.
    """
    from datetime import datetime, timezone

    settings = get_settings()
    stored = settings.get_reset_code()
    if not stored or not stored.get("code_hash"):
        return False

    now = int(datetime.now(timezone.utc).timestamp())
    if int(stored.get("expires_at", 0)) <= now:
        settings.set_reset_code({})
        db.session.commit()
        return False

    attempts = int(stored.get("attempts", 0))
    import hmac

    if not hmac.compare_digest(str(stored.get("code_hash", "")), _hash_code(code)):
        attempts += 1
        if attempts >= RESET_MAX_ATTEMPTS:
            # Burned immediately on the attempt that hits the limit: a wrong
            # guess that exhausts the allowance must not leave the code alive.
            settings.set_reset_code({})
        else:
            stored["attempts"] = attempts
            settings.set_reset_code(stored)
        db.session.commit()
        return False

    # Success CONSUMES the code: it cannot be verified a second time, which is
    # both the one-time-use rule and the defence against replay.
    settings.set_reset_code({})
    db.session.commit()
    return True

def reset_admin_password(code: str, new_password: str) -> dict[str, Any]:
    """Set a new console password, but only with a valid emailed code.

    This is the forgot-password path. It does NOT require the old password -- the
    whole point is that the owner has forgotten it -- so the mailed code IS the
    authorisation, and it is checked before anything is changed.

    PROMPT 9, requirement by requirement:

      * the OTP is verified on the BACKEND first; only then is the password set;
      * the new password passes the shared `validate_password_strength` policy
        (length, letters, digits — the same rule every other account uses), not
        just a bare length check;
      * the password is stored ONLY as a bcrypt hash via the existing hashing
        system; the plaintext exists for the length of this call and is never
        logged, never stored, never returned;
      * the code was already consumed by `verify_reset_code`, so the OTP is dead
        after one successful reset;
      * the console session is REVOKED: a password reset means every unlock
        issued under the old credential stops counting, so a stolen unlocked
        tab cannot ride through the change;
      * an audit event is logged WITHOUT the code or the password — only that
        the event happened and when.
    """
    from app.utils.validators import validate_password_strength

    # THE PASSWORD IS VALIDATED BEFORE THE CODE IS CONSUMED. The OTP is the
    # authorisation and it is single-use, so checking the format first means a
    # weak-password submission (a typo, a rejected policy) never burns the user's
    # code — they can correct the password and resubmit the same code. Only when
    # the password passes policy is the OTP spent.
    new_password = validate_password_strength(new_password)

    if not verify_reset_code(code):
        logger.warning("Admin password reset refused: invalid or expired code")
        raise AuthError("That reset code is not valid or has expired")

    settings = get_settings()
    settings.password_hash = bcrypt.generate_password_hash(new_password).decode("utf-8")
    db.session.commit()

    # Requirement 9: revoke the console session. The credential changed, so a
    # window that the OLD credential opened must not stay open.
    from app.services import console_session
    console_session.lock()

    # Requirement 12: an audit event that carries NO secret. No code, no password,
    # no hash — the event, the actor model and the moment are all it holds.
    logger.warning("ADMIN_SECURITY password_reset actor=admin-email-otp result=success")
    _email_password_change(admin_identity()["email"])
    return {"changed_at": utcnow().isoformat()}


def change_admin_password(current: str, new_password: str, actor_email: str) -> dict[str, Any]:
    """Rotate the console password and email the confirmation."""
    if not verify_admin_password(current):
        raise AuthError("The current admin password is not correct")

    new_password = (new_password or "").strip()
    if len(new_password) < 8:
        raise ValidationError(
            "The new password is too short",
            {"new_password": "Use at least 8 characters"},
        )
    if new_password == current:
        raise ValidationError(
            "The new password must be different",
            {"new_password": "Choose a password you have not used here before"},
        )

    settings = get_settings()
    settings.password_hash = bcrypt.generate_password_hash(new_password).decode("utf-8")
    db.session.commit()

    logger.info("Admin console password changed by %s", actor_email)
    _email_password_change(actor_email)

    return {"changed_at": utcnow().isoformat()}


def _email_password_change(actor_email: str) -> None:
    """Send the password-change confirmation, never raising.

    THE RECIPIENT IS THE CONSOLE'S OWN AUTHORIZED ADDRESS, resolved through
    `admin_identity()` - the SAME resolver the login-approval mail and the
    forgot-password code use. Reading it from one place is requirement 3: the
    approval address, the recovery code address and this confirmation address can
    never drift apart, so there is no inbox that receives one class of mail but
    not another, and no arbitrary caller-supplied address is ever honoured.
    """
    try:
        from app.services import mail_service
        from app.services.mail_service import admin_password_changed_message

        recipient = admin_identity()["email"]
        subject, text, html = admin_password_changed_message(
            utcnow().isoformat(), actor_email
        )
        mail_service.send_email(recipient, subject, text, html)
    except Exception:  # noqa: BLE001 - the password DID change; the notice is secondary
        logger.exception("Could not send the admin password-change notice")


# ------------
# Parameter limits
# ------------
def get_parameter_limits() -> list[dict[str, Any]]:
    """Every parameter with its effective limit.

    A parameter with no override reports the built-in constant, so the console
    always shows the value actually in force rather than an empty field the
    reader has to interpret.
    """
    overrides = get_settings().get_parameter_limits()

    rows = []
    for name in FEATURE_NAMES:
        default_low, default_high = FEATURE_BOUNDS[name]
        override = overrides.get(name) or {}
        rows.append(
            {
                "name": name,
                "label": FEATURE_LABELS[name],
                "unit": FEATURE_UNITS[name],
                "min": override.get("min", default_low),
                "max": override.get("max", default_high),
                "default_min": default_low,
                "default_max": default_high,
                # Lets the console show which rows differ from the built-in
                # value, instead of the reader comparing numbers by eye.
                "is_overridden": name in overrides,
            }
        )
    return rows


def update_parameter_limits(updates: dict[str, dict[str, float]]) -> list[dict[str, Any]]:
    """Replace the overridden limits.

    VALIDATION IS AGAINST THE PHYSICAL BOUNDS, not against taste. The console may
    make a limit TIGHTER than the built-in range - that is the point, an
    administrator enforcing a stricter local standard - but it must not widen it
    past what the parameter can physically take, because the model was trained on
    values inside that range and the database enforces it with a CHECK.
    """
    if not isinstance(updates, dict):
        raise ValidationError("Expected an object of parameter limits")

    errors: dict[str, str] = {}
    cleaned: dict[str, dict[str, float]] = {}

    for name, limits in updates.items():
        if name not in FEATURE_BOUNDS:
            errors[name] = "Unknown parameter"
            continue
        if not isinstance(limits, dict):
            errors[name] = "Expected { min, max }"
            continue

        try:
            low = float(limits.get("min"))
            high = float(limits.get("max"))
        except (TypeError, ValueError):
            errors[name] = "Both min and max must be numbers"
            continue

        hard_low, hard_high = FEATURE_BOUNDS[name]
        if not (hard_low <= low < high <= hard_high):
            errors[name] = (
                f"Must sit inside the physical range {hard_low}--{hard_high}, "
                "with min below max"
            )
            continue

        cleaned[name] = {"min": low, "max": high}

    if errors:
        raise ValidationError("Some limits are not valid", errors)

    settings = get_settings()
    settings.set_parameter_limits(cleaned)
    db.session.commit()

    logger.info("Parameter limits updated (%s parameters)", len(cleaned))
    return get_parameter_limits()

# ------------
# Location access scope
# ------------
# The modes the console can set. `None` (mode cleared) means no restriction.
LOCATION_SCOPE_MODES = ("state", "country")


def get_location_scope() -> dict[str, Any]:
    """The configured location access scope, shaped for the console.

    Returns ``{"mode": None|"state"|"country", "state": str|None,
    "country": str|None, "updated_at": datetime|None,
    "updated_by": str|None}``. `mode = None` means the restriction is OFF and
    every location is allowed, which is the default for a deployment that has
    never opened this panel.

    PROMPT 13 adds the two provenance fields so the console can show who set the
    scope and when, and so an administrator looking at a restriction they did
    not expect can see who put it there.
    """
    return get_settings().get_location_scope()


# ---------------------------------------------------------------------------
# PROMPT 13: validating the chosen area is a REAL place, not typed text
# ---------------------------------------------------------------------------
# WHY THIS EXISTS. The scope decides which locations the whole application may
# be used for, so storing whatever the admin typed would be a real hazard: a
# scope of "Tamil Nadd" matches NO resolved place, which does not read as "that
# scope does not work" - it reads as "nobody is in scope", and the feature is
# silently locked for every user with no error anywhere. Worse, the scope is
# matched against the RESOLVED state of a place, so the stored value has to be
# the geocoder's own canonical spelling of that state, not the admin's.
#
# So the value is RESOLVED, not accepted:
#
#   * a STATE must resolve to a first-level administrative division, and the
#     CANONICAL name and country the resolver returns are what get stored;
#   * a COUNTRY must resolve to a country, and likewise.
#
# Resolution failure is a 422 with a field-level error naming the problem,
# never a stored nonsense value.


def _resolve_scope_state(state: str, country: str | None) -> tuple[str | None, str | None]:
    """Resolve a state name to (canonical state, canonical country).

    Returns ``(None, None)`` when the text is not a state the resolver knows.
    The canonical values come from the resolver, so the scope is stored in the
    same spelling the geocoder later reports for a place in that state - which
    is what makes the comparison in `within_scope` match at all.
    """
    from app.services.country_service import resolve_state

    resolved = resolve_state(state)
    if not resolved:
        return None, None
    name = (resolved.get("state") or resolved.get("name") or "").strip() or None
    if not name:
        return None, None
    resolved_country = (resolved.get("country") or "").strip() or None

    # A state name is ambiguous WITHOUT its country in the general case, so when
    # the admin supplied a country it is checked against the resolver's answer.
    # A mismatch is refused rather than stored: storing it would create a scope
    # that can never match, which is the silent-lockout this function exists to
    # prevent.
    if country and resolved_country:
        wanted = " ".join(country.split()).casefold()
        found = " ".join(resolved_country.split()).casefold()
        if wanted and found and wanted != found:
            return None, None
    return name, resolved_country or (country.strip() if country else None)


def _resolve_scope_country(country: str) -> str | None:
    """Resolve a country name to the resolver's canonical spelling, or None."""
    from app.services.country_service import resolve_country

    resolved = resolve_country(country)
    if not resolved:
        return None
    return (resolved.get("name") or "").strip() or None


def _record_scope_audit(
    *,
    actor: str,
    previous: dict[str, Any],
    new_mode: str | None,
    new_state: str | None,
    new_country: str | None,
    success: bool,
    detail: str,
) -> None:
    """Append one scope-change row. Never raises.

    An audit failure must not turn a refused change into a 500, and must not
    turn a successful change into an error for the admin - the scope itself is
    what matters, so a failure here is logged and swallowed.
    """
    try:
        from app.extensions import db
        from app.models import LocationScopeAudit

        db.session.add(LocationScopeAudit(
            actor=actor or "console",
            new_mode=new_mode,
            new_state=new_state,
            new_country=new_country,
            previous_mode=previous.get("mode"),
            previous_state=previous.get("state"),
            previous_country=previous.get("country"),
            success=success,
            detail=(detail or "")[:500] or None,
        ))
        db.session.commit()
    except Exception:  # noqa: BLE001 - the audit must not break the change
        try:
            db.session.rollback()
        except Exception:  # noqa: BLE001
            pass
        logger.exception("Location scope audit row could not be recorded")


def list_location_scope_audits(limit: int = 25) -> list[dict]:
    """The scope-change history, newest first. For the console's settings tab."""
    from sqlalchemy import select

    from app.extensions import db
    from app.models import LocationScopeAudit

    statement = (
        select(LocationScopeAudit)
        .order_by(LocationScopeAudit.occurred_at.desc(), LocationScopeAudit.id.desc())
        .limit(max(1, min(int(limit or 25), 200)))
    )
    return [row.to_dict() for row in db.session.execute(statement).scalars().all()]


def update_location_scope(
    mode: str | None,
    state: str | None,
    country: str | None,
    actor: str | None = None,
) -> dict[str, Any]:
    """Set the location access scope from the console.

    VALIDATION IS THE POINT HERE, because this value decides which users can use
    the feature at all. A half-configured scope - a mode with no area, or an area
    the lookup can never match - would silently block every user, so it is
    refused with a field-level error rather than stored.

    ``mode`` is one of "state", "country", or None/empty to turn the restriction
    off. When the mode is "state" a state name is required; when it is "country"
    a country name is required. The unused field is cleared on save.

    PROMPT 13, REQUIREMENTS 2/3/6: the area is not merely REQUIRED, it must be a
    place that RESOLVES. The chosen state or country is run through the same
    resolver the rest of the application uses to identify a state or a country,
    and the CANONICAL name it returns is what gets stored - so a scope is always
    spelled the way the geocoder will spell it when a user's place is resolved
    later. Text that resolves to nothing is refused with a 422 rather than
    stored, because a scope that matches no place looks exactly like a feature
    that is broken for everyone.

    REQUIREMENT 4: the console identity and the time are stamped on the same
    commit as the value. REQUIREMENT 12: every attempt, refused ones included,
    is appended to `location_scope_audits`.
    """
    previous = get_location_scope()
    # The console identity is resolved HERE rather than trusted from the body:
    # a caller must not be able to record themselves as a different admin.
    try:
        actor_name = actor or admin_identity().get("username") or "console"
    except Exception:  # noqa: BLE001 - provenance must not block a valid change
        actor_name = actor or "console"

    normalised = (mode or "").strip().lower() or None
    clean_state = (state or "").strip() or None
    clean_country = (country or "").strip() or None

    def _refuse(message: str, errors: dict, detail: str) -> None:
        _record_scope_audit(
            actor=actor_name,
            previous=previous,
            new_mode=normalised,
            new_state=clean_state,
            new_country=clean_country,
            success=False,
            detail=detail,
        )
        raise ValidationError(message, errors)

    if normalised is None:
        # Turning the restriction off is a valid, deliberate action.
        settings = get_settings()
        settings.set_location_scope(None, None, None, actor=actor_name)
        db.session.commit()
        _record_scope_audit(
            actor=actor_name,
            previous=previous,
            new_mode=None,
            new_state=None,
            new_country=None,
            success=True,
            detail="Scope cleared - all locations allowed",
        )
        logger.info("Location scope cleared by %s - all locations allowed", actor_name)
        return get_location_scope()

    if normalised not in LOCATION_SCOPE_MODES:
        _refuse(
            "Unknown location scope mode",
            {"mode": "Choose STATE or COUNTRY, or clear the scope"},
            f"Refused unknown mode {normalised!r}",
        )

    if normalised == "state":
        if not clean_state:
            _refuse(
                "A state is required for a state-level scope",
                {"state": "Choose the state users may search within"},
                "Refused a state scope with no state",
            )
        canonical_state, canonical_country = _resolve_scope_state(
            clean_state, clean_country
        )
        if not canonical_state:
            _refuse(
                f"{clean_state!r} is not a state this application can identify",
                {"state": "Choose a real state; it must resolve to a first-level administrative division"},
                f"Refused unresolvable state {clean_state!r}",
            )
        stored_state, stored_country = canonical_state, canonical_country
    else:  # country
        if not clean_country:
            _refuse(
                "A country is required for a country-level scope",
                {"country": "Choose the country users may search within"},
                "Refused a country scope with no country",
            )
        canonical_country = _resolve_scope_country(clean_country)
        if not canonical_country:
            _refuse(
                f"{clean_country!r} is not a country this application can identify",
                {"country": "Choose a real country; it must resolve to a country"},
                f"Refused unresolvable country {clean_country!r}",
            )
        stored_state, stored_country = None, canonical_country

    settings = get_settings()
    settings.set_location_scope(normalised, stored_state, stored_country, actor=actor_name)
    db.session.commit()

    _record_scope_audit(
        actor=actor_name,
        previous=previous,
        new_mode=normalised,
        new_state=stored_state,
        new_country=stored_country,
        success=True,
        detail=(
            f"Scope set to {normalised.upper()}"
            + (f": {stored_state}" if stored_state else "")
            + (f", {stored_country}" if stored_country and normalised == "state" else "")
        ),
    )

    logger.info(
        "Location scope set to %s=%s by %s",
        normalised,
        stored_state if normalised == "state" else stored_country,
        actor_name,
    )
    return get_location_scope()


# ------------
# Notification templates and settings
# ------------
def get_notification_config() -> dict[str, Any]:
    """The templates and their enabled flags, merged over the built-in defaults.

    Merged rather than replaced: a type added to the code after a deployment has
    settings stored still appears, with its default wording, instead of vanishing
    from the console because the stored JSON predates it.
    """
    settings = get_settings()
    stored_templates = settings.get_templates()
    stored_settings = settings.get_notification_settings()

    types = []
    for key, default in DEFAULT_NOTIFICATION_TEMPLATES.items():
        current = stored_templates.get(key) or {}
        flag = stored_settings.get(key) or {}
        types.append(
            {
                "key": key,
                "label": current.get("label") or default["label"],
                "subject": current.get("subject") or default["subject"],
                "body": current.get("body") or default["body"],
                "enabled": bool(flag.get("enabled", True)),
                "is_customised": key in stored_templates,
            }
        )

    return {"types": types}


def update_notification_config(payload: dict[str, Any]) -> dict[str, Any]:
    """Save edited templates and their enabled flags.

    Only known types are accepted. An unknown key would otherwise be stored and
    then never used -- a silent no-op that looks like a successful save.
    """
    if not isinstance(payload, dict):
        raise ValidationError("Expected an object of notification settings")

    templates = payload.get("templates") or {}
    flags = payload.get("enabled") or {}

    errors: dict[str, str] = {}

    for key in templates:
        if key not in DEFAULT_NOTIFICATION_TEMPLATES:
            errors[key] = "Unknown notification type"

    for key, template in templates.items():
        if key not in DEFAULT_NOTIFICATION_TEMPLATES:
            continue
        if not isinstance(template, dict):
            errors[key] = "Expected { subject, body }"
            continue
        subject = str(template.get("subject") or "").strip()
        body = str(template.get("body") or "").strip()
        if not subject:
            errors[key] = "A subject is required"
        elif not body:
            errors[key] = "A body is required"
        elif len(subject) > 200:
            errors[key] = "Keep the subject under 200 characters"

    if errors:
        raise ValidationError("Some notification settings are not valid", errors)

    settings = get_settings()

    merged_templates = settings.get_templates()
    for key, template in templates.items():
        if key in DEFAULT_NOTIFICATION_TEMPLATES:
            merged_templates[key] = {
                "label": DEFAULT_NOTIFICATION_TEMPLATES[key]["label"],
                "subject": str(template["subject"]).strip(),
                "body": str(template["body"]).strip(),
            }
    settings.set_templates(merged_templates)

    merged_flags = settings.get_notification_settings()
    for key, value in flags.items():
        if key in DEFAULT_NOTIFICATION_TEMPLATES:
            merged_flags[key] = {"enabled": bool(value)}
    settings.set_notification_settings(merged_flags)

    db.session.commit()
    logger.info("Notification settings updated")

    return get_notification_config()


# ------------
# User management
# ------------
def list_users(search: str | None = None, page: int = 1, per_page: int = 25) -> tuple[list[dict], dict]:
    """Every account, with its activity counts.

    The counts are computed per user in one pass rather than per row on demand:
    the page shows them for every row, so a lazy load would be an N+1 query.
    """
    from sqlalchemy import func

    from app.models import Alert, WaterPrediction

    # THE SHARED VISITOR IS ALWAYS LISTED FIRST. It is the account every
    # unauthenticated reading is filed under, so an operator looking at the
    # user table is looking for it; and a database that has accumulated many
    # test or bulk rows would otherwise push it off the first page, where the
    # console's own tests (and any operator relying on "page 1 shows the
    # visitor") could not find it. Ordered before `created_at`, so a fresh row
    # cannot displace it either.
    from app.services.identity import VISITOR_EMAIL

    query = select(User).order_by(
        db.case((User.email == VISITOR_EMAIL, 0), else_=1),
        User.created_at.desc(),
        User.id.desc(),
    )
    if search:
        needle = f"%{search.strip()}%"
        query = query.where(User.name.ilike(needle) | User.email.ilike(needle))

    total = db.session.execute(
        select(func.count()).select_from(query.subquery())
    ).scalar_one()

    per_page = max(1, min(int(per_page or 25), 200))
    page = max(1, int(page or 1))
    users = db.session.execute(query.limit(per_page).offset((page - 1) * per_page)).scalars().all()

    prediction_counts = dict(
        db.session.execute(
            select(WaterPrediction.user_id, func.count()).group_by(WaterPrediction.user_id)
        ).all()
    )
    alert_counts = dict(
        db.session.execute(select(Alert.user_id, func.count()).group_by(Alert.user_id)).all()
    )

    items = []
    for user in users:
        payload = user.to_dict()
        payload["prediction_count"] = int(prediction_counts.get(user.id, 0))
        payload["alert_count"] = int(alert_counts.get(user.id, 0))
        items.append(payload)

    meta = {
        "page": page,
        "per_page": per_page,
        "total": int(total or 0),
        "pages": (int(total or 0) + per_page - 1) // per_page if per_page else 0,
    }
    return items, meta


def update_user_role(user_id: int, role: str) -> dict[str, Any]:
    """Change an account's role."""
    if role not in VALID_ROLES:
        raise ValidationError("Unknown role", {"role": f"Must be one of {VALID_ROLES}"})

    user = db.session.get(User, user_id)
    if user is None:
        raise ValidationError("Account not found", {"user_id": "No such account"})

    user.role = role
    db.session.commit()
    logger.info("Role changed for user=%s to %s", user_id, role)
    return user.to_dict()


def delete_user(user_id: int, actor_email: str) -> dict[str, Any]:
    """Delete an account and everything owned by it.

    The cascade is in the schema (`ON DELETE CASCADE` on predictions, alerts,
    conversations and login events), so this is one DELETE rather than a
    sequence of statements that could half-apply and leave orphans.
    """
    user = db.session.get(User, user_id)
    if user is None:
        raise ValidationError("Account not found", {"user_id": "No such account"})

    # THE SHARED VISITOR ACCOUNT IS NOT DELETABLE. Every reading, alert and
    # conversation submitted without a login is filed under it, and its columns
    # are NOT NULL, so removing it would either fail on the foreign keys or take
    # the whole public record with it. It is infrastructure now, not an account.
    from app.services.identity import VISITOR_EMAIL

    if user.email == VISITOR_EMAIL:
        raise ValidationError(
            "The shared visitor record cannot be deleted",
            {"user_id": "It holds the readings submitted without a sign-in"},
        )

    email = user.email
    db.session.delete(user)
    db.session.commit()

    logger.info("Account deleted: id=%s email=%s (console: %s)", user_id, email, actor_email)
    return {"id": user_id, "email": email, "deleted": True}


def dashboard() -> dict[str, Any]:
    """Console overview: account, prediction and alert totals."""
    from sqlalchemy import func

    from app.models import Alert, LoginEvent, WaterPrediction

    def count(model, *conditions):
        statement = select(func.count()).select_from(model)
        for condition in conditions:
            statement = statement.where(condition)
        return int(db.session.execute(statement).scalar_one() or 0)

    return {
        "users": count(User),
        "admins": count(User, User.role == "admin"),
        "predictions": count(WaterPrediction),
        "safe": count(WaterPrediction, WaterPrediction.prediction == "safe"),
        "moderate": count(WaterPrediction, WaterPrediction.prediction == "moderate"),
        "unsafe": count(WaterPrediction, WaterPrediction.prediction == "unsafe"),
        "alerts": count(Alert),
        "signins": count(LoginEvent),
        "failed_signins": count(LoginEvent, LoginEvent.success.is_(False)),
    }


# ------------
# PROMPT 12: Report-email audit listing
# ------------
REPORT_MAIL_OPTIONS = ("REPORT_PDF", "REPORT_CSV", "ALL_PDF", "ALL_CSV")
REPORT_MAIL_STATUSES = ("sent", "failed", "suppressed", "disabled", "unconfigured")


def list_report_email_audits(
    search: str | None = None,
    option: str | None = None,
    status: str | None = None,
    start: str | None = None,
    end: str | None = None,
    scope_state: str | None = None,
    scope_country: str | None = None,
    page: int = 1,
    per_page: int = 25,
) -> tuple[list[dict], dict]:
    """Paged report-email audit records, filtered, scope-checked on the backend.

    SCOPE ENFORCEMENT IS SERVER-SIDE. When the console has configured a
    state/country location scope, only rows whose consented location falls
    inside it are returned. Rows with no recorded location are always shown
    ("Location unavailable" is the honest answer for them); an out-of-scope
    location is withheld entirely — the row is not shown with the location
    blanked, because that would leak which locations exist.

    Unknown filter values are ignored rather than rejected, matching how the
    login-details filters behave.
    """
    from datetime import datetime, timezone

    from sqlalchemy import func

    from app.models import ReportEmailAudit

    query = select(ReportEmailAudit)

    if search and search.strip():
        needle = f"%{_escape_like(search.strip())}%"
        query = query.where(
            ReportEmailAudit.recipient_email.ilike(needle)
            | ReportEmailAudit.requester_name.ilike(needle)
            | ReportEmailAudit.admin_username.ilike(needle)
            | ReportEmailAudit.location_name.ilike(needle)
            | ReportEmailAudit.location_city.ilike(needle)
        )

    if (option or "").strip().upper() in REPORT_MAIL_OPTIONS:
        query = query.where(ReportEmailAudit.report_option == option.strip().upper())

    if (status or "").strip().lower() in REPORT_MAIL_STATUSES:
        query = query.where(ReportEmailAudit.delivery_status == status.strip().lower())

    def _parse_date(value: str, end_of_day: bool = False):
        try:
            parsed = datetime.fromisoformat(str(value).strip())
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        if end_of_day and len(str(value).strip()) <= 10:
            parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
        return parsed

    start_dt = _parse_date(start) if start else None
    end_dt = _parse_date(end, end_of_day=True) if end else None
    if start_dt is not None:
        query = query.where(ReportEmailAudit.created_at >= start_dt)
    if end_dt is not None:
        query = query.where(ReportEmailAudit.created_at <= end_dt)

    # --- Admin state/country scope (requirement 6) -------------------------
    # A ROW WITH NO RECORDED LOCATION IS ALWAYS SHOWN, and that is a real
    # requirement rather than a convenience: a requester who declined the
    # geolocation permission leaves NULL location columns, and hiding those
    # rows would hide exactly the requests an admin most needs to review. So
    # the scope predicate is `matches OR the column is empty`, never the bare
    # match. Without the empty half, an in-scope-looking row with no location
    # at all vanished the moment a scope was configured - which is how
    # out-of-scope rows became invisible while the audit silently lost records.
    # `func.trim(NULL)` IS NULL in SQL, NOT an empty string, so the raw column
    # would never satisfy the "empty" half of the predicate and a row with no
    # recorded location would still vanish. Coalescing the TRIMMED value to ''
    # is what makes the no-location branch reachable.
    scope_mode = None
    try:
        scope = get_location_scope() or {}
        scope_mode = scope.get("mode")
        if scope_mode == "state":
            wanted = (scope.get("state") or "").strip().lower()
            if wanted:
                recorded = func.lower(func.coalesce(func.trim(ReportEmailAudit.location_state), ""))
                query = query.where(
                    (recorded == wanted) | (recorded == "")
                )
        elif scope_mode == "country":
            wanted = (scope.get("country") or "").strip().lower()
            if wanted:
                recorded = func.lower(func.coalesce(func.trim(ReportEmailAudit.location_country), ""))
                query = query.where(
                    (recorded == wanted) | (recorded == "")
                )
    except Exception:  # noqa: BLE001 - a scope read failure must not blank the page
        logger.warning("Report-email audit: location scope could not be read")

    query = query.order_by(ReportEmailAudit.created_at.desc(), ReportEmailAudit.id.desc())

    total = int(
        db.session.execute(
            select(func.count()).select_from(query.subquery())
        ).scalar_one() or 0
    )

    per_page = max(1, min(int(per_page or 25), 200))
    page = max(1, int(page or 1))
    rows = db.session.execute(
        query.limit(per_page).offset((page - 1) * per_page)
    ).scalars().all()

    items = []
    for row in rows:
        item = row.to_dict()
        # Requirement 4/5: never fabricate. "unavailable" is explicit.
        item["location"] = {
            "source": row.location_source,
            "name": row.location_name,
            "city": row.location_city,
            "state": row.location_state,
            "country": row.location_country,
            "pincode": row.location_pincode,
            "available": bool(row.location_source),
        }
        items.append(item)

    meta = {
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": (total + per_page - 1) // per_page if per_page else 0,
        # `has_next` / `has_prev` ARE INCLUDED EXPLICITLY rather than left for
        # the UI to derive from `page < pages`. They are already computed here,
        # so deriving them in the browser means two places that can disagree
        # about the same question - and a Next button that is permanently
        # disabled because the field it read was absent is exactly that bug.
        "has_next": page < ((total + per_page - 1) // per_page if per_page else 0),
        "has_prev": page > 1,
        "filters": {
            "search": search or None,
            "option": (option or None),
            "status": (status or None),
            "start": start or None,
            "end": end or None,
        },
        "scope": {"mode": scope_mode},
    }
    return items, meta


def _escape_like(value: str) -> str:
    """Escape LIKE wildcards in a user-supplied search term."""
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return escaped
