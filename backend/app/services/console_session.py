"""The admin console's own session state.

THE CONSOLE'S AUTHENTICATION. Normal users have no login at all in this
application, so there is no account session to lean on and no JWT to check: the
unlock below IS the gate, and it is opened only by `POST /api/admin/session`,
which verifies the console's own username and password and then spends the
mailed confirmation.

A SHORT-LIVED SERVER-SIDE SESSION, deliberately not:

  * NOT a JWT. A token is a bearer credential: once issued it is valid until it
    expires and cannot be revoked from the server. The console needs the
    opposite - a lock button that works immediately, and a window that closes on
    its own.
  * NOT keyed by a user id. There is no user to key it by any more, and the
    console is a single shared surface anyway, so the window is keyed by the
    CONSOLE. Two administrators, or one administrator on two devices, get
    independent windows rather than sharing one another's unlock.

The store is the Flask app's extension dict, so it lives and dies with the
process. That is correct for a single-process deployment and HONEST about a
multi-process one: with several workers behind a load balancer, an unlock on one
worker is not visible to another, and the administrator would be asked to sign
in again. That is a predictable inconvenience rather than a security hole, and
the fix (a shared store) is a deployment decision rather than something to guess
at here.
"""

from __future__ import annotations

import time
from typing import Any

from flask import current_app, has_app_context

# Where the unlock timestamps live.
_EXTENSION_KEY = "admin_console_sessions"

# The console's own key. One console, one lock - which is what the credential is.
CONSOLE_KEY = "console"


def _store() -> dict[str, float]:
    """The process-local map of console key -> unlock expiry (epoch seconds)."""
    return current_app.extensions.setdefault(_EXTENSION_KEY, {})


def _window_seconds() -> int:
    """The unlock window, in seconds.

    Guarded for a missing application context. It is always called from inside
    one in production, but `state()` is also reachable from a CLI or a diagnostic
    script, and an unguarded `current_app` there raises "Working outside of
    application context" - a failure that says nothing about the actual problem.
    The configured default is the right answer when there is no configuration to
    read.
    """
    if not has_app_context():
        return 60 * 60
    return int(current_app.config.get("ADMIN_SESSION_MINUTES", 60) or 60) * 60


def unlock() -> dict[str, Any]:
    """Unlock the console and report the expiry."""
    expires = time.time() + _window_seconds()
    _store()[CONSOLE_KEY] = expires

    return {
        "unlocked": True,
        "expires_at": expires,
        "seconds_remaining": int(expires - time.time()),
        "window_minutes": _window_seconds() // 60,
    }


def lock() -> None:
    """Lock the console. Idempotent."""
    _store().pop(CONSOLE_KEY, None)


def is_unlocked() -> bool:
    """True when the console has an unexpired unlock.

    An expired entry is dropped on read rather than left to accumulate, so a
    console nobody locks does not leak memory.

    Guarded for a missing application context, because this is called from an
    authorisation guard that a CLI or a unit test may reach with none.
    """
    if not has_app_context():
        return False

    store = _store()
    expires = store.get(CONSOLE_KEY)
    if expires is None:
        return False

    if expires <= time.time():
        store.pop(CONSOLE_KEY, None)
        return False

    return True


def state() -> dict[str, Any]:
    """The current unlock state, for the console header."""
    unlocked = is_unlocked()
    seconds_remaining = 0

    if unlocked:
        expires = _store().get(CONSOLE_KEY)
        if expires:
            seconds_remaining = max(0, int(expires - time.time()))

    return {
        "unlocked": unlocked,
        "seconds_remaining": seconds_remaining,
        "window_minutes": _window_seconds() // 60,
    }
