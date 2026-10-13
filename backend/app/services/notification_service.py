"""Notification rendering: turn a template plus some data into a message.

WHY TEMPLATES ARE STORED, NOT WRITTEN IN CODE. The console lets an administrator
edit the wording of each notification type, and the NEXT notification must use the
edited wording. That is stored state, so the renderer reads the template from the
settings row and falls back to the built-in default only when nothing has been
saved.

WHY RENDERING IS SO DEFENSIVE. A template is user-supplied text containing
placeholders, and it is used to build an email. Two failure modes matter:

  * An UNKNOWN placeholder (`{typo}`) must not raise — a broken template would
    otherwise silently stop every notification of that type, which is far worse
    than a leftover placeholder in the output.
  * A MISSING VALUE must not raise either, for the same reason.

So rendering uses a formatter that leaves unrecognised or absent keys as-is, and
the caller gets a usable message either way. A notification with a visible
`{typo}` is self-diagnosing; an exception is not.
"""

from __future__ import annotations

import logging
import string
from typing import Any

from app.services.admin_service import DEFAULT_NOTIFICATION_TEMPLATES

logger = logging.getLogger(__name__)

# The plain-text shell every notification is wrapped in. Kept here rather than in
# the template so an edit to the body cannot remove the disclaimer.
_DISCLAIMER = (
    "\n\n---\nAquaGuard AI is a screening tool and is not a substitute for "
    "laboratory testing.\n"
)


class _SafeFormatter(string.Formatter):
    """A formatter that never raises on a bad placeholder.

    `str.format` raises KeyError for an unknown key, ValueError for a bad format
    spec, and IndexError for a positional reference. Any of those escaping would
    turn a template edit into silently-broken notifications — the exact failure
    the console must not be able to cause.
    """

    def get_value(self, key, args, kwargs):
        if isinstance(key, str):
            # Leave an unknown placeholder visible rather than exploding.
            return kwargs.get(key, "{" + key + "}")
        return super().get_value(key, args, kwargs)

    def convert_field(self, value, conversion):
        try:
            return super().convert_field(value, conversion)
        except (ValueError, TypeError):
            return value


_FORMATTER = _SafeFormatter()


def render_template(template: str, context: dict[str, Any]) -> str:
    """Fill a template's placeholders, tolerating anything wrong with it."""
    if not template:
        return ""
    try:
        return _FORMATTER.vformat(template, (), context or {})
    except Exception:  # noqa: BLE001 - a template must never break a request
        logger.exception("Could not render a notification template")
        return template


def get_template(notification_type: str) -> dict[str, str]:
    """The stored template for a type, falling back to the built-in default."""
    default = DEFAULT_NOTIFICATION_TEMPLATES.get(notification_type)
    if default is None:
        return {
            "label": notification_type.replace("_", " ").title(),
            "subject": "AquaGuard AI notification",
            "body": "{message}",
        }

    try:
        from app.services.admin_service import get_settings

        stored = get_settings().get_templates().get(notification_type) or {}
    except Exception:  # noqa: BLE001 - outside an app context, use the default
        stored = {}

    return {
        "label": default["label"],
        "subject": stored.get("subject") or default["subject"],
        "body": stored.get("body") or default["body"],
    }


def is_enabled(notification_type: str) -> bool:
    """Whether this notification type is switched on in the console.

    Defaults to True when nothing is stored, so a type added in code is live
    immediately rather than silently off until someone remembers to enable it.
    """
    try:
        from app.services.admin_service import get_settings

        flag = get_settings().get_notification_settings().get(notification_type) or {}
        return bool(flag.get("enabled", True))
    except Exception:  # noqa: BLE001
        return True


def render_notification(
    notification_type: str,
    context: dict[str, Any],
) -> tuple[str, str, str]:
    """Build `(subject, text, html)` for a notification type.

    Returns the text-only subject and body even when the type is disabled: the
    caller decides whether to send. This keeps "should this be sent" separate from
    "what would it say", so the same renderer can power a preview in the console.
    """
    template = get_template(notification_type)

    subject = render_template(template["subject"], context)
    body = render_template(template["body"], context)

    text = f"{body.rstrip()}{_DISCLAIMER}"
    html = _to_html(subject, body)

    return subject, text, html


def _to_html(subject: str, body: str) -> str:
    """Wrap the rendered body in the same inline-styled shell the mail service uses.

    Inline styling rather than a <style> block, because Gmail strips the latter —
    the most common reason a template looks right in preview and broken in an
    inbox.
    """
    import html as html_module

    paragraphs = [
        f'<p style="margin:0 0 12px;font-size:14px;line-height:1.6;color:#334155;">'
        f"{html_module.escape(line)}</p>"
        for line in body.split("\n")
        if line.strip()
    ]

    return (
        '<!doctype html><html><body style="margin:0;padding:24px;background:#eff9ff;'
        'font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">'
        '<table role="presentation" cellpadding="0" cellspacing="0" width="100%" '
        'style="max-width:560px;margin:0 auto;background:#ffffff;border-radius:14px;'
        'border-top:3px solid #0e9de8;"><tr><td style="padding:28px;">'
        '<p style="margin:0 0 4px;font-size:18px;font-weight:700;color:#0f172a;">'
        "AquaGuard AI</p>"
        '<p style="margin:0 0 20px;font-size:11px;letter-spacing:0.18em;'
        'text-transform:uppercase;color:#007cc6;">'
        + html_module.escape(subject)
        + "</p>"
        + "".join(paragraphs)
        + '<p style="margin:18px 0 0;padding-top:14px;border-top:1px solid #e2e8f0;'
        'font-size:12px;line-height:1.6;color:#64748b;">AquaGuard AI is a screening '
        "tool and is not a substitute for laboratory testing.</p>"
        "</td></tr></table></body></html>"
    )
