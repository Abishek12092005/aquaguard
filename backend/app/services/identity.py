"""Who the current request is acting as, now that visitors need no account.

THE APPLICATION IS OPEN. There is no user login, no registration and no session:
a visitor arrives, browses, and submits a water sample without ever signing in.
Every feature that USED to be scoped to an account still needs an owner for its
rows, though - `water_predictions.user_id`, `alerts.user_id` and
`aqua_ai_conversations.user_id` are NOT NULL foreign keys, and the "your
predictions" queries filter on them.

So ownership is resolved here, in ONE place, by ONE rule:

    a request that carries a valid bearer token is that account,
    any other request is the shared VISITOR account.

The visitor row is a real `users` row - a single, well-known account created on
first use - rather than a nullable `user_id` or a per-browser identity. That
choice matters:

  * The schema is untouched, so no migration is needed and no cascade, index or
    join changes meaning.
  * History, alerts, reports and the dashboard keep filtering on `user_id`, so
    every existing query, chart and console screen keeps working unchanged.
  * An admin who browses the app while signed in to the console sees THEIR OWN
    predictions, not the shared visitor pool, which is what a signed-in operator
    expects.

WHAT THIS DELIBERATELY IS NOT. It is not an authentication system: the visitor
account is public and holds no secret, so nothing here may ever be used to decide
whether a request is ALLOWED. The admin console is the only gated surface, and it
is gated by its own console credential and emailed confirmation - see
`routes/admin_routes.py`.
"""

from __future__ import annotations

import logging
import threading

from app.constants import ROLE_USER
from app.extensions import db

logger = logging.getLogger(__name__)

# PROMPT 16: the JWT subject claim is now VERIFIED against a live account
# inside `current_user_id()` itself, at the moment of use, rather than only
# at token verification time. That means a token for an account the console
# has since deleted resolves to the visitor here, instead of relying on the
# lookup loader's separate decision -- so row ownership can never be claimed
# by a token whose subject does not correspond to a real, existing row.

# The shared visitor account. A fixed, readable address rather than a generated
# one, so the row can be found again after a restart without storing an id
# anywhere, and so it is obvious in the admin console what it is.
VISITOR_EMAIL = "visitor@aquaguard.local"
VISITOR_NAME = "Visitor"

# The visitor's role is the ordinary `user` role, because `users.role` carries a
# CHECK constraint allowing only `user` and `admin` - and inventing a third value
# would mean a schema migration for a row nobody signs into. The visitor is
# therefore recognised by its EMAIL, which is what every guard checks.

# A password hash the account can never use: this account is not a credential and
# no login flow exists to submit one against. It is stored because the column is
# NOT NULL, not because anything checks it.
UNUSABLE_PASSWORD_HASH = "!aquaguard-visitor-account-has-no-password!"


# The visitor's id, resolved once per process.
#
# EVERY prediction, history page and dashboard call resolves its owner through
# `current_user_id`, and an unauthenticated request lands on `visitor()` - so
# this was a `SELECT ... WHERE email = ?` on the hot path of essentially every
# request, to learn an id that is a durable property of the database.
#
# It is cached deliberately, and the cache is only ever populated from a
# committed row, so the cached value is exactly the id that row has. Deleting
# the visitor account and re-creating it out of band would invalidate the cache;
# that is a manual database operation, and `clear_visitor_cache()` exists for it.
_visitor_id: int | None = None
_visitor_lock = threading.Lock()


def clear_visitor_cache() -> None:
    """Forget the cached visitor id — after re-creating the visitor account."""
    global _visitor_id
    with _visitor_lock:
        _visitor_id = None


def visitor() -> "object":
    """The shared visitor row, created on first use.

    Commits, because the row is a durable fact rather than part of a caller's
    request. Creation is race-safe enough for this project: a duplicate insert
    can only ever happen on the very first simultaneous requests, and the loser
    re-reads the row in the `except` branch below rather than failing the
    request.
    """
    global _visitor_id

    if _visitor_id is not None:
        from app.models import User

        cached = db.session.get(User, _visitor_id)
        if cached is not None:
            return cached

    from app.models import User

    existing = User.query.filter_by(email=VISITOR_EMAIL).first()
    if existing is not None:
        with _visitor_lock:
            _visitor_id = existing.id
        return existing

    row = User(
        name=VISITOR_NAME,
        email=VISITOR_EMAIL,
        password_hash=UNUSABLE_PASSWORD_HASH,
        role=ROLE_USER,
    )
    db.session.add(row)
    try:
        db.session.commit()
    except Exception:  # noqa: BLE001 - a concurrent creator won the race
        db.session.rollback()
        found = User.query.filter_by(email=VISITOR_EMAIL).first()
        if found is not None:
            with _visitor_lock:
                _visitor_id = found.id
            return found
        raise
    logger.info("Created the shared visitor account for unauthenticated use")
    with _visitor_lock:
        _visitor_id = row.id
    return row


def current_user_id() -> int:
    """The id of the account this request acts as.

    The ONLY definition of ownership in the application. Every service that
    filters rows by owner calls this, rather than reading the token itself, so
    "who owns this" is answered in one place and cannot drift between features.
    """
    identity = _token_identity()
    if identity is None:
        return visitor_id()

    from app.models import User

    account = db.session.get(User, identity)
    if account is None:
        # A token for an account that no longer exists. The admin console deletes
        # accounts, so this is reachable: fall back to the visitor rather than
        # failing an ordinary page view, which is what an open application
        # should do with a stale credential.
        return visitor_id()
    return account.id


def visitor_id() -> int:
    """The shared visitor account's id, resolved once per process.

    The hot-path accessor. Callers that only need the id - which is every
    owner-scoped query and every prediction - never need the row itself.
    """
    if _visitor_id is not None:
        return _visitor_id
    return visitor().id


def is_visitor() -> bool:
    """True when this request is acting as the shared visitor account."""
    identity = _token_identity()
    if identity is None:
        return True
    from app.models import User

    account = db.session.get(User, identity)
    return account is None or account.email == VISITOR_EMAIL


def _token_identity() -> int | None:
    """The bearer token's subject id, or None when there is no usable token.

    Deliberately never raises. A missing, malformed or expired token is not an
    error for an application that does not require one - it simply means the
    visitor is the caller.

    `get_jwt_identity()` alone answers None unless some extension has already
    VERIFIED the request's header -- which, on an endpoint that does not itself
    require auth, nothing does. That made a signed-in caller's prediction land
    on the shared visitor and broke row isolation. `verify_jwt_in_request` is
    called here so the header is checked on the spot; its failure modes are the
    same "no usable token" cases and are swallowed into None like the rest.
    """
    try:
        from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request

        try:
            verify_jwt_in_request(optional=True)
        except Exception:  # noqa: BLE001 - missing, malformed or expired token
            return None

        identity = get_jwt_identity()
    except Exception:  # noqa: BLE001 - no token, or no request context
        return None

    if identity is None:
        return None
    try:
        return int(identity)
    except (TypeError, ValueError):
        return None
