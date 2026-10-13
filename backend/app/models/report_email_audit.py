"""Report-email audit trail — one append-only row per Reports-to-Mail request.

PROMPT 12. The Reports page's "email me the report" workflow is a network action
that hands an attachment to an outside mailbox. Like the login_events table, the
current state of the world cannot answer "who asked, when, and what happened",
so a separate append-only table is the shape that keeps that history.

WHAT IS STORED, AND WHY IT IS SAFE.

  * The recipient address is stored in full — it IS the record's subject.
  * No password, no token, no report content. There is no column for any of
    them, so no future change can forget and start writing one.
  * The delivery status is the transport's own verdict, stored verbatim
    (sent / failed / suppressed / disabled / unconfigured), so an audit reader
    can tell a provider-accepted message from a suppression — never a dressed-up
    success.
  * LOCATION IS OPTIONAL AND EXPLICIT. A row carries a place only when the
    requester deliberately sent a browser-obtained, reverse-geocoded location
    with the request (the same grant/consent flow the rest of the app uses) —
    never inferred, never guessed, and only at place granularity. When nothing
    legitimate is available the fields stay NULL and the admin page shows
    "Location unavailable" instead of inventing something.
"""

from app.extensions import db
from app.models.mixins import SerializableMixin, TimestampMixin

_BIGINT = db.BigInteger().with_variant(db.Integer, "sqlite")


class ReportEmailAudit(TimestampMixin, SerializableMixin, db.Model):
    __tablename__ = "report_email_audits"

    id = db.Column(_BIGINT, primary_key=True, autoincrement=True)

    # The address the report was sent to, exactly as validated.
    recipient_email = db.Column(db.String(190), nullable=False, index=True)

    # REPORT_PDF | REPORT_CSV | ALL_PDF | ALL_CSV
    report_option = db.Column(db.String(20), nullable=False, index=True)

    # The transport's OWN verdict, stored verbatim. Never rewritten later.
    delivery_status = db.Column(db.String(30), nullable=False, index=True)

    # How many reports the attachment carried (1 for single-report options).
    reports_included = db.Column(db.Integer, nullable=True)

    # The account whose reports were mailed (the visitor account for
    # unauthenticated requests). Nullable: kept for readability of old rows.
    user_id = db.Column(
        _BIGINT,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # The user's display name, copied at write time so a later account deletion
    # (the FK above is SET NULL) still leaves a readable audit row.
    requester_name = db.Column(db.String(120), nullable=True)

    # The admin identity only when the console itself asked for the mail. The
    # audit route records this separately; it is not a user-account reference.
    admin_username = db.Column(db.String(120), nullable=True)

    # Explicit, consented location — place granularity only. Set by the client
    # when the browser geolocation permission was granted and the resulting fix
    # was reverse-geocoded; NULL when denied/absent. No coordinates are stored.
    location_name = db.Column(db.String(190), nullable=True)
    location_city = db.Column(db.String(120), nullable=True)
    location_state = db.Column(db.String(120), nullable=True)
    location_country = db.Column(db.String(120), nullable=True)
    location_pincode = db.Column(db.String(20), nullable=True)
    # How the place was obtained: "browser" (consented geolocation fix,
    # reverse-geocoded) — the only accepted value. Anything else is refused.
    location_source = db.Column(db.String(20), nullable=True)

    # Short device label the client may send ("Windows · Chrome"). Never a
    # fingerprint; only what the user agent already tells everyone.
    device_label = db.Column(db.String(80), nullable=True)

    user = db.relationship("User", foreign_keys=[user_id], passive_deletes=True)

    @property
    def updated_at(self):
        return self.created_at

    _serializable_fields = (
        "id",
        "recipient_email",
        "report_option",
        "delivery_status",
        "reports_included",
        "user_id",
        "requester_name",
        "admin_username",
        "location_name",
        "location_city",
        "location_state",
        "location_country",
        "location_pincode",
        "location_source",
        "device_label",
    )
    _serializable_datetime_fields = ("created_at",)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<ReportEmailAudit id={self.id} to={self.recipient_email!r} "
            f"option={self.report_option} status={self.delivery_status}>"
        )
