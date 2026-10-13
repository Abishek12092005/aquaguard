"""Outbound email: the transport, and the messages this application sends.

TRANSPORT. Plain `smtplib` rather than Flask-Mail. Flask-Mail would add a
dependency to wrap the same twenty lines, and this way the failure modes are all
in one place: connect, STARTTLS, login, send.

NEVER LET EMAIL BREAK A REQUEST. Every public function here returns a result
object and never raises. A registration that fails because Gmail was unreachable
is worse than one that succeeds and sends no mail -- the account exists, the
notification is a courtesy. Callers that care inspect the returned `MailResult`.

SUPPRESSION. `MAIL_SUPPRESS_SEND` short-circuits the whole thing and reports
`suppressed`, so a test run or a local development session never opens a socket
to a real provider. The message is still fully BUILT, so the templates are
exercised either way -- a suppression that skipped rendering would let a broken
template ship.

THE APP PASSWORD. The credential in the environment is a provider app password
(Gmail: a 16-character password generated for a specific app), not the account
password. Gmail refuses plain-password SMTP auth, and an app password is
revocable on its own -- which is what makes it acceptable in a `.env` rather than
a reason to hardcode a login.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from zoneinfo import ZoneInfo
from typing import Any

from flask import current_app

# Messages that were built but suppressed (MAIL_SUPPRESS_SEND) are recorded here
# so a test or developer session can recover what WOULD have gone out without
# ever opening a socket. A sink that only logs "suppressed" would leave no way
# to assert the message body, which is exactly what a test needs to read.
SUPPRESSED_MESSAGES: list[EmailMessage] = []

logger = logging.getLogger(__name__)


@dataclass
class MailResult:
    """Outcome of one send attempt.

    `status` is one of:
        "sent"        delivered to the provider
        "suppressed"  MAIL_SUPPRESS_SEND was on; nothing was sent
        "disabled"    MAIL_ENABLED was off
        "unconfigured" no username/password set
        "failed"      any transport or auth failure
    """

    status: str
    detail: str = ""
    recipient: str = ""

    @property
    def ok(self) -> bool:
        # `suppressed` counts as ok: nothing went wrong, the mail was just not
        # sent by choice. A caller checking `ok` should not treat a deliberate
        # suppression as an error.
        return self.status in {"sent", "suppressed"}


def is_configured() -> bool:
    """True when the transport has everything it needs to attempt a send."""
    config = current_app.config
    return bool(config.get("MAIL_USERNAME") and config.get("MAIL_PASSWORD"))


def _sender() -> tuple[str, str]:
    """The (address, display name) a message is sent from."""
    config = current_app.config
    address = (
        config.get("MAIL_DEFAULT_SENDER")
        or config.get("MAIL_USERNAME")
        or ""
    )
    return address, config.get("MAIL_FROM_NAME") or "AquaGuard AI"


def send_email(
    to: str,
    subject: str,
    text_body: str,
    html_body: str | None = None,
    attachments: list[tuple[str, bytes, str]] | None = None,
) -> MailResult:
    """Send one message, swallowing every failure into a `MailResult`.

    A multipart message is always built -- plain text plus HTML when HTML is
    supplied. A text-only fallback is not an afterthought: some clients and every
    plain-text terminal show it, and it is what a spam filter reads.

    `attachments` is an OPTIONAL list of (filename, bytes, mime_type) triples,
    used by the Reports-to-Mail feature. When absent (every existing caller) the
    message is built exactly as before -- no call site changes behaviour.
    """
    config = current_app.config
    recipient = (to or "").strip()

    if not recipient:
        return MailResult("failed", "No recipient address", recipient)

    # REFUSE ADDRESSES THAT CANNOT EXIST ON THE INTERNET.
    #
    # `abishek@aquaguard.local` looks like an address but there is no such mail
    # domain, so SMTP accepts the message and the provider later bounces it back
    # with "Address not found ... the domain aquaguard.local couldn't be found".
    # Sending anyway is exactly what produced that bounce and the misleading
    # "Email sent to ..." log line. Detecting it here turns a silent, provider-
    # side failure into a clear, immediate result the caller can act on.
    from app.utils.validators import NON_DELIVERABLE_TLDS
    _domain = recipient.rsplit("@", 1)[-1].lower() if "@" in recipient else ""
    if _domain and any(_domain.endswith(reserved) for reserved in NON_DELIVERABLE_TLDS):
        logger.info("Email to %s not sent: undeliverable domain", recipient)
        return MailResult(
            "failed",
            f"The address {recipient} is on a domain that cannot receive mail",
            recipient,
        )

    if not config.get("MAIL_ENABLED", True):
        return MailResult("disabled", "MAIL_ENABLED is off", recipient)

    sender_address, sender_name = _sender()
    if not sender_address:
        return MailResult("failed", "No sender address", recipient)

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((sender_name, sender_address))
    message["To"] = recipient
    # A Message-ID with the sender's own domain. Providers are more likely to
    # treat a message as legitimate when it carries one it can trace.
    message["Message-ID"] = make_msgid(domain=sender_address.split("@")[-1] or None)
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")
    for filename, payload, mime in attachments or []:
        # The attachment's maintype/subtype come from its declared MIME type;
        # the bytes are added raw. A malformed triple is skipped rather than
        # aborting the whole message.
        try:
            maintype, subtype = mime.split("/", 1)
            message.add_attachment(
                bytes(payload), maintype=maintype, subtype=subtype, filename=filename,
            )
        except (ValueError, TypeError):
            logger.warning("Skipping malformed attachment %r", filename)

    if config.get("MAIL_SUPPRESS_SEND", False):
        logger.info("Email to %s suppressed (MAIL_SUPPRESS_SEND)", recipient)
        # The message is already built, so record it for inspection by tests
        # and local development before suppressing the actual send.
        SUPPRESSED_MESSAGES.append(message)
        return MailResult("suppressed", "MAIL_SUPPRESS_SEND is on", recipient)

    host = config.get("MAIL_HOST") or "smtp.gmail.com"
    port = int(config.get("MAIL_PORT") or 587)
    timeout = int(config.get("MAIL_TIMEOUT") or 15)
    username = config.get("MAIL_USERNAME") or ""
    password = config.get("MAIL_PASSWORD") or ""
    use_ssl = bool(config.get("MAIL_USE_SSL"))
    use_tls = bool(config.get("MAIL_USE_TLS"))

    try:
        if use_ssl:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, timeout=timeout, context=context) as server:
                server.login(username, password)
                server.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=timeout) as server:
                server.ehlo()
                if use_tls:
                    server.starttls(context=ssl.create_default_context())
                    server.ehlo()
                server.login(username, password)
                server.send_message(message)
    except smtplib.SMTPAuthenticationError:
        # The most common real failure: an app password was used where a normal
        # password is required, or the app password was revoked. Logged with the
        # host but NOT the credential.
        logger.warning("SMTP authentication rejected by %s", host)
        return MailResult("failed", f"Authentication rejected by {host}", recipient)
    except smtplib.SMTPException as exc:
        logger.warning("SMTP error sending to %s: %s", recipient, type(exc).__name__)
        return MailResult("failed", f"SMTP error: {type(exc).__name__}", recipient)
    except (OSError, ssl.SSLError) as exc:
        logger.warning("SMTP connection to %s failed: %s", host, type(exc).__name__)
        return MailResult("failed", f"Could not reach {host}", recipient)

    logger.info("Email sent to %s (%s)", recipient, subject)
    return MailResult("sent", subject, recipient)


# ------------------
# Messages
# ------------------
# Each builder returns (subject, text, html). They are pure string functions so
# they are testable without a mail server, and so the suppression path exercises
# exactly the same rendering as a real send.

_BRAND = "AquaGuard AI"


def _wrap_html(title: str, intro: str, rows: list[tuple[str, str]], footer: str) -> str:
    """One inline-styled HTML shell for every message.

    Styling is inline rather than in a <style> block because Gmail strips
    <style> from the head, which is the single most common reason a template
    looks right in preview and broken in the inbox.
    """
    cells = "".join(
        '<tr>'
        f'<td style="padding:8px 0;color:#475569;font-size:13px;">{label}</td>'
        f'<td style="padding:8px 0;color:#0f172a;font-size:13px;font-weight:600;'
        f'text-align:right;">{value}</td>'
        '</tr>'
        for label, value in rows
    )

    return f"""\
<!doctype html>
<html><body style="margin:0;padding:24px;background:#eff9ff;
     font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
 <table role="presentation" cellpadding="0" cellspacing="0" width="100%"
         style="max-width:560px;margin:0 auto;background:#ffffff;border-radius:14px;
                border-top:3px solid #0e9de8;">
    <tr><td style="padding:28px;">
      <p style="margin:0 0 4px;font-size:18px;font-weight:700;color:#0f172a;">{_BRAND}</p>
      <p style="margin:0 0 20px;font-size:11px;letter-spacing:0.18em;
                text-transform:uppercase;color:#007cc6;">{title}</p>
      <p style="margin:0 0 16px;font-size:14px;line-height:1.6;color:#334155;">{intro}</p>
      <table role="presentation" cellpadding="0" cellspacing="0" width="100%"
             style="border-top:1px solid #e2e8f0;border-bottom:1px solid #e2e8f0;">
        {cells}
      </table>
      <p style="margin:18px 0 0;font-size:12px;line-height:1.6;color:#64748b;">{footer}</p>
    </td></tr>
 </table>
</body></html>"""


def _location_rows(place: dict | None) -> list[tuple[str, str]]:
    """The location lines an admin notice shows, as (label, value) rows.

    Only the APPROXIMATE place is returned - name, city, state, country and
    pincode - and never a latitude or longitude. When nothing usable was
    supplied, a single honest row says so, so the notice never shows a blank where
    a location is expected and never invents one.

    The rows are the same for a registration and a sign-in, so both notices
    describe a place identically.
    """
    place = place if isinstance(place, dict) else {}
    # Accept BOTH shapes a caller may pass: the client payload (`name`, `city`, ...)
    # and a stored login-event row (`location_name`, `location_city`, ...). The two
    # name the same things, and a notice must describe them identically whichever
    # one it was handed.
    def field(*keys: str):
        for key in keys:
            value = place.get(key)
            if value:
                return value
        return None

    name = _clean(field("name", "location_name"))
    city = _clean(field("city", "location_city"))
    state = _clean(field("state", "location_state"))
    country = _clean(field("country", "location_country"))
    pincode = _clean(field("pincode", "location_pincode"))

    # "Location" leads with the place name, falling back to the city, so a row
    # exists whenever ANY part of the place is known. The remaining parts are
    # added only when present and never repeat a value already shown.
    location = name or city
    # When nothing is known, the notice states the exact sentence on its own line
    # rather than "Location: Location unavailable", which reads as a doubling.
    if not location and not state and not country:
        return [(_LOCATION_UNAVAILABLE, "")]

    rows: list[tuple[str, str]] = []
    rows.append(("Location", location or _LOCATION_UNAVAILABLE))
    if city and city != location:
        rows.append(("City", city))
    if state:
        rows.append(("State", state))
    if country:
        rows.append(("Country", country))
    if pincode:
        rows.append(("Pincode", pincode))
    return rows


def _clean(value) -> str | None:
    """Normalise an email field value, or drop it."""
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None


# The exact sentence shown when no approximate place was available. Kept here so
# every notice and the console agree on the wording.
_LOCATION_UNAVAILABLE = "Location unavailable"


def admin_signup_notice(
    name: str, email: str, when: str, location: dict | None = None
) -> tuple[str, str, str]:
    """Sent to the ADMIN when a NEW USER REGISTERS an account.

    Parallel to `admin_signin_notice`, but for registrations rather than
    sign-ins: it tells the administrator that a new account now exists, with the
    name, the email, when it was created, and WHERE it came from as an APPROXIMATE
    PLACE. The same recipient rule applies (`ADMIN_NOTIFY_EMAIL`, falling back to
    the sending account), and the timestamp is split into DATE and TIME lines the
    same way, so every admin notice reads the same.

    PRIVACY: only the place labels are included. The raw coordinates are never
    sent - the admin needs to know the area, not the user's exact position.
    """
    date_part, time_part = _split_date_time(when)
    place_rows = _location_rows(location)
    subject = f"{_BRAND}: new user registered and signed in - {name}"
    text_lines = [
        f"A new user registered on {_BRAND} and the sign-in was recorded.",
        "",
        f"Name: {name}",
        f"Email: {email}",
    ]
    text_lines += [f"{label}: {value}" if value else label for label, value in place_rows]
    text_lines += [
        f"Date: {date_part}",
        f"Time: {time_part}",
        "",
        "This notice is sent to the administrator on every new registration.",
        "",
        f"-- {_BRAND}",
    ]
    text = "\n".join(text_lines)
    html = _wrap_html(
        "New user registered",
        f"A new user registered on {_BRAND}.",
        [("Name", name), ("Email", email), *place_rows, ("Date", date_part), ("Time", time_part)],
        "Sent to the administrator on every new registration.",
    )
    return subject, text, html


def welcome_message(email: str, name: str, created_at: str) -> tuple[str, str, str]:
    """Sent to the NEW USER the moment their account is created.

    The subject and the first line say plainly what happened -- a new account
    was created with this email -- so a reader who did NOT sign up knows at a
    glance that someone used their address, and the security line tells them
    exactly what to do about it. Someone who DID sign up just reads it as a
    confirmation.
    """
    date_part, time_part = _split_date_time(created_at)
    subject = f"New account created on {_BRAND}"
    text = (
        f"Hello {name},\n\n"
        f"A NEW account has been created on {_BRAND} with this email address.\n\n"
        f"Email: {email}\n"
        f"Date: {date_part}\n"
        f"Time: {time_part}\n\n"
        "You can now sign in with the password you chose during registration.\n\n"
        "If this was YOU, no action is needed -- this is just a confirmation.\n"
        "If you did NOT create this account, change your password immediately "
        "from the sign-in page (Forgot password), or contact support.\n\n"
        "This tool is a screening aid and is not a substitute for laboratory "
        "testing.\n\n"
        f"-- {_BRAND}"
    )
    html = _wrap_html(
        "New account created",
        (
            f"Hello {name}, a new account has been created on {_BRAND} with "
            "this email address. You can now sign in with the password you "
            "chose. If you did not create this account, change your password "
            "immediately."
        ),
        [
            ("Email", email),
            ("Date", date_part),
            ("Time", time_part),
            ("Sign-in", "Use the password you chose"),
        ],
        "AquaGuard AI is a screening tool and is not a substitute for laboratory testing.",
    )
    return subject, text, html


def first_signin_notice(name: str, email: str, when: str) -> tuple[str, str, str]:
    """Sent to a NEW USER the first time they sign in.

    Different from `signin_notice` in wording only -- the subject says plainly
    that this is their first sign-in, so the very first mail a new account
    owner receives after registering reads as a welcome-confirmation rather
    than a security warning.
    """
    date_part, time_part = _split_date_time(when)
    subject = f"Welcome to {_BRAND} -- your first sign-in"
    text = (
        f"Hello {name},\n\n"
        f"Your FIRST sign-in to your {_BRAND} account was recorded.\n\n"
        f"Email: {email}\n"
        f"Date: {date_part}\n"
        f"Time: {time_part}\n\n"
        "Your account is now active. If this was you, no action is needed. "
        "If it was not, change your password immediately.\n\n"
        f"-- {_BRAND}"
    )
    html = _wrap_html(
        "First sign-in recorded",
        f"Hello {name}, welcome to {_BRAND} -- your first sign-in was just recorded.",
        [
            ("Email", email),
            ("Date", date_part),
            ("Time", time_part),
        ],
        "If this was not you, change your password immediately.",
    )
    return subject, text, html


def signin_notice(name: str, email: str, when: str, where: str) -> tuple[str, str, str]:
    """Sent on a successful sign-in, so the account owner sees unexpected access."""
    subject = f"New sign-in to your {_BRAND} account"
    date_part, time_part = _split_date_time(when)
    text = (
        f"Hello {name},\n\n"
        f"A sign-in to your {_BRAND} account was recorded.\n\n"
        f"Email: {email}\n"
        f"Date: {date_part}\n"
        f"Time: {time_part}\n"
        f"Source: {where}\n\n"
        "If this was you, no action is needed. If it was not, change your password "
        "immediately.\n\n"
        f"-- {_BRAND}"
    )
    html = _wrap_html(
        "Sign-in recorded",
        f"Hello {name}, a sign-in to your account was just recorded.",
        [
            ("Email", email),
            ("Date", date_part),
            ("Time", time_part),
            ("Source", where),
        ],
        "If this was not you, change your password immediately.",
    )
    return subject, text, html


# Full month names for the emailed DATE line, so a notice reads
# "08 October 2026" rather than the abbreviated "08 Oct 2026" `%b` produces.
# Indexed by month number; index 0 is unused so `_FULL_MONTHS[1]` is January.
_FULL_MONTHS = (
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def _split_date_time(when: str) -> tuple[str, str]:
    """Split a timestamp into human-readable DATE and TIME parts, in IST.

    The tracking table stores ISO strings ("2026-01-15T10:30:45+00:00"). Those
    are fine for sorting but unreadable in an email, and the requirement is the
    date and the time on SEPARATE lines -- shown in the user's local time (IST)
    rather than as the UTC instant the database stores, so the mail says the
    time it actually is when it arrives. Falls back to the raw string on both
    lines if it cannot be parsed, so a notice is never sent with blanks.
    """
    raw = (when or "").strip()
    try:
        moment = datetime.fromisoformat(raw)
        if moment.tzinfo is None:
            # Naive timestamps in the tracking table are stored in UTC.
            moment = moment.replace(tzinfo=timezone.utc)
        moment = moment.astimezone(ZoneInfo("Asia/Kolkata"))
        # THE REQUESTED WORDING: a full month name ("08 October 2026") and a
        # minute-precision clock ("12:25 PM"). Seconds are omitted deliberately —
        # an emailed notice is read by a person matching it against when they did
        # something, and the second is noise that only widens the line.
        return (
            f"{moment.day:02d} {_FULL_MONTHS[moment.month]} {moment.year}",
            moment.strftime("%I:%M %p").lstrip("0"),
        )
    except ValueError:
        return raw, raw


def admin_signin_notice(
    name: str, email: str, when: str, where: str, location: dict | None = None
) -> tuple[str, str, str]:
    """Sent to the ADMIN when any user signs in.

    DIFFERENT FROM `signin_notice`, AND SENT TO A DIFFERENT PERSON. That one goes
    to the account owner so they can spot unexpected access to their OWN account;
    this one goes to the administrator (ADMIN_NOTIFY_EMAIL) so they can see who is
    using the system and when. The requirement is the account's NAME with the
    DATE AND TIME, so those lead the message and are stated in full rather than
    abbreviated.

    The name is shown even when the sign-in has no name on record (a bare email),
    because the admin cares which account, not which display name — a missing name
    degrades to the email rather than to a blank row.

    LOCATION IS THE APPROXIMATE PLACE (name, city, state, country, pincode), never
    the raw coordinates. `where` remains the device + IP line, which is separate
    from the place and is kept as it was.
    """
    shown_name = (name or "").strip() or email
    date_part, time_part = _split_date_time(when)
    place_rows = _location_rows(location)
    subject = f"{_BRAND}: user signed in - {shown_name}"
    text_lines = [
        f"A user signed in to {_BRAND}.",
        "",
        f"Name: {shown_name}",
        f"Email: {email}",
    ]
    text_lines += [f"{label}: {value}" if value else label for label, value in place_rows]
    text_lines += [
        f"Source: {where}",
        f"Date: {date_part}",
        f"Time: {time_part}",
        "",
        "This notice is sent to the administrator on every sign-in.",
        "",
        f"-- {_BRAND}",
    ]
    text = "\n".join(text_lines)
    html = _wrap_html(
        "User signed in",
        f"{shown_name} signed in to {_BRAND}.",
        [
            ("Name", shown_name),
            ("Email", email),
            *place_rows,
            ("Source", where),
            ("Date", date_part),
            ("Time", time_part),
        ],
        "Sent to the administrator on every successful sign-in.",
    )
    return subject, text, html


def email_action_capabilities() -> dict[str, Any]:
    """What THIS mail transport can actually do about an in-message button.

    READ THIS BEFORE BELIEVING ANYTHING IN AN EMAIL BUTTON.

    A link in an email is a link. Clicking it performs a GET, which means the
    destination can decide the outcome on load alone. That is precisely why the
    links in the approval mail point at a CONFIRMATION PAGE that changes nothing
    until a real POST is sent - see `admin_login_approval_message`.

    Some providers go further and offer a genuinely interactive action: SendGrid
    and Postmark support an AMP for Email part carrying `Amp-Form` / `action-id`
    buttons, which the CLIENT executes itself. That is a different mechanism from
    a link, and it is only real for clients that render AMP. Most desktop and
    mobile clients do not.

    This function REPORTS the situation honestly so the mail and the login page
    can both describe what will happen:

        `interactive_actions_supported`
            True only when a provider known to support authenticated in-message
            actions is configured. Currently False for the plain SMTP transport
            this application uses, which has no such facility.

        `mechanism`
            A short sentence naming what the buttons actually do, so the copy can
            say "open a confirmation page" rather than the untrue "approve from
            this mail".

        `limitation`
            The sentence that belongs in the mail and on the waiting screen,
            stating plainly that an ordinary mail client cannot execute an action
            inside the mail itself.

    RETURNING False HERE IS THE HONEST ANSWER, not a missing feature. Pretending
    a plain link can "approve" would describe a mechanism the platform does not
    have, and the failure would surface as a security control that quietly does
    nothing.
    """
    provider = (current_app.config.get("MAIL_PROVIDER") or "").strip().lower()

    # Providers with a real authenticated in-message action facility. Listed so
    # an operator can see exactly what would change the answer, and so adding one
    # later is a deliberate act rather than a claim.
    interactive_providers = {"sendgrid", "postmark", "mailgun-interactive"}

    supported = provider in interactive_providers

    if supported:  # pragma: no cover - no such provider is configured today
        return {
            "provider": provider,
            "interactive_actions_supported": True,
            "mechanism": (
                "The buttons in this mail are an email-client action (AMP for "
                "Email) handled by the mail provider, not a link."
            ),
            "limitation": (
                "Only mail clients that render interactive email actions can run "
                "these buttons; most do not. In every other client the buttons are "
                "ordinary links that open a confirmation page on the AquaGuard AI "
                "site, where you approve or deny. A provider or client may also "
                "open a link automatically to scan or preview it - that is why the "
                "link alone decides nothing."
            ),
        }

    return {
        "provider": provider or "smtp",
        "interactive_actions_supported": False,
        "mechanism": (
            "The buttons are links to a confirmation page on the AquaGuard AI "
            "site that shows exactly what you are approving. Nothing is approved "
            "by the mail alone - you must press a button on that page."
        ),
        "limitation": (
            "An ordinary email is links, not an application, so no mail client can "
            "run an action from inside the message itself. Some clients and "
            "providers also open or preview a link automatically to scan it, and "
            "that cannot be prevented universally. Both cases are why the links "
            "here open a confirmation page and change nothing until you press its "
            "button: a link that decided on being opened would be decided by "
            "automatic scanners, which is the opposite of an approval step."
        ),
    }


def admin_login_approval_message(
    request_id: str,
    admin_username: str,
    review_url: str,
    minutes: int,
    *,
    approve_url: str | None = None,
    deny_url: str | None = None,
    requested_at: str | None = None,
    device_label: str | None = None,
    ip_address: str | None = None,
) -> tuple[str, str, str]:
    """The approval mail for a console login attempt.

    YES AND NO ARE LINKS TO A CONFIRMATION PAGE, NOT ONE-CLICK DECISIONS.
    `approve_url` / `deny_url` open a small confirmation page on THIS
    application's own domain, pre-selecting the intended answer. That page shows
    the request's details and a single button; the decision is recorded only when
    the approver presses it (a real POST).

    WHY THE EXTRA STEP, WHICH IS THE WHOLE POINT. A link in an email is followed
    automatically by more things than the recipient: security scanners, link
    prefetchers and chat-client previews all GET a URL to inspect it. If the
    link itself decided, every one of those would cast the vote — an approval
    nobody made. Putting the decision behind a deliberate press means a scanner
    that fetches these URLs changes nothing. See `email_action_capabilities` for
    what each mail provider can and cannot do here, stated honestly.

    NO EXTERNAL REDIRECT. Every URL in this message is built from this
    application's own base URL, so the approver never leaves for a third-party or
    unrelated page; the confirmation page is served by the same origin that sent
    the mail.

    APPROVING HERE STILL DOES NOT OPEN THE CONSOLE. The confirmation step only
    marks the request approved; the console is opened by `consume`, which needs
    the browser challenge that never left the sign-in tab. The token is
    single-use, expires in `minutes`, and authorises exactly one decision on
    exactly one request.

    `review_url` is the same confirmation page reached without a pre-selected
    answer, for an approver who wants to read the details before choosing.

    NOTHING SENSITIVE IS IN THE MAIL. No password, no console credential, and no
    permanent secret. The token in a link is single-use and short-lived, and
    nothing acts on it until a button is pressed on the confirmation page.
    """
    # DATE AND TIME ON SEPARATE ROWS, in the requested human wording:
    #   Date: 08 October 2026
    #   Time: 12:25 PM
    # `_split_date_time` renders the stored UTC instant in IST with a full month
    # name and a minute-precision clock, exactly like the other admin notices, so
    # every mail this console sends shows the same readable date and time.
    if (requested_at or '').strip():
        request_date, request_time = _split_date_time(requested_at)
    else:
        request_date = 'just now'
        request_time = ''

    caps = email_action_capabilities()

    details = [
        ("Console username", admin_username),
        ("Date", request_date),
        ("Time", request_time),
        ("Browser", device_label),
        ("IP address", ip_address),
        ("Expires in", f"{minutes} minutes, then this request is refused"),
    ]
    detail_lines = "\n".join(f"  {label}: {value}" for label, value in details if value)

    subject = f"{_BRAND}: admin console login request — approve or deny"
    # The plain-text part carries the two decision links directly, so a client
    # that renders no HTML can still answer in one click.
    decision_lines = ""
    if approve_url and deny_url:
        decision_lines = (
            "To ALLOW this login:\n"
            f"  YES - Approve Access: {approve_url}\n\n"
            "To DENY this login:\n"
            f"  NO - Deny Access: {deny_url}\n\n"
            "Each link opens a confirmation page on the AquaGuard AI site showing\n"
            "this request. Nothing is decided until you press the button there, so\n"
            "simply opening the link cannot approve or deny anything.\n\n"
        )
    text = (
        f"A login to the {_BRAND} admin console is waiting for your approval.\n\n"
        f"{detail_lines}\n\n"
        f"{decision_lines}"
        "Prefer to see the details first? This page changes nothing on its own:\n"
        f"{review_url}\n\n"
        f"{caps['mechanism']}\n\n"
        f"{caps['limitation']}\n\n"
        f"The request is refused automatically after {minutes} minutes, and once you\n"
        "answer it the link stops working — a decision cannot be made twice.\n\n"
        "If you did not make this login attempt, deny it and change the console\n"
        "password immediately.\n\n"
        f"-- {_BRAND}"
    )

    button_style = (
        "display:inline-block;padding:12px 28px;margin:4px;border-radius:8px;"
        "font-size:15px;font-weight:bold;text-decoration:none;"
    )
    detail_rows = "".join(
        f'<tr><td style="padding:3px 12px 3px 0;color:#64748b;font-size:13px;">{label}</td>'
        f'<td style="padding:3px 0;color:#0f172a;font-size:13px;font-weight:bold;">{value}</td></tr>'
        for label, value in details
        if value
    )

    html = f"""
<div style="font-family:Arial,sans-serif;max-width:560px;margin:auto;">
  <h2 style="color:#0f172a;">Admin console login request</h2>
  <p style="color:#334155;font-size:14px;line-height:1.6;">
    A login to the <strong>{_BRAND}</strong> admin console is waiting for your
    approval. It stays locked until you answer.
  </p>

  <table role="presentation" style="margin:18px 0;border-collapse:collapse;">
    {detail_rows}
  </table>

  <p style="text-align:center;margin:24px 0;">
    <a href="{approve_url or review_url}" style="{button_style}background:#0ea5e9;color:#ffffff;"
       >Yes &mdash; Approve Access</a>
    <a href="{deny_url or review_url}" style="{button_style}background:#ef4444;color:#ffffff;"
       >No &mdash; Deny Access</a>
  </p>

  <p style="color:#334155;font-size:14px;line-height:1.6;">
    Each button opens a confirmation page on the {_BRAND} site that shows this
    request. Press <strong>“Yes — Approve Access”</strong> there to let the login
    through, or <strong>“No — Deny Access”</strong> to keep the console locked.
    Nothing is decided by opening the link — only by pressing the button on that
    page, so an automatic link scanner cannot answer for you.
  </p>

  <p style="color:#64748b;font-size:12px;line-height:1.6;">
    Want the request's details before deciding?
    <a href="{review_url}" style="color:#0ea5e9;">Review this request</a>.
  </p>

  <p style="color:#64748b;font-size:12px;line-height:1.6;border-top:1px solid #e2e8f0;padding-top:12px;">
    {caps['mechanism']}<br><br>
    {caps['limitation']}<br><br>
    If this was not you, deny the request and change the console password.
  </p>
</div>"""
    return subject, text, html


def admin_unlock_alert_message(confirm_url: str, deny_url: str, minutes: int) -> tuple[str, str, str]:
    """DEPRECATED — superseded by `admin_login_approval_message`.

    Retained only so an existing import does not break. It is no longer called by
    any route, and it should not be: the `GET` links it builds would change access
    state on load, which automatic link scanners would trigger. The replacement
    puts no authority in a GET at all.
    """
    subject = f"{_BRAND}: admin console access attempt — approve or deny"
    text = (
        "A login to the AquaGuard AI admin console is waiting for your approval.\n\n"
        f"Open the approval page:\n{confirm_url}\n\n"
        "On that page press “Yes — Approve” to allow it or “No — Deny” to refuse it.\n"
        f"The request is refused after {minutes} minutes if unanswered.\n\n"
        f"-- {_BRAND}"
    )
    button_style = (
        "display:inline-block;padding:12px 28px;margin:4px;border-radius:8px;"
        "font-size:15px;font-weight:bold;text-decoration:none;"
    )
    html = f"""
<div style="font-family:Arial,sans-serif;max-width:560px;margin:auto;">
  <h2 style="color:#0f172a;">Admin console access attempt</h2>
  <p style="color:#334155;font-size:14px;line-height:1.6;">
    A login to the <strong>{_BRAND}</strong> admin console is waiting for your
    approval.
  </p>
  <p style="text-align:center;margin:24px 0;">
    <a href="{confirm_url}" style="{button_style}background:#0ea5e9;color:#ffffff;"
       >Review this request</a>
  </p>
  <p style="color:#64748b;font-size:12px;">
    The request expires in {minutes} minutes. If this was not you, deny it and
    change the console password.
  </p>
</div>"""
    return subject, text, html




def admin_reset_code_message(code: str, minutes: int) -> tuple[str, str, str]:
    """The 6-digit code for resetting the admin console password.

    The code is the message. Everything else is context, so the first thing the
    reader sees is the number they have to type.
    """
    subject = f"{_BRAND}: your admin reset code"
    text = (
        "A password reset was requested for the AquaGuard AI admin console.\n\n"
        f"Your code: {code}\n\n"
        f"Enter it in the console to set a new password. The code expires in "
        f"{minutes} minutes and can be used once.\n\n"
        "If you did not request this, ignore this message -- nothing has changed "
        "and the code will expire on its own.\n\n"
        f"-- {_BRAND}"
    )
    html = _wrap_html(
        "Admin password reset",
        "A password reset was requested for the admin console. Enter this code to "
        "set a new password.",
        [("Reset code", code), ("Expires in", f"{minutes} minutes")],
        "If you did not request this, ignore this message -- nothing has changed.",
    )
    return subject, text, html

def admin_password_changed_message(when: str, changed_by: str) -> tuple[str, str, str]:
    """Confirms the admin console password was rotated.

    Like every other notice here, the timestamp is split into DATE and TIME
    lines — one line each, rather than a single combined string — so this mail
    reads the same as the sign-in and registration notices.
    """
    date_part, time_part = _split_date_time(when)
    subject = f"{_BRAND}: admin console password changed"
    text = (
        f"The admin console password for {_BRAND} was changed.\n\n"
        f"Date: {date_part}\n"
        f"Time: {time_part}\n"
        f"Changed by: {changed_by}\n\n"
        "If you did not make this change, the admin console has been accessed by "
        "someone else and the credential should be rotated again immediately.\n\n"
        f"-- {_BRAND}"
    )
    html = _wrap_html(
        "Admin password changed",
        "The admin console password was changed.",
        [("Date", date_part), ("Time", time_part), ("Changed by", changed_by)],
        "If you did not make this change, rotate the credential again immediately.",
    )
    return subject, text, html


def password_reset_code_message(name: str, code: str, minutes: int) -> tuple[str, str, str]:
    """The 6-digit code for resetting an account password from the sign-in page.

    The code is the message. Everything else is context, so the first thing the
    reader sees is the number they have to type.
    """
    subject = f"{_BRAND}: your password reset code"
    text = (
        f"Hello {name},\n\n"
        "A password reset was requested for your AquaGuard AI account.\n\n"
        f"Your code: {code}\n\n"
        f"Enter it on the reset page to set a new password. The code expires in "
        f"{minutes} minutes and can be used once.\n\n"
        "If you did not request this, ignore this message -- nothing has changed "
        "and the code will expire on its own.\n\n"
        f"-- {_BRAND}"
    )
    html = _wrap_html(
        "Password reset",
        f"Hello {name}, a password reset was requested for your account. Enter "
        "this code to set a new password.",
        [("Reset code", code), ("Expires in", f"{minutes} minutes")],
        "If you did not request this, ignore this message -- nothing has changed.",
    )
    return subject, text, html

def password_changed_message(name: str, when: str) -> tuple[str, str, str]:
    """Confirms an account password was changed."""
    subject = f"{_BRAND}: your password was changed"
    text = (
        f"Hello {name},\n\n"
        f"Your AquaGuard AI account password was changed.\n\n"
        f"Time: {when}\n\n"
        "If you did not make this change, reset your password again immediately "
        "and check your recent sign-in activity.\n\n"
        f"-- {_BRAND}"
    )
    html = _wrap_html(
        "Password changed",
        f"Hello {name}, your account password was changed.",
        [("Time", when)],
        "If you did not make this change, reset your password again immediately.",
    )
    return subject, text, html

def login_details_export_message(count: int, generated_at: str) -> tuple[str, str, str]:
    """Sent when an admin exports the login-details dataset."""
    subject = f"{_BRAND}: login details exported"
    text = (
        "The login-details dataset was exported from the admin console.\n\n"
        f"Records: {count}\n"
        f"Generated: {generated_at}\n\n"
        "If you did not request this export, review the admin console access log.\n\n"
        f"-- {_BRAND}"
    )
    html = _wrap_html(
        "Login details exported",
        "The login-details dataset was exported from the admin console.",
        [("Records", str(count)), ("Generated", generated_at)],
        "If you did not request this export, review the admin console access log.",
    )
    return subject, text, html

def report_mail_message(
    recipient: str, option: str, scope: str, attachment_name: str, size: int
) -> tuple[str, str, str]:
    """The message for the Reports-to-Mail feature, carrying the attachment.

    Parallel to the other builders: a plain subject, a text body, and the shared
    HTML shell. The body states exactly WHAT is attached (option, scope, file
    name and size) so a reader can see what arrived without opening it.
    """
    option_labels = {
        "REPORT_PDF": "Your selected report as PDF",
        "REPORT_CSV": "Your selected report as CSV",
        "ALL_PDF": "All your reports as one PDF",
        "ALL_CSV": "All your reports as one CSV",
    }
    label = option_labels.get(option, option)
    readable_size = f"{size / 1024:.1f} KB" if size >= 1024 else f"{size} bytes"

    # DATE AND TIME INSIDE THE BRAND BOX, per the layout requirement: the report
    # email shows the date and the time as separate labeled rows within the
    # AquaGuard details table, so a reader knows when the report was generated
    # without opening the attachment.
    now = datetime.now(timezone.utc)
    generated_date = now.strftime("%Y-%m-%d")
    generated_time = now.strftime("%H:%M:%S UTC")

    subject = f"{_BRAND}: your water quality report"
    text = (
        "Hello,\n\n"
        f"Your requested water quality report from {_BRAND} is attached.\n\n"
        f"Report: {label}\n"
        f"Date: {generated_date}\n"
        f"Time: {generated_time}\n"
        f"Scope: {scope}\n"
        f"Attachment: {attachment_name} ({readable_size})\n\n"
        "This tool is a screening aid and is not a substitute for laboratory "
        "testing.\n\n"
        f"-- {_BRAND}"
    )
    html = _wrap_html(
        "Your water quality report",
        f"Your requested water quality report from {_BRAND} is attached.",
        [
            ("Report", label),
            ("Date", generated_date),
            ("Time", generated_time),
            ("Scope", scope),
            ("Attachment", attachment_name),
            ("Size", readable_size),
        ],
        "AquaGuard AI is a screening tool and is not a substitute for laboratory testing.",
    )
    return subject, text, html
