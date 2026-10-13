"""Sign-in tracking, and the queries the admin console reads from it.

WRITE PATH — `record_event` is called by the auth service on every attempt, and
is deliberately total: it must never raise, because a failed audit write must not
fail a login. It reads the request context defensively so it works from a test or
a CLI, where there is no request at all.

READ PATH — the admin console's login-details page, with filtering and the
dataset export. Both are scoped by the caller's admin check, which lives in the
route, not here.

WHAT IS STORED, AND WHAT IS DELIBERATELY NOT.

  stored      email, success flag, event type, IP, user agent, a derived device
              label, the timestamp, and a failure reason
  never       a password, a password hash, a token, or anything derived from one

The failure reason is the SAME ambiguous sentence the API returns ("Invalid email
or password"), never "no such user" versus "wrong password". A tracking table
that distinguished them would turn an admin page into an account-enumeration
tool.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from flask import request
from sqlalchemy import func, or_, select

from app.extensions import db
from app.models import LoginEvent, User
from app.models.mixins import utcnow

logger = logging.getLogger(__name__)

EVENT_LOGIN = "login"
EVENT_LOGOUT = "logout"
EVENT_REGISTER = "register"
EVENT_ADMIN_LOGIN = "admin_login"


def _client_ip() -> str | None:
    """The caller's IP, honouring a proxy's forwarded header.

    `X-Forwarded-For` is only trustworthy behind a proxy that SETS it. It is read
    here because this deployment is expected to sit behind one (a PaaS, nginx),
    and because the alternative — logging the proxy's own IP for every user —
    makes the column useless. It is a display value, never an authorisation input.
    """
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        # The left-most entry is the original client; the rest are proxies.
        return forwarded.split(",")[0].strip()[:45]
    return (request.remote_addr or None) and request.remote_addr[:45]


def _device_label(user_agent: str) -> str:
    """A short, readable "OS · browser" label.

    Deliberately a small hand-rolled classifier rather than a user-agent parsing
    dependency. It only needs to be good enough to answer "was this me?", and an
    unknown agent degrades to a truncated string rather than to a wrong label.
    """
    ua = (user_agent or "").lower()

    if "windows" in ua:
        os_name = "Windows"
    elif "android" in ua:
        os_name = "Android"
    elif "iphone" in ua or "ipad" in ua or "ios" in ua:
        os_name = "iOS"
    elif "mac os" in ua or "macintosh" in ua:
        os_name = "macOS"
    elif "linux" in ua:
        os_name = "Linux"
    else:
        os_name = "Unknown"

    if "edg/" in ua:
        browser = "Edge"
    elif "chrome" in ua and "chromium" not in ua:
        browser = "Chrome"
    elif "firefox" in ua:
        browser = "Firefox"
    elif "safari" in ua:
        browser = "Safari"
    elif "python" in ua or "curl" in ua or "http" in ua:
        # A script or an API client, not a person.
        browser = "API client"
    else:
        browser = "Unknown"

    return f"{os_name} · {browser}"[:80]


def _client_location(raw: Any) -> dict[str, Any]:
    """Sanitise an APPROXIMATE place supplied by the client.

    Only the five place-label fields are accepted; anything else - crucially any
    latitude or longitude - is dropped. The value is a description of WHERE as a
    place ("Karaikudi, Tamil Nadu"), never a position: the admin notice does not
    need the precision of a pin and storing one would be more than the feature
    requires. A malformed value degrades to no location rather than raising, so a
    bad payload can never block a login or a registration.
    """
    if not isinstance(raw, dict):
        return {}

    fields: dict[str, Any] = {}
    for name, max_length in (
        ("name", 190),
        ("city", 120),
        ("state", 120),
        ("country", 120),
        ("pincode", 20),
    ):
        value = raw.get(name)
        if value is None:
            continue
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            value = str(value)
        if not isinstance(value, str):
            continue
        cleaned = " ".join(value.split())[:max_length]
        if cleaned:
            fields[name] = cleaned
    return fields


def record_event(
    email: str,
    success: bool,
    user_id: int | None = None,
    event_type: str = EVENT_LOGIN,
    failure_reason: str | None = None,
    location: dict | None = None,
) -> LoginEvent | None:
    """Append one sign-in event. Returns None if it could not be written.

    `location` is the client's APPROXIMATE place, when one was supplied. It is
    sanitised here and only its place labels are stored; no coordinate ever
    reaches this table.
    """
    try:
        user_agent = (request.headers.get("User-Agent") or "")[:255]
        place = _client_location(location)
        event = LoginEvent(
            user_id=user_id,
            email=(email or "")[:190],
            event_type=event_type,
            success=bool(success),
            ip_address=_client_ip(),
            user_agent=user_agent or None,
            device=_device_label(user_agent),
            failure_reason=(failure_reason or None) and failure_reason[:120],
            location_name=place.get("name"),
            location_city=place.get("city"),
            location_state=place.get("state"),
            location_country=place.get("country"),
            location_pincode=place.get("pincode"),
        )
        db.session.add(event)
        db.session.commit()
        return event
    except Exception:  # noqa: BLE001 - auditing must never break authentication
        db.session.rollback()
        logger.exception("Failed to record login event for %r", email)
        return None


def _base_query():
    return select(LoginEvent)


def list_events(
    page: int = 1,
    per_page: int = 25,
    *,
    search: str | None = None,
    success: bool | None = None,
    event_type: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """A filtered, paginated page of sign-in events, each with its username.

    The username is joined in rather than left to the client. The admin console
    shows an email beside a name, and making the browser issue a second request
    per row would be both slow and a way for the two to disagree.
    """
    from app.utils.pagination import paginate_query

    query = select(LoginEvent, User.name).outerjoin(User, LoginEvent.user_id == User.id)

    if search:
        needle = f"%{search.strip()}%"
        query = query.where(
            or_(LoginEvent.email.ilike(needle), User.name.ilike(needle))
        )
    if success is not None:
        query = query.where(LoginEvent.success.is_(bool(success)))
    if event_type:
        query = query.where(LoginEvent.event_type == event_type)
    if start:
        query = query.where(LoginEvent.created_at >= _parse_day(start))
    if end:
        # Inclusive of the whole end day, which is what a user picking a date
        # means. Comparing against midnight would silently drop that day.
        query = query.where(LoginEvent.created_at < _parse_day(end, end_of_day=True))

    query = query.order_by(LoginEvent.created_at.desc(), LoginEvent.id.desc())

    # `paginate_query` expects a model query, so the rows are paged here instead
    # and the meta rebuilt in the same shape the rest of the API uses.
    total = db.session.execute(
        select(func.count()).select_from(query.subquery())
    ).scalar_one()

    per_page = max(1, min(int(per_page or 25), 200))
    page = max(1, int(page or 1))
    rows = db.session.execute(query.limit(per_page).offset((page - 1) * per_page)).all()

    items = []
    for event, name in rows:
        payload = event.to_dict()
        # The username travels WITH the record, which is the requirement that the
        # admin dataset show results attached to a user rather than bare ids.
        payload["user_name"] = name or "—"
        payload["user_email"] = event.email
        items.append(payload)

    meta = {
        "page": page,
        "per_page": per_page,
        "total": int(total or 0),
        "pages": (int(total or 0) + per_page - 1) // per_page if per_page else 0,
    }
    return items, meta


def event_stats() -> dict[str, Any]:
    """Counters for the admin login-details header."""
    total = db.session.execute(select(func.count()).select_from(LoginEvent)).scalar_one()
    failed = db.session.execute(
        select(func.count()).select_from(LoginEvent).where(LoginEvent.success.is_(False))
    ).scalar_one()
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    today = db.session.execute(
        select(func.count())
        .select_from(LoginEvent)
        .where(LoginEvent.created_at >= today_start)
    ).scalar_one()
    unique_users = db.session.execute(
        select(func.count(func.distinct(LoginEvent.user_id))).where(
            LoginEvent.user_id.is_not(None)
        )
    ).scalar_one()

    return {
        "total": int(total or 0),
        "failed": int(failed or 0),
        "today": int(today or 0),
        "unique_users": int(unique_users or 0),
    }


def _parse_day(value: str, end_of_day: bool = False) -> datetime:
    """Parse `YYYY-MM-DD` into a UTC datetime, tolerant of a full timestamp."""
    text = str(value).strip()
    try:
        if "T" in text or "'" in text:
            stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
        else:
            stamp = datetime.fromisoformat(f"{text}T00:00:00")
    except ValueError:
        stamp = utcnow()

    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    if end_of_day and "T" not in text and "'" not in text:
        stamp = stamp.replace(hour=23, minute=59, second=59, microsecond=999)
    return stamp
