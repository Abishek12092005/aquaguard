"""Admin console settings — the admin password, and the notification templates.

WHY THIS IS A TABLE AND NOT CONFIGURATION. Two of the requested behaviours need
state the deployment cannot hold:

  1. The admin password has to be CHANGEABLE from the console. A value in `.env`
     is immutable at runtime, so "change password" could only ever pretend.
  2. Notification templates have to be editable, and the NEXT notification has to
     use the edited wording. That is stored state by definition.

It is a single-row table. `id == 1` is the only row, created on demand; a second
row would be a second source of truth for the admin password, which is exactly
the sort of thing that makes "why will my new password not work?" happen.
"""

import json

from app.extensions import db
from app.models.mixins import SerializableMixin, TimestampMixin, utcnow

# The single row's primary key.
SETTINGS_ID = 1


class AdminSettings(TimestampMixin, SerializableMixin, db.Model):
    __tablename__ = "admin_settings"

    id = db.Column(db.Integer, primary_key=True)

    # The admin console password, bcrypt-hashed. NULL means "no password has been
    # set through the console yet", and the boot-time value from the environment
    # is used to seed it on first login (see `admin_service`).
    password_hash = db.Column(db.String(255), nullable=True)

    # The editable notification templates, keyed by notification type.
    #
    # JSON rather than one column per type because the set of types is expected to
    # grow (the requested list already includes prediction, alert and
    # threshold notices), and a schema change per new type would be a schema
    # change per new type forever.
    #
    # Shape: {"water_unsafe": {"label": ..., "subject": ..., "body": ...}, ...}
    notification_templates = db.Column(db.Text, nullable=True)

    # Which types are currently enabled, and the threshold at which a "warning"
    # notification is raised. Stored as JSON for the same reason.
    notification_settings = db.Column(db.Text, nullable=True)

    # --- Parameter limits --------------------------------------------------
    # Editable per-parameter accepted bounds. NULL means "use the built-in
    # constants", so an untouched deployment behaves exactly as it did before
    # this table existed.
    parameter_limits = db.Column(db.Text, nullable=True)

    # --- Location access scope ---------------------------------------------
    # The administrator-fixed area inside which water-quality checks are allowed.
    #
    # `location_scope_mode` is "state", "country" or NULL (no restriction).
    # `location_scope_state` and `location_scope_country` hold the chosen area
    # names. They are stored as plain strings rather than JSON because each is a
    # single value, and NULL on the mode means the feature is OFF, so an existing
    # deployment keeps working with no restriction until an admin sets one.
    #
    # WHY THE COLUMN NAMES MATCH THE ATTRIBUTES `location_routes._scope()` READS:
    # that helper resolves the scope on every location lookup, and reading the
    # columns directly keeps the enforcement path a single attribute access with
    # no parsing step that could disagree with the console's own view.
    location_scope_mode = db.Column(db.String(20), nullable=True)
    location_scope_state = db.Column(db.String(190), nullable=True)
    location_scope_country = db.Column(db.String(190), nullable=True)

    # PROMPT 13, REQUIREMENT 4: WHEN and BY WHOM the scope was last changed.
    #
    # These live on the SETTINGS row rather than only in `location_scope_audits`
    # because the console has to be able to answer "who set this, and when?"
    # from the settings screen itself, without a second query whose result could
    # disagree with the value being displayed. The audit table is the full
    # history; these two columns are the most recent entry of it, denormalised
    # so the answer is on the row that carries the scope.
    #
    # `location_scope_updated_at` is a plain TIMESTAMP, NOT the row's own
    # `updated_at`: that column moves for every unrelated settings save (a
    # notification template, a parameter limit), so it cannot answer "when was
    # the SCOPE last touched". `location_scope_updated_by` is the console
    # identity, never a user account or a session token.
    location_scope_updated_at = db.Column(db.DateTime, nullable=True)
    location_scope_updated_by = db.Column(db.String(190), nullable=True)

    # --- Admin console identity --------------------------------------------
    # The credentials the console signs in with, editable from inside the
    # console. They are STORED rather than read from the environment for the same
    # reason the password is: the requirement is that the console can change its
    # own username and recovery address, and an env value is immutable at runtime.
    #
    # `admin_username` is the login name (default "abishek"), and
    # `admin_email` is where a password-reset code is mailed. Both NULL means
    # "use the configured defaults", so an existing deployment keeps working.
    admin_username = db.Column(db.String(190), nullable=True)
    admin_email = db.Column(db.String(190), nullable=True)

    # --- Admin console identity --------------------------------------------
    #
    # PROMPT 8: WHERE APPROVAL EMAILS GO.
    #
    # `admin_email` remains the console's RECOVERY address - where a password
    # reset code goes. `admin_approval_email` is a SEPARATE, optional setting for
    # the address that receives login approval requests.
    #
    # They are separate because they answer different questions and are trusted
    # for different things. Anyone who can read the recovery inbox can already
    # take over the console by resetting the password, so that address is already
    # an access-approver by definition. An approval address lets an operator send
    # approvals somewhere else entirely - a security mailbox, a second
    # administrator, a group alias - without changing where reset codes go.
    #
    # Unset means "same as the recovery address", which is exactly the previous
    # behaviour, so an existing deployment keeps working with no configuration
    # change at all.
    admin_approval_email = db.Column(db.String(190), nullable=True)

    # One pending password-reset code, stored as JSON:
    #   { "code": "123456", "expires_at": <epoch>, "attempts": <int> }
    #
    # A SINGLE slot rather than a table: only one reset can be in flight for the
    # console, and a new request replaces the previous code, so an old code can
    # never be used after a fresh one has been issued.
    reset_code = db.Column(db.Text, nullable=True)

    # One pending console-unlock confirmation, stored as JSON:
    #   { "token": <urlsafe>, "user_id": <int>, "expires_at": <epoch> }
    # The "Yes, confirm" link in the alert mail is what spends this token.
    unlock_confirmation = db.Column(db.Text, nullable=True)

    @property
    def updated_at(self):
        return self.created_at

    _serializable_fields = ("id",)
    _serializable_datetime_fields = ()

    # --- JSON accessors ----------------------------------------------------
    # Never expose the raw text columns as serialisable fields, and never let a
    # malformed value take a request down: a corrupt JSON blob returns the
    # default, because a settings row is not worth a 500.

    def get_templates(self) -> dict:
        return _safe_json(self.notification_templates, {})

    def set_templates(self, value: dict) -> None:
        self.notification_templates = json.dumps(value or {})

    def get_notification_settings(self) -> dict:
        return _safe_json(self.notification_settings, {})

    def set_notification_settings(self, value: dict) -> None:
        self.notification_settings = json.dumps(value or {})

    def get_parameter_limits(self) -> dict:
        return _safe_json(self.parameter_limits, {})

    def set_parameter_limits(self, value: dict) -> None:
        self.parameter_limits = json.dumps(value or {})

    def get_location_scope(self) -> dict:
        """The configured location scope as a small, always-safe dict.

        Returns ``{"mode": None|"state"|"country", "state": str|None,
        "country": str|None, "updated_at": datetime|None,
        "updated_by": str|None}``. An unset or unrecognised mode reads as None,
        which the enforcement path treats as "no restriction" — so a corrupt or
        half-written row can never lock every user out of the feature.

        PROMPT 13 adds the two provenance fields, so the console can show who
        set the scope and when. They are always present (possibly None) so no
        caller has to guard for their absence.
        """
        mode = (self.location_scope_mode or "").strip().lower() or None
        if mode not in ("state", "country"):
            mode = None
        return {
            "mode": mode,
            "state": (self.location_scope_state or "").strip() or None,
            "country": (self.location_scope_country or "").strip() or None,
            "updated_at": self.location_scope_updated_at,
            "updated_by": (self.location_scope_updated_by or "").strip() or None,
        }

    def set_location_scope(
        self,
        mode: str | None,
        state: str | None,
        country: str | None,
        actor: str | None = None,
    ) -> None:
        """Store the scope. A None mode clears the restriction entirely.

        PROMPT 13 records WHO made the change and WHEN, on the same commit as
        the value itself. They are stamped together deliberately: provenance
        written in a second write could disagree with the value it describes if
        that write failed, and a scope that shows a value with no actor — or an
        actor with no value — is worse than no provenance at all.
        """
        normalised = (mode or "").strip().lower() or None
        self.location_scope_mode = normalised
        self.location_scope_state = (state or "").strip() or None if normalised == "state" else None
        # PROMPT 13, REQUIREMENT 2: A STATE SCOPE KEEPS ITS COUNTRY.
        #
        # This line used to keep the country only in COUNTRY mode, so a STATE
        # scope stored the country as NULL - and `location_routes._scope()`
        # returns that NULL straight to `within_scope`, which then compared the
        # state and NOTHING else. The stored country was also the answer to
        # requirement 2's ambiguity ("Kerala" exists in more than one country),
        # so discarding it threw away the very evidence that made the stored
        # state unambiguous.
        #
        # Keeping it is safe in the other direction: a stale country left by an
        # earlier STATE change cannot survive, because the country is rewritten
        # from the resolver's own answer on every STATE save.
        self.location_scope_country = (country or "").strip() or None if normalised in ("state", "country") else None
        self.location_scope_updated_at = utcnow()
        self.location_scope_updated_by = (actor or "").strip() or None

    def get_reset_code(self) -> dict:
        return _safe_json(self.reset_code, {})

    def set_reset_code(self, value: dict) -> None:
        self.reset_code = json.dumps(value or {})

    def get_unlock_confirmation(self) -> dict:
        return _safe_json(self.unlock_confirmation, {})

    def set_unlock_confirmation(self, value: dict) -> None:
        self.unlock_confirmation = json.dumps(value or {})

    # --- PROMPT 8: the login approval workflow -------------------------------
    # The address login approval requests are sent to, stored rather than read
    # from the environment for the same reason the console identity is: the
    # workflow can be pointed at a different mailbox from inside the console, and
    # an env value is immutable at runtime. NULL means "use the configured
    # default", so an existing deployment is unaffected.
    def get_admin_approval_email(self) -> str | None:
        value = (self.admin_approval_email or "").strip()
        return value or None

    def set_admin_approval_email(self, value: str | None) -> None:
        self.admin_approval_email = (str(value).strip() if value else None) or None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<AdminSettings id={self.id} password_set={bool(self.password_hash)}>"


def _safe_json(raw: str | None, default):
    """Parse a JSON column, falling back to `default` on anything unreadable."""
    if not raw:
        return default
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return default
    return parsed if isinstance(parsed, type(default)) else default
