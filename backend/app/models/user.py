"""User account model."""

from app.constants import ROLE_USER
from app.extensions import bcrypt, db
from app.models.mixins import SerializableMixin, TimestampMixin


class User(TimestampMixin, SerializableMixin, db.Model):
    # A registered account.
    #
    # The column set matches `users` in database/schema.sql exactly: id, name,
    # email, password_hash, role, created_at, updated_at. `name` (not
    # `full_name`) is deliberate — the schema is the contract, and an ORM that
    # expects a column the database does not have fails at query time with a
    # confusing "Unknown column" error rather than at import time.

    __tablename__ = "users"

    id = db.Column(
        db.BigInteger().with_variant(db.Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(190), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default=ROLE_USER)

    # --- Self-service password reset ---------------------------------------
    # One pending reset code per account, stored the same way the admin console
    # stores its own: a code, an expiry, and a failure count. Kept on the user
    # row rather than in a separate table because there is only ever ONE reset in
    # flight per account, and a new request replaces the old code -- so an old
    # code can never be replayed after a fresh one has been issued.
    reset_code_hash = db.Column(db.String(255), nullable=True)
    reset_code_expires_at = db.Column(db.Integer, nullable=True)
    reset_code_attempts = db.Column(db.Integer, nullable=False, default=0)

    # created_at / updated_at come from TimestampMixin.

    # --- Relationships ---
    predictions = db.relationship(
        "WaterPrediction",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="dynamic",
    )
    alerts = db.relationship(
        "Alert",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="dynamic",
    )
    conversations = db.relationship(
        "AIConversation",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="dynamic",
    )
    # The sign-in history. `dynamic` because it is only ever paged or counted,
    # never iterated whole — an account with years of history would otherwise be
    # loaded into memory every time the user row is fetched.
    login_events = db.relationship(
        "LoginEvent",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="dynamic",
    )

    # password_hash is deliberately absent: it must never reach an API
    # response, and omitting it here makes that a property of the class rather
    # than something every serialisation site has to remember. The reset-code
    # columns are absent for the same reason.
    _serializable_fields = ("id", "name", "email", "role")
    _serializable_datetime_fields = ("created_at", "updated_at")

    # --- Password handling -------------------------------------------------
    def set_password(self, raw_password: str) -> None:
        """Hash and store the password. The plaintext is never persisted."""
        self.password_hash = bcrypt.generate_password_hash(raw_password).decode("utf-8")

    def check_password(self, raw_password: str) -> bool:
        """Verify a candidate password against the stored bcrypt hash.

        bcrypt's comparison is constant-time, so this does not leak information
        about the hash through timing.
        """
        if not self.password_hash:
            return False
        return bcrypt.check_password_hash(self.password_hash, raw_password)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<User id={self.id} email={self.email!r}>"
