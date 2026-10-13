"""Login event model — one row per sign-in attempt that succeeded or failed.

WHY THIS EXISTS. `users` holds the CURRENT state of an account; it cannot answer
"when did this person last sign in, from where, and how often" without being
overwritten each time. A separate append-only table is the only shape that keeps
that history.

WHY IT IS ALSO PRIVACY-SENSITIVE, AND WHAT THAT MEANS FOR THE SCHEMA.

  * The IP address and user agent are stored, because "sign-in from a new
    location" is the whole point of the feature. They are stored in full rather
    than hashed: a hash cannot be shown to an administrator, which would make the
    column useless for the only thing it is for.
  * The PASSWORD is never touched, and neither is any token. There is no column
    for either, so it is not something a future change can forget.
  * Rows are scoped to a user and cascade on delete, so removing an account
    removes its login history with it rather than leaving an orphaned trail.

A FAILED ATTEMPT IS RECORDED TOO, and this matters: a table that only recorded
successes could not show the brute-force pattern that is the main reason anyone
reads this page.
"""

from app.extensions import db
from app.models.mixins import SerializableMixin, TimestampMixin

_BIGINT = db.BigInteger().with_variant(db.Integer, "sqlite")


class LoginEvent(TimestampMixin, SerializableMixin, db.Model):
    __tablename__ = "login_events"

    id = db.Column(_BIGINT, primary_key=True, autoincrement=True)

    # Nullable, because a failed attempt for an address with no account is still
    # worth recording — that is the enumeration attempt. The email is kept
    # alongside it so such a row is still readable.
    user_id = db.Column(
        _BIGINT,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    email = db.Column(db.String(190), nullable=False, index=True)

    # "login" | "logout" | "register" | "admin_login"
    event_type = db.Column(db.String(20), nullable=False, default="login", index=True)
    success = db.Column(db.Boolean, nullable=False, default=True, index=True)

    ip_address = db.Column(db.String(45), nullable=True)  # 45 chars fits IPv6
    user_agent = db.Column(db.String(255), nullable=True)
    # A short, already-derived label ("Windows · Chrome"). Stored rather than
    # recomputed so a later change to the parser cannot rewrite history.
    device = db.Column(db.String(80), nullable=True)
    # Why a failed attempt failed, in the same ambiguous wording the API returns.
    # Never the password, and never anything derived from it.
    failure_reason = db.Column(db.String(120), nullable=True)

    # Where the user was when they registered / signed in, as an APPROXIMATE
    # PLACE. Supplied by the client after a reverse-geocode of the browser's
    # position, or left empty when permission was denied. The exact coordinates
    # are never stored here and never leave the client: a place name is what the
    # admin notice needs, and a pin would be more precision than the feature
    # requires. Nullable because the lookup can fail or the user can decline.
    location_name = db.Column(db.String(190), nullable=True)
    location_city = db.Column(db.String(120), nullable=True)
    location_state = db.Column(db.String(120), nullable=True)
    location_country = db.Column(db.String(120), nullable=True)
    location_pincode = db.Column(db.String(20), nullable=True)

    user = db.relationship("User", back_populates="login_events")

    # created_at comes from TimestampMixin and is the "when" of the attempt.
    # `updated_at` is exposed as a property for the same reason the other models
    # do it: login events are immutable, so a second timestamp column would only
    # add a way for the two to disagree.
    @property
    def updated_at(self):
        return self.created_at

    _serializable_fields = (
        "id",
        "user_id",
        "email",
        "event_type",
        "success",
        "ip_address",
        "user_agent",
        "device",
        "failure_reason",
        "location_name",
        "location_city",
        "location_state",
        "location_country",
        "location_pincode",
    )
    _serializable_datetime_fields = ("created_at",)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<LoginEvent id={self.id} email={self.email!r} ok={self.success}>"
