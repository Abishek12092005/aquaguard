"""Alert model — matches the `alerts` table in database/schema.sql."""

from app.constants import ALERT_WATER_UNSAFE
from app.extensions import db
from app.models.mixins import SerializableMixin, TimestampMixin

_BIGINT = db.BigInteger().with_variant(db.Integer, "sqlite")


class Alert(TimestampMixin, SerializableMixin, db.Model):
    __tablename__ = "alerts"

    id = db.Column(_BIGINT, primary_key=True, autoincrement=True)
    user_id = db.Column(
        _BIGINT,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Nullable by design: system notices are not tied to a specific reading.
    # ON DELETE SET NULL — deleting a prediction must not erase the record that
    # the user was warned about it.
    prediction_id = db.Column(
        _BIGINT,
        db.ForeignKey("water_predictions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    type = db.Column(db.String(40), nullable=False, default=ALERT_WATER_UNSAFE)
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, nullable=False, default=False)

    # When the user dealt with the alert, or NULL while it still stands.
    #
    # This is a real column rather than a flag derived from `is_read`, because
    # "seen" and "dealt with" are genuinely different states and the previous
    # code conflated them: `resolve_alert` set `is_read = True` and returned a
    # hand-written `status: "resolved"` for that one response, while
    # `_derive_status` went on answering "acknowledged" forever after. The button
    # appeared to work and the change evaporated on the next page load.
    #
    # NULL rather than a boolean so the timestamp of the resolution is kept too,
    # which is what makes "how long was this open?" answerable later.
    resolved_at = db.Column(db.DateTime, nullable=True)

    # The schema has created_at only, so `updated_at` is exposed as a plain
    # property rather than a mapped column that would break every SELECT.
    @property
    def updated_at(self):
        return self.created_at
    # --- Relationships ---
    __table_args__ = (
        # One alert per prediction, enforced by the database rather than by
        # convention. The service also checks before inserting (so the common
        # case is a clean no-op), but only a unique key closes the window where
        # two concurrent requests both pass that check.
        #
        # NULLs are excluded from a MySQL unique index, so system notices that
        # are not tied to a prediction are unaffected by this constraint.
        db.UniqueConstraint("prediction_id", name="uq_alerts_prediction_id"),
    )

    # --- Relationships ---
    user = db.relationship("User", back_populates="alerts", passive_deletes=True)
    prediction = db.relationship("WaterPrediction", back_populates="alerts")

    _serializable_fields = (
        "id",
        "user_id",
        "prediction_id",
        "type",
        "message",
        "is_read",
    )
    _serializable_datetime_fields = ("created_at", "resolved_at")

    @property
    def is_resolved(self) -> bool:
        """True once the user has dealt with this alert."""
        return self.resolved_at is not None

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Alert id={self.id} type={self.type} read={self.is_read}>"
