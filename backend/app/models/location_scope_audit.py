"""Location-scope change audit trail — one append-only row per scope change.

PROMPT 13. The geographic scope is the single setting that decides WHO MAY USE
the water-quality feature at all, so "who changed it, when, and from what to
what" is not a nicety — it is the question an administrator most needs answered
after the fact. The current value of the scope cannot answer it: it records
only what is true NOW, and a mistake is corrected by overwriting.

WHAT IS STORED, AND WHY IT IS SAFE.

  * `actor` is the CONSOLE identity, never a user account or a session token.
  * The previous and resulting mode/state/country are stored as text, so the
    change is legible from the log alone without reconstructing it.
  * NO SECRET IS STORED. `detail` is a short human sentence; it is never
    populated with a credential, an API key, or a traceback that might contain
    one.

FAILED ATTEMPTS ARE RECORDED TOO, which is the entire point of a log rather
than a counter: "someone tried to open the scope to a country that does not
exist" is exactly the event nobody wants to discover from the behaviour of a
running system instead. There is deliberately NO UPDATE OR DELETE path on this
table anywhere in the application.

CHANGING SCOPE DELETES NOTHING. This table records the changes; the
predictions, reports and audit rows that predate a narrowing remain stored and
are merely filtered on READ (see `admin_service.list_predictions`), because
requirement 10 asks that history survive a scope change, not that it be
destroyed by one.
"""

from app.extensions import db
from app.models.mixins import SerializableMixin, utcnow


class LocationScopeAudit(SerializableMixin, db.Model):
    """One row per attempted change to the administrative location scope."""

    __tablename__ = "location_scope_audits"

    id = db.Column(
        # The variant is load-bearing on SQLite, as it is on model_audit_logs:
        # SQLite only auto-increments a column declared exactly
        # `INTEGER PRIMARY KEY`, so a bare BigInteger there makes every insert
        # fail with a NOT NULL error on `id`.
        db.BigInteger().with_variant(db.Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )

    # The console identity that made the change - the same value the rest of
    # the console audits with.
    actor = db.Column(db.String(190), nullable=False, index=True)

    # state | country | off - what the admin was trying to SET.
    new_mode = db.Column(db.String(20), nullable=True, index=True)
    new_state = db.Column(db.String(190), nullable=True)
    new_country = db.Column(db.String(190), nullable=True)

    # What was in force BEFORE, so the change is legible from the log alone.
    # All NULL means the scope was off before the change.
    previous_mode = db.Column(db.String(20), nullable=True)
    previous_state = db.Column(db.String(190), nullable=True)
    previous_country = db.Column(db.String(190), nullable=True)

    # 0 when the change was REFUSED - an unresolvable state, a missing country,
    # a half-configured scope. Recorded so an attempt cannot be hidden by the
    # absence of a success.
    success = db.Column(db.Boolean, nullable=False, default=False, index=True)

    # Short human explanation. Never a credential, never a raw traceback.
    detail = db.Column(db.String(500), nullable=True)

    occurred_at = db.Column(db.DateTime, default=utcnow, nullable=False, index=True)

    _serializable_fields = (
        "id",
        "actor",
        "new_mode",
        "new_state",
        "new_country",
        "previous_mode",
        "previous_state",
        "previous_country",
        "success",
        "detail",
    )
    _serializable_datetime_fields = ("occurred_at",)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<LocationScopeAudit {self.previous_mode or 'off'} -> "
            f"{self.new_mode or 'off'} ok={self.success} by {self.actor}>"
        )