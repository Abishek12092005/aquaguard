"""Aqua AI conversation model — matches `aqua_ai_conversations`."""

from app.extensions import db
from app.models.mixins import SerializableMixin, TimestampMixin

_BIGINT = db.BigInteger().with_variant(db.Integer, "sqlite")


class AIConversation(TimestampMixin, SerializableMixin, db.Model):
    __tablename__ = "aqua_ai_conversations"

    id = db.Column(_BIGINT, primary_key=True, autoincrement=True)
    user_id = db.Column(
        _BIGINT,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    title = db.Column(db.String(180), nullable=False, default="New conversation")

    user = db.relationship("User", back_populates="conversations", passive_deletes=True)
    messages = db.relationship(
        "AIMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="AIMessage.id",
        passive_deletes=True,
        lazy="dynamic",
    )

    _serializable_fields = ("id", "user_id", "title")
    _serializable_datetime_fields = ("created_at", "updated_at")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AIConversation id={self.id} title={self.title!r}>"
