"""Aqua AI message model — matches `aqua_ai_messages`."""

from app.constants import AI_ROLE_USER
from app.extensions import db
from app.models.mixins import SerializableMixin, TimestampMixin

_BIGINT = db.BigInteger().with_variant(db.Integer, "sqlite")


class AIMessage(TimestampMixin, SerializableMixin, db.Model):
    __tablename__ = "aqua_ai_messages"

    id = db.Column(_BIGINT, primary_key=True, autoincrement=True)
    conversation_id = db.Column(
        _BIGINT,
        db.ForeignKey("aqua_ai_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    role = db.Column(db.String(20), nullable=False, default=AI_ROLE_USER)
    content = db.Column(db.Text, nullable=False)

    # The schema has created_at only, so `updated_at` is exposed as a plain
    # property rather than a mapped column that would break every SELECT.
    @property
    def updated_at(self):
        return self.created_at
    conversation = db.relationship("AIConversation", back_populates="messages")

    _serializable_fields = ("id", "conversation_id", "role", "content")
    _serializable_datetime_fields = ("created_at",)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AIMessage id={self.id} role={self.role}>"
