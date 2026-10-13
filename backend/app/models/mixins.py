"""Reusable column mixins and base model behaviour."""

from datetime import datetime, timezone

from app.extensions import db


def utcnow() -> datetime:
    """Timezone-aware UTC now — avoids the deprecated `datetime.utcnow()`."""
    return datetime.now(timezone.utc)


class TimestampMixin:
    """Adds `created_at` / `updated_at` to a model."""

    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class SerializableMixin:
    """Provides a consistent `to_dict()` contract for API serialisation.

    Subclasses declare `_serializable_fields` (and optionally
    `_serializable_datetime_fields`) so the JSON shape stays explicit rather
    than leaking every ORM column by accident.
    """

    _serializable_fields: tuple[str, ...] = ()
    _serializable_datetime_fields: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        payload = {}
        for field in self._serializable_fields:
            payload[field] = getattr(self, field, None)
        for field in self._serializable_datetime_fields:
            value = getattr(self, field, None)
            payload[field] = value.isoformat() if value else None
        return payload
