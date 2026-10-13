"""Admin console API.

MOUNTED AT `/api/admin`, and NOT under `/api/v1`. The console is an internal
surface, not part of the public API contract: versioning it would imply it is
covered by the same stability promise as the user-facing endpoints, which it is
not.

AUTHORISATION IS THE CONSOLE CREDENTIAL, and it is deliberately separate from
everything else in the application:

  1. `POST /api/admin/session` -- the console's OWN username and password. This
     is the only way in: the rest of the application has no user login at all, so
     there is no account session to lean on and no JWT that a normal visitor
     could ever hold.
  2. `@console_unlocked` -- a short-lived console session, opened by confirming
     the mail the password step sends. This is the second factor for the
     destructive operations.

A route that changes state requires BOTH; read-only routes require only that the
console is unlocked. The console password alone is not enough to act, and being
unlocked is not enough without having proved the password first. Neither half on
its own is sufficient to delete an account.

WHAT IS NOT HERE. No route returns a password, a password hash, or a mail
credential. The console can see THAT a thing is
configured, never the secret itself.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone

from flask import Blueprint, Response, current_app, request

from app.extensions import db
from app.utils.errors import AquaGuardError, ForbiddenError
from app.utils.pagination import parse_pagination
from app.utils.responses import error_response, success_response

logger = logging.getLogger(__name__)

admin_bp = Blueprint("admin", __name__)


# ------------------
# Authorisation helpers
# ------------------
def _require_unlocked() -> None:
    """Require a live console unlock for ANY console endpoint.

    The unlock IS the console's authentication. It is opened only by
    `POST /session`, which checks the console's own username and password, and
    only after the mailed confirmation is spent. There is deliberately no
    fallback that lets a request through without it, and no user account behind
    it: normal users have no login at all.
    """
    from app.services.console_session import is_unlocked

    if not is_unlocked():
        raise ForbiddenError(
            "The admin console is locked. Sign in with the console password."
        )


def _console_identity() -> dict:
    """The console's login name and recovery email, for audit messages.

    Reads the same single settings row every other console route does, so an
    audit line names the console itself rather than an account.
    """
    from app.services.admin_service import admin_identity

    return admin_identity()


def _failure(exc: AquaGuardError):
    return error_response(exc.message, exc.status_code, exc.errors)


# ------------------
# Session
# ------------------
@admin_bp.post("/session")
def open_session():
    """Sign in to the console with the console's own username and password.

    THE ONLY WAY INTO THE ADMIN AREA. Normal users have no login at all, so this
    credential is the whole of the console's authentication: there is no account
    session behind it to escalate from and no token a visitor could already
    hold.

    PROMPT 8, AND THE ORDER HERE IS THE REQUIREMENT. The credential is verified
    FIRST, and the approval mail is only built and sent once `verify_admin_*` has
    passed. The previous code called `issue_unlock_confirmation()` before the
    result was acted on, so a wrong password could still produce a mail - which
    turns the admin's inbox into an oracle that confirms a correct username.

    On success this creates an approval REQUEST (one row, independent of any
    other attempt) and mails it. Nothing is unlocked here: the console opens only
    when that request is approved AND the original browser spends it.

    Body: ``{password, username?, challenge}``. `challenge` is the nonce the login
    page received when it loaded; it binds the approval to this browser and is
    never accepted from anywhere else.
    """
    try:
        from app.services.admin_service import (
            issue_login_approval_request,
            verify_admin_credentials,
            verify_admin_password,
        )

        payload = request.get_json(silent=True) or {}
        password = payload.get("password") or ""
        username = payload.get("username")
        challenge = str(payload.get("challenge") or "").strip()

        ok = (
            verify_admin_credentials(str(username or ""), password)
            if username is not None
            else verify_admin_password(password)
        )
        if not ok:
            # NO MAIL, NO ROW, NO TIMESTAMP. The attempt is logged with the
            # console identity but never the candidate, and the wording is the
            # same ambiguous sentence whatever was wrong.
            logger.warning("Failed admin console login attempt")
            return error_response("That username or password is not correct", 401)

        if not challenge:
            # Without a challenge the approval could not be bound to a browser,
            # so accepting the login would mean accepting an unbound approval.
            return error_response(
                "This sign-in is missing its browser challenge. Reload the login page and try again.",
                400,
            )

        result = issue_login_approval_request(challenge)
        logger.info("Admin console login approval mailed to %s", result["sent_to"])
        return success_response(
            data=result,
            message=(
                f"An approval request was sent to {result['sent_to']}. Approve it "
                "there to finish signing in."
            ),
        )
    except AquaGuardError as exc:
        return _failure(exc)


@admin_bp.route("/session/confirm", methods=["GET", "POST"])
def confirm_session():
    """REMOVED AS AN ACCESS-CHANGING ENDPOINT — it now changes nothing at all.

    PROMPT 8. This used to accept `GET /session/confirm?token=…` and OPEN THE
    CONSOLE on load. That is the single most important thing this prompt fixed:
    a GET acts the moment it is loaded, so any email security scanner, chat
    client's link preview or browser prefetch that followed that URL spent the
    single-use token and made the decision on the admin's behalf. A control that
    fires when a bot touches it is not a control.

    The endpoint is kept, returning 410, for one reason only: an old mail sitting
    in an inbox should produce a clear explanation rather than a confusing 404
    or, worse, a silent success. It grants nothing, and it never did not grant -
    it now simply cannot.
    """
    return Response(
        """<!doctype html><html><head><meta charset="utf-8"><title>AquaGuard admin</title></head>
<body style="font-family:Arial,sans-serif;background:#0f172a;color:#e2e8f0;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0;">
  <div style="max-width:520px;text-align:center;">
    <p style="font-size:18px;color:#fbbf24;">This approval link is no longer used.</p>
    <p style="font-size:14px;color:#94a3b8;margin-top:12px;line-height:1.6;">
      For safety, links in an email can no longer grant access by being opened
      &mdash; automatic link scanners would otherwise be able to approve a
      login. Open the admin console in your browser and sign in again; you will
      get a fresh approval mail with a confirmation page.
    </p>
  </div>
</body></html>""",
        mimetype="text/html",
        status=410,
    )


# ---------------------------------------------------------------------------
# PROMPT 8: the two-step login approval flow
# ---------------------------------------------------------------------------
#
# WHAT IS DELIBERATELY ABSENT, because each of these would be a defect:
#
#   * NO `GET /session/approve?token=…` that unlocks. A GET that changes access
#     state is fired by link scanners, so the decision has to require a POST.
#   * NO token in a URL that any page load alone acts on. The mail's link opens a
#     REVIEW page; its two buttons POST.
#   * NO approval flag the frontend can set. Every decision is the database's
#     `admin_login_approvals.status`, and the console only opens when
#     `spend_on_unlock` re-checks that status, the token AND the browser challenge.


@admin_bp.get("/session/challenge")
def approval_challenge():
    """Mint the browser challenge this page load's approvals will be bound to.

    PUBLIC, like `GET /session`, and for the same reason: the login page calls it
    before anybody has signed in, because the challenge has to exist BEFORE a
    request can be made rather than being invented afterwards.

    It grants nothing. The value is a 256-bit nonce the page keeps in
    `sessionStorage`; the server stores only its SHA-256, attached to whichever
    request the page subsequently asks for. Because the plain value never travels
    in a URL, it cannot leak the way a cookie or a query parameter would.
    """
    from app.services import login_approval_service as approvals

    return success_response(
        data={"challenge": approvals.new_challenge()},
        message="Browser challenge issued",
    )


@admin_bp.post("/session/approval")
def request_approval():
    """Poll one request's outcome. Requires that request's browser challenge.

    This is how the LOGIN PAGE - which stays open throughout - learns what was
    decided in the mail. It returns a status, never a token, and it is scoped to
    a single request by `request_id`.

    Requiring the challenge is what stops this being a way to watch somebody
    else's login attempt: without it, anyone could poll every request id and
    learn the admin's authentication state, and when the console was unlocked.
    """
    try:
        payload = request.get_json(silent=True) or {}
        request_id = str(payload.get("request_id") or "")
        challenge = str(payload.get("challenge") or "")

        if not request_id or not challenge:
            return error_response("A request id and challenge are required", 400)

        from app.services import login_approval_service as approvals

        return success_response(data=approvals.poll(request_id, challenge))
    except AquaGuardError as exc:
        return _failure(exc)


@admin_bp.get("/session/approval/<request_id>/review")
def review_approval(request_id: str):
    """The APPROVAL PAGE the mail's link opens. IT CHANGES NOTHING.

    This is the interstitial, and its entire job is to be safe to open. A mail
    scanner, a chat client's link preview or a browser prefetch that fetches this
    URL gets a page describing the request and nothing else - no decision is
    recorded, no state changes, and the console stays locked.

    Only the POST below, made by the page's own button, records anything.

    IT IS DELIBERATELY A SMALL SELF-CONTAINED HTML DOCUMENT rather than the React
    application: the approver is answering from their mail, possibly on another
    device, and it must not require the SPA, a login, or an API host to be
    reachable. It also closes on its own, so the approver's browser is left where
    it was - the console is opened by the ORIGINAL login page, not from here.

    THE TOKEN IN THE URL IS SAFE BECAUSE NOTHING ACTS ON LOADING THIS PAGE. It is
    carried in the mail's link and echoed into the button, and the ONLY thing that
    consumes it is the POST below. That is why the token can be stored hashed and
    never in the clear: the approver already holds it, so the server never needs a
    recoverable copy. A scanner that fetches this URL learns nothing it can act on.
    """
    from app.services import login_approval_service as approvals
    from app.models.admin_login_approval import AdminLoginApproval

    row = db.session.query(AdminLoginApproval).filter_by(request_id=request_id).first()
    if row is None:
        return _approval_page(
            status="missing",
            title="Nothing to approve",
            message="This approval request was not found. It may have expired, or the link may be incomplete.",
            can_decide=False,
        )

    live = row.is_pending()
    # Timestamps come back from the driver NAIVE (UTC by construction), so the
    # comparison has to be naive too — aware minus naive is a TypeError.
    seconds = max(0, int((row.expires_at - datetime.now(timezone.utc).replace(tzinfo=None)).total_seconds()))

    if not live:
        message = (
            "This request has already been answered."
            if row.status in ("approved", "denied", "consumed")
            else "This request expired. Sign in again from the admin console to get a new one."
        )
        return _approval_page(
            status=row.status,
            title="Already decided",
            message=message,
            can_decide=False,
            admin_username=row.admin_username,
            requested_at=row.requested_at,
            device_label=row.device_label,
            ip_address=row.ip_address,
        )

    return _approval_page(
        status="pending",
        title="Approve this admin console login?",
        message="",
        can_decide=True,
        admin_username=row.admin_username,
        requested_at=row.requested_at,
        device_label=row.device_label,
        ip_address=row.ip_address,
        seconds_remaining=seconds,
        token=str(request.args.get("token") or ""),
        # The mail's Yes / No links arrive here with the intended answer in
        # `?action=`. It only HIGHLIGHTS that button — the page still decides
        # nothing until the button is pressed. That is what keeps a link scanner,
        # which GETs this URL without pressing anything, from casting a vote.
        intended_action=str(request.args.get("action") or "").strip().lower(),
    )


@admin_bp.post("/session/approval/<request_id>/decide")
def decide_approval(request_id: str):
    """Record YES or NO. A POST, so nothing that merely loads a URL can call it.

    Body: ``{action: "approve"|"deny", token: str}`` as JSON, OR the same two
    fields as a normal HTML form post. Both are accepted because the confirmation
    page submits a real form (so the decision works with JavaScript disabled),
    while the page's script posts JSON for the smoother inline result. There is no
    JavaScript IN THE EMAIL — the mail only ever contains links.

    The token is the mail's authority: single-use, short-lived, stored hashed and
    compared in constant time. On approve the row is marked approved - it is NOT
    yet usable, because the console only opens when the original login page
    presents the token AND its own challenge to `spend_on_unlock`.

    The reply is MINIMAL: for a form post, a tiny self-contained confirmation page
    on this same origin (no redirect anywhere); for the JSON path, the standard
    envelope. Either way the decision is enforced entirely on the server.
    """
    try:
        # A JSON body first (the script path); fall back to form fields (the
        # no-JavaScript path). `request.form` is empty for a JSON request and vice
        # versa, so the two never collide.
        payload = request.get_json(silent=True) or {}
        action = str(payload.get("action") or request.form.get("action") or "").strip().lower()
        token = str(payload.get("token") or request.form.get("token") or "")
        # A browser form post wants a page back, not JSON.
        wants_html = request.form and not request.is_json

        if not action or not token:
            if wants_html:
                return _confirm_page(
                    False,
                    "An action and the approval token are required.",
                    autoclose=False,
                )
            return error_response("An action and the mail's approval token are required", 400)

        from app.services import login_approval_service as approvals

        try:
            result = approvals.decide(
                request_id,
                action,
                token,
                client_ip=request.remote_addr,
            )
        except AquaGuardError as exc:
            if wants_html:
                return _confirm_page(
                    False, str(getattr(exc, "message", exc)), autoclose=False
                )
            raise

        approved = result["status"] == "approved"
        if wants_html:
            return _confirm_page(
                approved,
                "Access granted — return to the browser where you signed in; the console will open there."
                if approved
                else "Access denied — that login was not granted access.",
                autoclose=False,
            )
        if approved:
            return success_response(
                data=result,
                message="Approved. Return to the browser where you signed in — the console will open there.",
            )
        return success_response(
            data=result,
            message="Denied. That login will not be granted access.",
        )
    except AquaGuardError as exc:
        return _failure(exc)


@admin_bp.route("/session/approval/<request_id>/mail", methods=["GET", "POST"])
def decide_from_mail(request_id: str):
    """Back-compat entry point for an OLD approval mail. It DECIDES NOTHING ON GET.

    WHY THIS NO LONGER ACTS ON LOAD. This endpoint used to read `?action=…&token=…`
    and record the decision on a GET. That is the defect this refinement removes: a
    link is followed automatically by security scanners, link prefetchers and
    chat-client previews, so an approval (or a denial) could be cast by a machine
    that merely inspected the message. A security control that fires when a bot
    touches it is not a control.

    New mails no longer use this URL at all — their Yes/No links open the
    confirmation page (`/review`), whose button POSTs to `/decide`. This endpoint
    exists only so a message already sitting in an inbox behaves safely: a GET
    renders the same inert confirmation content and changes nothing, and only an
    explicit POST with the action and token records a decision.

    THERE IS NO EXTERNAL REDIRECT. The response is served by this application, on
    its own origin, and is a minimal self-contained confirmation.
    """
    from app.services import login_approval_service as approvals
    from app.models.admin_login_approval import AdminLoginApproval

    # A GET IS INERT. It explains the situation and changes no state, so a
    # scanner that follows this link decides nothing.
    if request.method == "GET":
        row = db.session.query(AdminLoginApproval).filter_by(request_id=request_id).first()
        if row is None:
            return _confirm_page(
                False,
                "This approval request was not found. It may have expired.",
            )
        if not row.is_pending():
            return _confirm_page(
                False,
                "This approval request has already been answered.",
            )
        return _confirm_page(
            False,
            "Open the approval mail and press the button on its confirmation page "
            "to approve or deny. Opening a link alone does not decide anything.",
        )

    # A POST is a deliberate decision, and is authorised exactly as `/decide` is.
    payload = request.get_json(silent=True) or {}
    action = str(payload.get("action") or "").strip().lower()
    token = str(payload.get("token") or "")

    if action not in ("approve", "deny") or not token:
        return error_response(
            "An action and the mail's approval token are required", 400
        )

    try:
        result = approvals.decide(
            request_id, action, token, client_ip=request.remote_addr
        )
    except AquaGuardError as exc:
        return error_response(str(getattr(exc, "message", exc)), 400)

    message = (
        "Approved — the console will open in the browser where you signed in."
        if result.get("status") == "approved"
        else "Denied — that login was not granted access."
    )
    return success_response(data={"decided": True, "action": action}, message=message)


@admin_bp.post("/session/approval/<request_id>/consume")
def consume_approval(request_id: str):
    """Spend an approved request and OPEN the console. The last gate.

    Body: ``{challenge}``.

    NO TOKEN IS REQUIRED HERE, and that is the correct design rather than a
    shortcut. The token's job is to prove THE MAIL authorised the decision, and it
    did that at `decide` time — the result is now the row's status. This gate
    answers a different question: is THIS browser the one that asked? The
    challenge answers that, and the challenge never left the browser that made the
    request.

    So the approver's mail needs nothing from this page and this page needs
    nothing from the approver's mail beyond the approval itself.

    Re-checked here, at the moment the console actually opens:

      * the row must be `approved` — a denial or an expiry can never be spent;
      * it must not already have been consumed — single use, enforced on the row;
      * the challenge must match — only the requesting browser can spend it, so an
        approved request cannot be handed to another browser.

    On any mismatch the console stays locked and nothing is consumed.
    """
    try:
        payload = request.get_json(silent=True) or {}
        challenge = str(payload.get("challenge") or "")

        if not challenge:
            return error_response("The browser challenge is required", 400)

        from app.services import console_session
        from app.services import login_approval_service as approvals

        if not approvals.spend_on_unlock(request_id, challenge):
            logger.warning("Refused console unlock: approval could not be spent")
            return error_response(
                "That approval is no longer valid. Sign in again.", 403
            )

        opened = console_session.unlock()
        logger.info("Admin console opened from an approved login request")
        return success_response(data=opened, message="Admin console unlocked")
    except AquaGuardError as exc:
        return _failure(exc)


def _approval_page(
    *,
    status: str,
    title: str,
    message: str,
    can_decide: bool,
    admin_username: str | None = None,
    requested_at: datetime | None = None,
    device_label: str | None = None,
    ip_address: str | None = None,
    seconds_remaining: int = 0,
    token: str = "",
    intended_action: str = "",
) -> Response:
    """The self-contained confirmation page the mail's link opens.

    SELF-CONTAINED ON PURPOSE, and inert on load. It posts to the same origin it
    was served from, so no third-party script, image or beacon is involved - a
    page that decides an authentication outcome must not load remote content,
    because a remote resource is a third party observing the decision. Nothing
    here redirects off-site.

    NOTHING IS DECIDED BY OPENING THIS PAGE. That is the property that makes the
    mail's links safe: a scanner, prefetcher or chat preview that GETs this URL
    records no decision, because the decision is a POST made by the approver's own
    button. `intended_action` (from the mail's `?action=`) only HIGHLIGHTS the
    button the approver already chose — it does not act on its own.

    WORKS WITH JAVASCRIPT DISABLED. The two buttons are a real HTML form that
    POSTs to the same origin, so the decision can be made without any script. The
    little bit of JavaScript only upgrades the experience (inline result, then
    close the tab); it is never the thing that submits the answer.

    It also closes itself when it can. The approver answered a question from
    their mail; they should not be left in a browser tab pointing at an
    authentication endpoint. The console is opened by the ORIGINAL login page.
    """
    stamp = requested_at.strftime("%Y-%m-%d %H:%M:%S UTC") if requested_at else "—"
    rows = "".join(
        f'<tr><td class="k">{label}</td><td class="v">{value}</td></tr>'
        for label, value in (
            ("Console username", admin_username),
            ("Requested at", stamp),
            ("Browser", device_label),
            ("IP address", ip_address),
        )
        if value
    )

    if can_decide:
        minutes = max(1, round(seconds_remaining / 60))
        # The button the approver picked in the mail is emphasised, so the
        # confirmation page reads as "you chose Approve — press to confirm".
        yes_class = "yes focus" if intended_action == "approve" else "yes"
        no_class = "no focus" if intended_action == "deny" else "no"
        body = f"""
  <p class="lead">Approving allows ONE sign-in to finish. Denying leaves the console
     locked. Either decision applies immediately and only once. Press the button
     below to record your answer &mdash; opening this page decides nothing.</p>
  <table>{rows}</table>
  <p class="note">This request is refused automatically after {minutes} minute(s).</p>
  <form class="actions" method="post" action="decide">
    <input type="hidden" name="token" value="{token}">
    <button class="{yes_class}" type="submit" name="action" value="approve"
            data-token="{token}"
            onclick="return decide('approve')">Yes &mdash; Approve Access</button>
    <button class="{no_class}" type="submit" name="action" value="deny"
            data-token="{token}"
            onclick="return decide('deny')">No &mdash; Deny Access</button>
  </form>
  <p class="result" id="result"></p>
"""
        # The progressive enhancement: intercept the submit, POST as JSON, show
        # the outcome inline and close the tab. `return false` in the onclick
        # stops the plain form POST so the two paths never both fire. With JS off
        # nothing intercepts, and the form POST does the same job server-side.
        script = """
function decide(action){
  var btn=document.getElementById('result');
  var buttons=document.querySelectorAll('.actions button');
  buttons.forEach(function(b){b.disabled=true;});
  btn.className='result';
  btn.textContent='Recording your decision…';
  var token=document.querySelector('[data-token]').dataset.token;
  fetch(location.pathname.replace(/\\/review$/,'') + 'decide', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({action:action, token:token})
  }).then(function(r){return r.json().then(function(b){return {ok:r.ok, body:b};});})
    .then(function(res){
      var text = (res.body && res.body.message) || 'Could not record that decision.';
      btn.textContent = text;
      btn.className = 'result ' + (res.ok ? 'ok' : 'bad');
      setTimeout(function(){ window.close(); }, 2500);
    })
    .catch(function(){
      btn.className='result bad';
      btn.textContent='Could not reach the server. Nothing was changed.';
      buttons.forEach(function(b){b.disabled=false;});
    });
  return false;
}
"""
    else:
        body = f"""
  <p class="lead">{message}</p>
  <table>{rows}</table>
"""
        script = "setTimeout(function(){ window.close(); }, 6000);"

    return Response(
        f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>AquaGuard &mdash; admin login approval</title>
<style>
 body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;
      background:#0f172a;color:#e2e8f0;display:flex;align-items:center;
      justify-content:center;min-height:100vh;margin:0;padding:24px;}}
 .card{{max-width:560px;width:100%;background:#1e293b;border:1px solid #334155;
        border-radius:14px;padding:28px;}}
 h1{{font-size:18px;margin:0 0 6px;color:#f8fafc;}}
 .lead{{font-size:14px;line-height:1.6;color:#cbd5e1;margin:0 0 18px;}}
 table{{width:100%;border-collapse:collapse;margin:0 0 6px;}}
 .k{{padding:5px 14px 5px 0;color:#94a3b8;font-size:13px;text-align:left;}}
 .v{{padding:5px 0;color:#f1f5f9;font-size:13px;font-weight:600;word-break:break-all;}}
 .note{{font-size:12px;color:#94a3b8;margin:10px 0 0;}}
 .actions{{display:flex;gap:12px;flex-wrap:wrap;margin:22px 0 0;}}
 button{{flex:1;min-width:150px;padding:13px 18px;border-radius:9px;border:0;
        font-size:15px;font-weight:700;cursor:pointer;}}
 button:disabled{{opacity:.55;cursor:not-allowed;}}
 .yes{{background:#0ea5e9;color:#04283a;}} .no{{background:#ef4444;color:#fff;}}
 /* The button the approver chose in the mail is ringed, so the page reads as a
    confirmation of THAT choice rather than a fresh question. It changes nothing
    by itself — the decision is still this press. */
 .focus{{outline:3px solid #facc15;outline-offset:2px;}}
 .result{{margin:18px 0 0;font-size:14px;min-height:20px;color:#cbd5e1;}}
 .result.ok{{color:#4ade80;}} .result.bad{{color:#f87171;}}
</style></head>
<body><div class="card">
  <h1>{title}</h1>
  {body}
</div>
<script>{script}</script>
</body></html>""",
        mimetype="text/html",
        # The approver's browser must not send this request's token onward to
        # anything, and must not be treated as a frameable attack surface.
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Frame-Options": "DENY",
            "X-Robots-Tag": "noindex, nofollow",
        },
    )


def _confirm_page(ok: bool, label: str | None = None, *, autoclose: bool = True) -> Response:
    """The minimal confirmation page an action returns -- served by THIS app.

    NO EXTERNAL REDIRECT. This is the whole of the response: one small
    self-contained document on the same origin that ran the action. The approver
    is never bounced to an unrelated website or a third-party page.

    `autoclose=True` (the default, and what the JSON/script path wants) closes the
    tab almost immediately, leaving the browser exactly as it was. A real decision
    POSTed as a plain form passes `autoclose=False` so the person can actually
    read the outcome before the tab goes away.

    `label` lets a caller state the outcome in its own words; the default pair is
    the original yes/no wording this page has always used.
    """
    if label is None:
        if ok:
            label, colour = "Access granted — returning to the web page", "#0ea5e9"
        else:
            label, colour = "Access denied — the console stays locked", "#ef4444"
    else:
        colour = "#0ea5e9" if ok else "#ef4444"
    script = (
        "setTimeout(function() { window.close(); }, 250);"
        if autoclose
        else ""
    )
    return Response(
        f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>AquaGuard admin</title></head>
<body style="font-family:Arial,sans-serif;background:#0f172a;color:#e2e8f0;
line-height:1.6;display:flex;align-items:center;justify-content:center;
min-height:100vh;margin:0;padding:24px;">
  <div style="max-width:520px;text-align:center;">
    <p style="color:{colour};font-size:18px;font-weight:700;margin:0;">{label}</p>
    <p style="color:#94a3b8;font-size:13px;margin:14px 0 0;">
      You can close this tab. The decision is recorded on the AquaGuard AI server
      and nothing else is needed here.
    </p>
  </div>
  <script>{script}</script>
</body></html>""",
        mimetype="text/html",
        status=200,
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Robots-Tag": "noindex, nofollow",
        },
    )


@admin_bp.route("/session/deny", methods=["GET", "POST"])
def deny_session():
    """The "No, deny" BUTTON in the alert mail: kill the pending confirmation.

    After a deny, even the real token cannot confirm -- the attempt is dead and
    the console stays locked. A fresh attempt must start from the sign-in form.
    """
    from app.services.admin_service import deny_unlock

    payload = request.get_json(silent=True) or {}
    token = str(payload.get("token") or request.args.get("token") or "")
    denied = deny_unlock(token)

    if request.method == "GET":
        return _confirm_page(False)  # the same "denied / console locked" page
    if not denied:
        return error_response("This confirmation link is not valid or has expired", 400)
    return success_response(data={"denied": True}, message="Admin access denied. The console stays locked.")


@admin_bp.post("/session/lock")
def close_session():
    """Lock the console again. Always idempotent."""
    from app.services.console_session import lock

    lock()
    return success_response(data={"unlocked": False}, message="Admin console locked")


@admin_bp.get("/session")
def session_state():
    """Whether the console is currently unlocked, and for how much longer.

    PUBLIC, unlike every other console route, and it has to be: the page calls it
    before the administrator has signed in, to decide whether to show the sign-in
    form or the console. It reports state and nothing else.
    """
    from app.services.admin_service import pending_confirmation_for, pending_denied_for
    from app.services.console_session import state

    # A DENIAL in the mail is reported here, so the web page that has been
    # waiting for the emailed confirmation can show "access denied" on its own
    # screen the moment NO was clicked -- the decision is made in the mail and
    # the browser never has to open the mail's link to learn the outcome.
    if pending_denied_for():
        return success_response(
            data={"unlocked": False, "denied": True, "awaiting_confirmation": False},
            message="Admin access denied",
        )
    if pending_confirmation_for():
        return success_response(
            data={"unlocked": False, "awaiting_confirmation": True},
            message="Waiting for confirmation from the admin's email",
        )
    return success_response(data=state())


@admin_bp.post("/password/forgot")
def forgot_password():
    """Email a 6-digit code to the console's recovery address.

    Returns WHERE the code was sent and how long it lives -- never the code, and
    never the address in full. It answers no worse than any other console route,
    because proving the credential is the only way past this one.

    PROMPT 9, REQUIREMENT 13: the response is honest. "Sent" is reported only
    when the mail service accepted the message; a provider failure surfaces its
    real detail and the cooldown is explicitly waived for a failed send, so the
    retry button is a real option rather than a locked door.
    """
    try:
        from app.services.admin_service import issue_reset_code

        return success_response(
            data=issue_reset_code(),
            message="A reset code has been sent",
        )
    except AquaGuardError as exc:
        return _failure(exc)


@admin_bp.post("/password/reset")
def reset_password():
    """Set a new console password using the emailed code -- no old password needed.

    PROMPT 9: the code is verified server-side before anything changes, the new
    password must pass the shared strength policy, the OTP is invalidated by the
    reset itself, the console session is revoked, and the audit event records
    that it happened without recording either the code or the password.
    """
    try:
        payload = request.get_json(silent=True) or {}

        from app.services.admin_service import reset_admin_password
        result = reset_admin_password(
            code=str(payload.get("code") or ""),
            new_password=str(payload.get("new_password") or ""),
        )
        return success_response(data=result, message="Admin password reset")
    except AquaGuardError as exc:
        return _failure(exc)


@admin_bp.post("/email/change/request")
def request_email_change():
    """Begin changing the admin notification/recovery email (REQUIRES unlock).

    Body: ``{new_email?} | {same_as_recovery: true}``.

    REQUIREMENT 10: an authenticated settings action. The new address must
    prove it can receive mail before the change activates. REQUIREMENT 11: the
    `same_as_recovery` mode re-points the approval address at the recovery inbox
    with no code, keeping the two mailboxes synchronized by choice.
    """
    try:
        _require_unlocked()
        payload = request.get_json(silent=True) or {}

        from app.services.admin_service import request_approval_email_change

        result = request_approval_email_change(
            payload.get("new_email"),
            same_as_recovery=bool(payload.get("same_as_recovery")),
        )
        return success_response(
            data=result,
            message=(
                "The approval email now matches the recovery address"
                if result.get("mode") == "synced_to_recovery"
                else "A verification code has been sent"
            ),
        )
    except AquaGuardError as exc:
        return _failure(exc)


@admin_bp.post("/email/change/confirm")
def confirm_email_change():
    """Activate a verified email change with the code the new inbox received.

    The code is checked on the backend: expiring, attempt-limited and single
    use. The change only ever activates through this route.
    """
    try:
        _require_unlocked()
        payload = request.get_json(silent=True) or {}

        from app.services.admin_service import confirm_email_change

        result = confirm_email_change(str(payload.get("code") or ""))
        return success_response(data=result, message="The new email address is verified and active")
    except AquaGuardError as exc:
        return _failure(exc)


@admin_bp.get("/identity")
def get_identity():
    """The console's login name and recovery email."""
    try:
        from app.services.admin_service import admin_identity
        return success_response(data=admin_identity())
    except AquaGuardError as exc:
        return _failure(exc)


@admin_bp.put("/identity")
def put_identity():
    """Change the console's login name and/or recovery email.

    Requires the console to be unlocked, like every other state-changing route:
    changing the recovery address redirects where reset codes go, so it is as
    sensitive as changing the password.
    """
    try:
        _require_unlocked()
        payload = request.get_json(silent=True) or {}

        from app.services.admin_service import update_admin_identity
        updated = update_admin_identity(
            payload.get("username"),
            payload.get("email"),
        )
        return success_response(data=updated, message="Console identity updated")
    except AquaGuardError as exc:
        return _failure(exc)


@admin_bp.post("/password")
def change_password():
    """Rotate the console password. Emails the account that owns the console."""
    try:
        _require_unlocked()
        payload = request.get_json(silent=True) or {}

        from app.services.admin_service import change_admin_password

        result = change_admin_password(
            current=str(payload.get("current_password") or ""),
            new_password=str(payload.get("new_password") or ""),
            actor_email=_console_identity()["email"],
        )
        return success_response(data=result, message="Admin password changed")
    except AquaGuardError as exc:
        return _failure(exc)


# ------------------
# Dashboard
# ------------------
@admin_bp.get("/dashboard")
def dashboard():
    """Console overview counters."""
    try:
        _require_unlocked()
        from app.services.admin_service import dashboard as summary

        return success_response(data=summary())
    except AquaGuardError as exc:
        return _failure(exc)


# ------------------
# Users
# ------------------
@admin_bp.get("/users")
def users():
    """Every account, with activity counts, searchable and paged."""
    try:
        _require_unlocked()
        from app.services.admin_service import list_users

        page, per_page = parse_pagination()
        items, meta = list_users(search=request.args.get("search"), page=page, per_page=per_page)
        return success_response(data=items, meta=meta)
    except AquaGuardError as exc:
        return _failure(exc)


@admin_bp.patch("/users/<int:user_id>/role")
def set_role(user_id: int):
    """Promote or demote an account."""
    try:
        _require_unlocked()
        payload = request.get_json(silent=True) or {}

        from app.services.admin_service import update_user_role

        return success_response(
            data=update_user_role(user_id, str(payload.get("role") or "")),
            message="Role updated",
        )
    except AquaGuardError as exc:
        return _failure(exc)


@admin_bp.delete("/users/<int:user_id>")
def remove_user(user_id: int):
    """Delete an account, and everything it owns, via the schema's cascade.

    Requires the console to be unlocked, because the unlock IS the console's
    authentication: it is the one irreversible action in the console. The check
    was MISSING here -- a locked console could still delete any account, which
    is exactly what the authorisation tests below exercise.
    """
    try:
        _require_unlocked()
        from app.services.admin_service import delete_user

        result = delete_user(user_id, actor_email=_console_identity()["email"])
        return success_response(data=result, message="Account deleted")
    except AquaGuardError as exc:
        return _failure(exc)


# ------------------
# Login details
# ------------------
@admin_bp.get("/login-details")
def login_details():
    """Filtered, paged sign-in history, each row carrying its username.

    Historical data: the table records the sign-ins that happened before user
    authentication was removed, and it is kept as a record rather than as a live
    feed - new activity no longer creates rows.
    """
    try:
        _require_unlocked()
        from app.services.login_tracking_service import list_events

        page, per_page = parse_pagination()

        success_arg = request.args.get("success")
        success_filter = None
        if success_arg in ("true", "false"):
            success_filter = success_arg == "true"

        items, meta = list_events(
            page=page,
            per_page=per_page,
            search=request.args.get("search"),
            success=success_filter,
            event_type=request.args.get("event_type"),
            start=request.args.get("start"),
            end=request.args.get("end"),
        )
        return success_response(data=items, meta=meta)
    except AquaGuardError as exc:
        return _failure(exc)


@admin_bp.get("/login-details/stats")
def login_details_stats():
    """Counters for the login-details header."""
    try:
        _require_unlocked()
        from app.services.login_tracking_service import event_stats

        return success_response(data=event_stats())
    except AquaGuardError as exc:
        return _failure(exc)


@admin_bp.get("/login-details/export")
def export_login_details():
    """Download the login-details dataset as CSV or Excel.

    WHY EXCEL COMES BACK AS CSV. An .xlsx is a ZIP of XML parts and cannot be
    produced without a spreadsheet library. A `.csv` opened by Excel IS the Excel
    view of the data -- same columns, same rows -- and Excel is what the user was
    asking for, not the container format. The filename and the MIME type say what
    the file is, so Excel opens it directly rather than showing an import wizard.

    The BOM is what makes Excel read it as UTF-8; without it, a name with an
    accent arrives mangled.
    """
    try:
        _require_unlocked()
        admin = _console_identity()
        from app.services.login_tracking_service import list_events

        success_arg = request.args.get("success")
        success_filter = None
        if success_arg in ("true", "false"):
            success_filter = success_arg == "true"

        # The whole filtered set, not the visible page -- an export that silently
        # contained only page one would be worse than no export.
        items, _ = list_events(
            page=1,
            per_page=100_000,
            search=request.args.get("search"),
            success=success_filter,
            event_type=request.args.get("event_type"),
            start=request.args.get("start"),
            end=request.args.get("end"),
        )

        headers = [
            "Username",
            "Email",
            "Event",
            "Result",
            "Device",
            "IP address",
            "Date",
            "Time",
            "Failure reason",
        ]
        buffer = io.StringIO()
        writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(headers)
        for row in items:
            stamp = str(row.get("created_at") or "")
            writer.writerow(
                [
                    row.get("user_name") or "",
                    row.get("user_email") or "",
                    row.get("event_type") or "",
                    "success" if row.get("success") else "failed",
                    row.get("device") or "",
                    row.get("ip_address") or "",
                    stamp[:10],
                    stamp[11:19],
                    row.get("failure_reason") or "",
                ]
            )

        fmt = (request.args.get("format") or "csv").lower()
        extension = "csv"
        mime = "text/csv; charset=utf-8"
        if fmt in ("xlsx", "excel", "xls"):
            # Named and typed for Excel, still CSV content. See the docstring.
            extension = "csv"
            mime = "application/vnd.ms-excel; charset=utf-8"

        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
        filename = f"aquaguard-login-details_{stamp}.{extension}"

        logger.info(
            "Login details exported (%s rows) by %s", len(items), admin["email"]
        )
        _email_export_notice(len(items), admin["email"])

        return Response(
            "\ufeff" + buffer.getvalue(),
            mimetype=mime,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except AquaGuardError as exc:
        return _failure(exc)


def _email_export_notice(count: int, actor_email: str) -> None:
    """Email a note that the dataset was exported. Never raises."""
    try:
        from app.services import mail_service
        from app.services.mail_service import login_details_export_message

        recipient = (
            current_app.config.get("ADMIN_NOTIFY_EMAIL")
            or current_app.config.get("MAIL_USERNAME")
            or actor_email
        )
        subject, text, html = login_details_export_message(
            count, datetime.now(timezone.utc).isoformat()
        )
        mail_service.send_email(recipient, subject, text, html)
    except Exception:  # noqa: BLE001 - the download already happened
        logger.exception("Could not send the export notice")


# ------------------
# Parameter limits
# ------------------
@admin_bp.get("/parameter-limits")
def get_limits():
    """Every parameter's effective limit, with the built-in default alongside."""
    try:
        _require_unlocked()
        from app.services.admin_service import get_parameter_limits

        return success_response(data=get_parameter_limits())
    except AquaGuardError as exc:
        return _failure(exc)


@admin_bp.put("/parameter-limits")
def put_limits():
    """Replace the overridden limits."""
    try:
        _require_unlocked()
        payload = request.get_json(silent=True) or {}

        from app.services.admin_service import update_parameter_limits

        return success_response(
            data=update_parameter_limits(payload),
            message="Parameter limits updated",
        )
    except AquaGuardError as exc:
        return _failure(exc)


# ------------------
# Location access scope
# ------------------
@admin_bp.get("/location-scope")
def get_location_scope_route():
    """The configured location access scope, WITH its provenance.

    PROMPT 13, REQUIREMENT 12: the response carries `updated_at` and
    `updated_by`, so the console can show who set the current restriction and
    when instead of presenting it as a setting with no history.
    """
    try:
        _require_unlocked()
        from app.services.admin_service import get_location_scope

        return success_response(data=get_location_scope())
    except AquaGuardError as exc:
        return _failure(exc)


@admin_bp.get("/location-scope/audits")
def get_location_scope_audits_route():
    """The append-only history of scope changes, newest first.

    PROMPT 13, REQUIREMENT 12. Read-only, and behind the same unlock as the
    setting it explains. REFUSED attempts are included: an attempt that was
    denied is exactly what an administrator reviewing this list is looking for,
    and a log that only recorded successes would hide it.
    """
    try:
        _require_unlocked()
        from app.services.admin_service import list_location_scope_audits

        try:
            limit = int(request.args.get("limit", 25))
        except (TypeError, ValueError):
            limit = 25
        return success_response(data=list_location_scope_audits(limit=limit))
    except AquaGuardError as exc:
        return _failure(exc)


@admin_bp.get("/location-scope/options")
def get_location_scope_options_route():
    """The states an admin may choose, for a country.

    PROMPT 13, REQUIREMENTS 2/3/6. The console offers a CHOICE from resolved
    real geography rather than a free-text box, because the stored value has to
    be the geocoder's own spelling of a state - free text is how a scope ends up
    matching nothing while looking configured.

    Read-only and console-only, like every other route here. An unreachable
    source is reported as an empty list rather than an invented one: the admin
    still sees the field and the backend still validates what they type.
    """
    try:
        _require_unlocked()
        country_name = (request.args.get("country") or "").strip()
        if not country_name:
            return success_response(data={"country": None, "states": []})

        from app.services.country_service import (
            bundled_states,
            country_states,
            resolve_country,
        )

        country = resolve_country(country_name) or {"name": country_name}
        try:
            resolved = country_states(country, limit=400)
        except Exception:  # noqa: BLE001 - a source outage is not a validation failure
            current_app.logger.warning("Scope options: live state list unavailable")
            resolved = []
        if not resolved:
            resolved = [{"name": name, "state": name} for name in bundled_states(country)]

        return success_response(data={"country": country.get("name"), "states": resolved})
    except AquaGuardError as exc:
        return _failure(exc)


@admin_bp.put("/location-scope")
def put_location_scope_route():
    """Set the location access scope.

    CHANGES STATE, so it requires an unlocked console, like every other mutating
    endpoint in this console.

    Body: ``{ "mode": "state"|"country"|null, "state": str, "country": str }``.
    A null/empty mode clears the restriction. The service validates the
    combination and refuses a half-configured scope.

    PROMPT 13: the chosen state/country must RESOLVE to a real state or country,
    and the console identity plus the time are recorded with the change and in
    the append-only audit trail. An unresolvable value is a 422 and is recorded
    as a refused attempt.
    """
    try:
        _require_unlocked()
        payload = request.get_json(silent=True) or {}

        from app.services.admin_service import update_location_scope

        # The actor comes from the CONSOLE, never from the body: a caller must
        # not be able to record the change under someone else's name.
        return success_response(
            data=update_location_scope(
                payload.get("mode"), payload.get("state"), payload.get("country")
            ),
            message="Location scope updated",
        )
    except AquaGuardError as exc:
        return _failure(exc)


# ------------------
# Notification settings
# ------------------
# ------------------
# PROMPT 12: Report-email audit
# ------------------
@admin_bp.get("/report-email-audit")
def report_email_audit():
    """Paged history of report-download-by-email requests.

    Read-only, so it follows the console's rule: unlocked console required. The
    state/country scope and every filter are applied in the SQL query on the
    backend — the frontend only sends them.
    """
    try:
        _require_unlocked()
        from app.services.admin_service import list_report_email_audits

        page, per_page = parse_pagination()
        items, meta = list_report_email_audits(
            search=request.args.get("search"),
            option=request.args.get("option"),
            status=request.args.get("status"),
            start=request.args.get("start"),
            end=request.args.get("end"),
            page=page,
            per_page=per_page,
        )
        return success_response(data=items, meta=meta)
    except AquaGuardError as exc:
        return _failure(exc)


@admin_bp.get("/notifications")
def get_notifications():
    """The editable notification types and their templates."""
    try:
        _require_unlocked()
        from app.services.admin_service import get_notification_config

        return success_response(data=get_notification_config())
    except AquaGuardError as exc:
        return _failure(exc)


@admin_bp.put("/notifications")
def put_notifications():
    """Save edited templates. The next notification uses the saved wording."""
    try:
        _require_unlocked()
        payload = request.get_json(silent=True) or {}

        from app.services.admin_service import update_notification_config

        return success_response(
            data=update_notification_config(payload),
            message="Notification settings saved",
        )
    except AquaGuardError as exc:
        return _failure(exc)


# ------------------
# ML models
# ------------------
@admin_bp.get("/models")
def list_models():
    """Every model artifact the backend can see, with its metadata."""
    try:
        _require_unlocked()
        from app.services.model_service import list_models as rows

        return success_response(data=rows())
    except AquaGuardError as exc:
        return _failure(exc)


@admin_bp.get("/models/active")
def active_model():
    """Which artifact is currently answering predictions."""
    try:
        _require_unlocked()
        from app.services.model_service import active_model_info

        return success_response(data=active_model_info())
    except AquaGuardError as exc:
        return _failure(exc)


@admin_bp.post("/models/upload")
def upload_model():
    """Import a new model artifact.

    The upload is validated by LOADING it before it is accepted, because a model
    file that cannot be deserialised is worse than no upload: the failure would
    otherwise appear later, as a broken prediction for a real user.
    """
    try:
        _require_unlocked()

        from app.services.model_service import model_service

        upload = request.files.get("file")
        if upload is None or not upload.filename:
            return error_response("No model file was uploaded", 400)

        result = import_model(upload, name=request.form.get("name"))
        return success_response(data=result, message="Model imported")
    except AquaGuardError as exc:
        return _failure(exc)


@admin_bp.post("/models/<name>/activate")
def activate_model(name: str):
    """Point the predictor at a different imported artifact."""
    try:
        _require_unlocked()

        from app.services.model_service import set_active_model

        return success_response(
            data=set_active_model(name), message=f"Model '{name}' is now active"
        )
    except AquaGuardError as exc:
        return _failure(exc)


# ---------------------------------------------------------------------------
# Model version registry (Project Updates & ML Model Management)
# ---------------------------------------------------------------------------
#
# PROMPT 7. These routes EXTEND the console; they do not replace it. The four
# routes above are untouched and still behave exactly as before, including the
# pre-existing `/models/upload` path, so nothing that depended on them breaks.
#
# AUTHORISATION IS ENFORCED HERE, NOT IN THE FRONTEND. Every route below calls
# `_require_unlocked()` first, which is the console's actual authentication -
# the console password plus a confirmed mailed unlock. Hiding a button in React
# is presentation; these checks are the control, and they hold whatever the
# browser chooses to send.
#
# EVERY UPLOAD IS VALIDATED SERVER-SIDE. The extension, the size, the checksum,
# the feature contract, the label vocabulary and an actual prediction are all
# decided by the backend. Nothing about an artifact's acceptability is inferred
# from a filename, a content type, or anything the client claimed about it.


@admin_bp.get("/model-versions/status")
def model_versions_status():
    """The deployed project, backend and ML model versions, and the deployment state.

    Read-only, but console-only like everything else here: there is no user login
    in this application, so an unlocked console is the only thing that
    authorises any of it.
    """
    try:
        _require_unlocked()
        from app.services.model_registry_service import deployment_status

        return success_response(data=deployment_status())
    except AquaGuardError as exc:
        return _failure(exc)


@admin_bp.get("/model-versions")
def model_versions_list():
    """Every registered model version, newest first, with its validation verdict."""
    try:
        _require_unlocked()
        from app.services.model_registry_service import list_versions

        return success_response(
            data=list_versions(status=request.args.get("status") or None)
        )
    except AquaGuardError as exc:
        return _failure(exc)


@admin_bp.post("/model-versions")
def model_versions_register():
    """Register a new model version from an uploaded artifact, and validate it.

    Body: multipart/form-data with

        file      the artifact (.joblib / .pkl, within the size limit)
        version   the version string to register it under  (required)
        name      an optional display label
        notes     an optional note about what changed in this version
        checksum  an optional SHA-256 the upload is expected to match
        validate  "0" to register WITHOUT validating (it still cannot be activated)

    THE ACTIVE MODEL IS NEVER TOUCHED HERE. This route stores a file, validates
    it in an isolated subprocess and writes one registry row plus audit rows. It
    has no code path that writes the active pointer, which is why a rejected or
    broken upload cannot disturb a working deployment - not "usually", but
    structurally.

    The declared checksum is verified against the STORED bytes. A mismatch means
    the upload that arrived is not the artifact that was offered, so nothing is
    registered and the attempt is audited as a failure.
    """
    try:
        _require_unlocked()
        actor = _console_identity()["email"]

        from app.services.model_registry_service import register_artifact

        version = (request.form.get("version") or "").strip()
        if not version:
            return error_response("A version string is required to register a model", 400)

        result = register_artifact(
            request.files.get("file"),
            version=version,
            actor=actor,
            display_name=request.form.get("name"),
            notes=request.form.get("notes"),
            declared_checksum=request.form.get("checksum"),
            # Absent means validate. Only an explicit "0" skips it, and a
            # skipped validation still leaves the model unactivatable.
            auto_validate=(request.form.get("validate", "1") not in ("0", "false", "no")),
        )

        passed = bool(result.get("validation_passed"))
        return success_response(
            data=result,
            message=(
                f"Model version '{result['version']}' registered and passed validation. "
                "It can now be activated."
                if passed
                else f"Model version '{result['version']}' registered but FAILED "
                "validation. It cannot be activated, and the currently active model "
                "has not been changed."
            ),
        )
    except AquaGuardError as exc:
        return _failure(exc)


@admin_bp.post("/model-versions/<int:version_id>/validate")
def model_versions_validate(version_id: int):
    """Re-run the isolated validation for a registered version.

    Safe to repeat: it reads and writes only that version's own row, so running
    it on the active model is refused explicitly rather than being allowed to
    disturb a live deployment.
    """
    try:
        _require_unlocked()
        actor = _console_identity()["email"]

        from app.services.model_registry_service import validate_version

        result = validate_version(version_id, actor)
        passed = bool(result.get("validation_passed"))
        return success_response(
            data=result,
            message=(
                f"'{result['version']}' passed validation and can be activated."
                if passed
                else f"'{result['version']}' failed validation and cannot be activated."
            ),
        )
    except AquaGuardError as exc:
        return _failure(exc)


@admin_bp.post("/model-versions/<int:version_id>/activate")
def model_versions_activate(version_id: int):
    """Activate a validated model version.

    REFUSES ANY VERSION WHOSE OWN RECORDED VALIDATION DID NOT PASS. The check is
    re-read here, immediately before the pointer moves, rather than trusted from
    the calling code - so a version cannot become the running model because a
    row was edited somewhere else between the two.

    Nothing about the current model changes unless this call succeeds.
    """
    try:
        _require_unlocked()
        actor = _console_identity()["email"]

        from app.services.model_registry_service import activate_version

        result = activate_version(version_id, actor)
        return success_response(
            data=result,
            message=(
                f"'{result['version']}' is now answering predictions. "
                "The backend has confirmed the switch."
            ),
        )
    except AquaGuardError as exc:
        return _failure(exc)


@admin_bp.post("/model-versions/<int:version_id>/rollback")
def model_versions_rollback(version_id: int):
    """Roll the active model back to an earlier validated version.

    Same guard as activation, and deliberately so: a rollback target must be a
    version that passed validation, never a `registered` or `rejected` one.
    Rolling "back" to something that never worked is not a rollback, and allowing
    it would make this the easiest way to break a running system.
    """
    try:
        _require_unlocked()
        actor = _console_identity()["email"]

        from app.services.model_registry_service import rollback_to_version

        result = rollback_to_version(version_id, actor)
        return success_response(
            data=result,
            message=(
                f"Rolled back to '{result['version']}'. The backend has confirmed the "
                "previous model is active again."
            ),
        )
    except AquaGuardError as exc:
        return _failure(exc)


@admin_bp.get("/model-audit-log")
def model_audit_log():
    """The model-change audit trail: who, which version, when, what, and the outcome.

    Every ATTEMPTED change is here, including the refusals and the failures -
    a log of successes alone cannot answer "did anyone try to activate the model
    that failed validation", which is the question this exists to answer.
    """
    try:
        _require_unlocked()
        from app.services.model_registry_service import audit_log

        return success_response(
            data=audit_log(
                limit=request.args.get("limit", 100),
                action=request.args.get("action") or None,
                version=request.args.get("version") or None,
            )
        )
    except AquaGuardError as exc:
        return _failure(exc)


# ------------------
# Overall reports
# ------------------
@admin_bp.get("/reports")
def reports():
    """Every account's predictions, in the requested category, with usernames.

    The category filter is `safe` | `warning` | `unsafe` | `all`:

        safe      the model's SAFE verdict
        warning   the model's MODERATE verdict -- the "watch this" class
        unsafe    the model's UNSAFE verdict
        all       no filter

    The username is joined in, because the requirement is that the console's
    results are attached to a person rather than to a bare user id. The shared
    visitor account's rows appear here too, as a single named owner.
    """
    try:
        _require_unlocked()
        from app.services.report_service import list_reports

        page, per_page = parse_pagination()
        items, meta = list_reports(
            page=page,
            per_page=per_page,
            category=request.args.get("category"),
            search=request.args.get("search"),
            start=request.args.get("start"),
            end=request.args.get("end"),
        )
        return success_response(data=items, meta=meta)
    except AquaGuardError as exc:
        return _failure(exc)


@admin_bp.get("/unsafe-history")
def unsafe_history():
    """THE UNSAFE PREDICTION HISTORY: only rows the model judged UNSAFE.

    A SEPARATE, DELIBERATE SLICE of the same data the reports list holds, and the
    filtering happens in SQL (`prediction = 'unsafe'`) rather than in the browser:
    a client-side filter would only ever hide rows that had already been sent, and
    the total would then describe the page rather than the history.

    Read-only, so it follows the console's rule: an unlocked console is required.
    Supports `search` (place, district, state, country or pincode), and an optional
    `start` / `end` day window. The admin's location scope is applied in the query
    too, so this section cannot surface readings the rest of the console hides.
    """
    try:
        _require_unlocked()
        from app.services.report_service import list_unsafe_predictions

        page, per_page = parse_pagination()
        items, meta = list_unsafe_predictions(
            page=page,
            per_page=per_page,
            search=request.args.get("search"),
            start=request.args.get("start"),
            end=request.args.get("end"),
        )
        return success_response(data=items, meta=meta)
    except AquaGuardError as exc:
        return _failure(exc)


@admin_bp.get("/reports/summary")
def reports_summary():
    """Counts per category, for the report filter chips."""
    try:
        _require_unlocked()
        from app.services.report_service import category_summary

        return success_response(data=category_summary())
    except AquaGuardError as exc:
        return _failure(exc)


@admin_bp.get("/reports/export")
def export_reports():
    """Download the report dataset.

    `category` selects the slice, and the file is named for it, so a per-category
    download and an all-categories download are the same code path with a
    different filter -- which is what makes them guaranteed to agree.
    """
    try:
        _require_unlocked()
        admin = _console_identity()
        from app.services.report_service import CATEGORY_LABELS, list_reports

        category = (request.args.get("category") or "all").lower()

        items, _ = list_reports(
            page=1,
            per_page=100_000,
            category=category,
            search=request.args.get("search"),
            start=request.args.get("start"),
            end=request.args.get("end"),
        )

        headers = [
            "Report ID",
            "Prediction ID",
            "Username",
            "Email",
            "Date",
            "Time",
            "Location",
            "Pincode",
            "District",
            "State",
            "Country",
            "Water Source",
            # PROMPT 4: the nearest real source and its real distance, so the
            # export is as explicit about provenance as the screen. Read straight
            # off the row; nothing derived or guessed.
            "Nearest Source",
            "Nearest Source Distance (km)",
            "Verdict",
            "Confidence (%)",
            "pH",
            "Turbidity (NTU)",
            "TDS (mg/L)",
            "Temperature (C)",
            "Dissolved Oxygen (mg/L)",
        ]
        buffer = io.StringIO()
        writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(headers)
        for row in items:
            # The place as a label ("Karaikudi, Tamil Nadu"), never the exact
            # coordinates: `list_reports` has already dropped them for this reader.
            location = ", ".join(
                part
                for part in (row.get("location_name"), row.get("location_state"))
                if part
            )
            writer.writerow(
                [
                    row.get("report_id") or "",
                    row.get("prediction_id") or "",
                    row.get("user_name") or "",
                    row.get("user_email") or "",
                    str(row.get("created_at") or "")[:10],
                    str(row.get("created_at") or "")[11:19],
                    location,
                    # The exact stored pincode when there is one; "Not Available"
                    # when not. Never inferred from the place name. The district is
                    # not a stored column, so it is echoed only when the client sent
                    # one at predict time.
                    row.get("location_pincode") or "Not Available",
                    row.get("location_district") or "Not Available",
                    row.get("location_state") or "Not Available",
                    row.get("location_country") or "Not Available",
                    row.get("water_source_type") or "",
                    row.get("nearby_water_source") or "",
                    (
                        ""
                        if row.get("nearby_water_source_distance") is None
                        else round(float(row["nearby_water_source_distance"]), 2)
                    ),
                    str(row.get("prediction") or "").upper(),
                    round(float(row.get("confidence") or 0) * 100, 1),
                    row.get("ph"),
                    row.get("turbidity"),
                    row.get("tds"),
                    row.get("temperature"),
                    row.get("dissolved_oxygen"),
                ]
            )

        fmt = (request.args.get("format") or "csv").lower()
        mime = "text/csv; charset=utf-8"
        if fmt in ("xlsx", "excel", "xls"):
            mime = "application/vnd.ms-excel; charset=utf-8"

        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
        label = CATEGORY_LABELS.get(category, "all").lower().replace(" ", "-")
        filename = f"aquaguard-reports_{label}_{stamp}.csv"

        logger.info(
            "Reports exported (%s, %s rows) by %s", category, len(items), admin["email"]
        )

        return Response(
            "\ufeff" + buffer.getvalue(),
            mimetype=mime,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except AquaGuardError as exc:
        return _failure(exc)


# ------------------
# Diagnostics
# ------------------
@admin_bp.get("/providers")
def providers():
    """Which AI providers and mail transport are configured.

    Reports PRESENCE only -- never a key, never a prefix of one. A partial
    credential in an API response is still a leaked credential.
    """
    try:
        _require_unlocked()

        from app.ai.providers import describe_providers
        from app.services import mail_service

        return success_response(
            data={
                "ai": describe_providers(current_app.config),
                "mail": {
                    "configured": mail_service.is_configured(),
                    "host": current_app.config.get("MAIL_HOST"),
                    "sender": current_app.config.get("MAIL_DEFAULT_SENDER")
                    or current_app.config.get("MAIL_USERNAME"),
                    "suppressed": bool(current_app.config.get("MAIL_SUPPRESS_SEND")),
                },
            }
        )
    except AquaGuardError as exc:
        return _failure(exc)


@admin_bp.post("/diagnostics/email")
def send_test_email():
    """Send a test message, so the mail configuration can be proven, not assumed."""
    try:
        _require_unlocked()
        admin = _console_identity()
        
        from app.services import mail_service

        recipient = (
            (request.get_json(silent=True) or {}).get("email")
            or admin["email"]
        )
        result = mail_service.send_email(
            recipient,
            "AquaGuard AI: test message",
            "This is a test message from the AquaGuard AI admin console.",
            "<p>This is a test message from the <strong>AquaGuard AI</strong> "
            "admin console.</p>",
        )
        # The status is reported as-is, including a failure: a diagnostics button
        # that always says "sent" is worse than no button.
        return success_response(
            data={"status": result.status, "detail": result.detail, "to": recipient},
            message=f"Mail status: {result.status}",
        )
    except AquaGuardError as exc:
        return _failure(exc)
