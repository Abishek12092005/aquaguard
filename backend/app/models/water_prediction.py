"""Water quality prediction model.

Matches the `water_predictions` table in database/schema.sql exactly: six
measured parameters plus the model verdict and confidence.
"""

from app.constants import FEATURE_NAMES
from app.extensions import db
from app.models.mixins import SerializableMixin, TimestampMixin


class WaterPrediction(TimestampMixin, SerializableMixin, db.Model):
    __tablename__ = "water_predictions"

    # BigInteger to match the schema; the SQLite variant keeps tests runnable,
    # since SQLite only auto-increments an INTEGER PRIMARY KEY.
    id = db.Column(
        db.BigInteger().with_variant(db.Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id = db.Column(
        db.BigInteger().with_variant(db.Integer, "sqlite"),
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # --- Measured parameters (precision mirrors the schema) ----------------
    ph = db.Column(db.Numeric(4, 2), nullable=False)
    turbidity = db.Column(db.Numeric(8, 2), nullable=False)
    tds = db.Column(db.Numeric(12, 2), nullable=False)
    temperature = db.Column(db.Numeric(5, 2), nullable=False)
    dissolved_oxygen = db.Column(db.Numeric(6, 2), nullable=False)

    # --- Model output ------------------------------------------------------
    prediction = db.Column(db.String(20), nullable=False, index=True)  # safe|unsafe|moderate
    confidence = db.Column(db.Numeric(5, 4), nullable=False)

    # --- Where the sample came from ----------------------------------------
    # Free-text label of the place the user chose on the Location page (a place
    # name, a famous landmark, or "place, pincode"). Nullable: existing rows and
    # predictions submitted without a location must keep working.
    location_name = db.Column(db.String(190), nullable=True)
    # Structured parts of the same choice, so history can be grouped and the
    # state/country scope checked without parsing the free-text label.
    location_city = db.Column(db.String(120), nullable=True)
    # The area/locality within the city, and the district, as the brief's
    # History/PDF field list names them. Nullable like every other location
    # part: a prediction submitted without them keeps working.
    location_area = db.Column(db.String(120), nullable=True)
    location_district = db.Column(db.String(120), nullable=True)
    location_state = db.Column(db.String(120), nullable=True)
    location_country = db.Column(db.String(120), nullable=True)
    location_pincode = db.Column(db.String(20), nullable=True)
    location_lat = db.Column(db.Numeric(9, 6), nullable=True)
    location_lng = db.Column(db.Numeric(9, 6), nullable=True)
    # What the Location service identified for the place: the dominant water
    # source type ("river water", "ground water", ...) and the closest named
    # source with its distance. Stored so reports keep the identification even
    # after the location dataset changes.
    water_source_type = db.Column(db.String(60), nullable=True)
    nearby_water_source = db.Column(db.String(190), nullable=True)
    nearby_water_source_distance = db.Column(db.Numeric(7, 2), nullable=True)
    # PROMPT 1, E.9: WHERE THE FIVE READINGS CAME FROM, kept with the record so
    # a prediction stored as "Dataset-Based Estimate" can never later be read
    # back as if it had been measured at this location. The value is one of the
    # provenance codes the location context service already defines - measured,
    # nearby_source, historical, dataset_based, estimated,
    # user_input_required - or "user" when the user typed all five readings
    # themselves. Null for a prediction submitted without location context.
    # Bounded like the text fields above so an over-long value is clamped at the
    # service layer rather than failing the commit.
    param_provenance = db.Column(db.String(40), nullable=True)

    # TimestampMixin adds `updated_at` as a real column, but the schema has
    # only `created_at`. Overriding it with a plain property keeps the mapped
    # column out of every query, so the ORM never asks MySQL for a column that
    # does not exist (which fails with "Unknown column").
    @property
    def updated_at(self):
        return self.created_at

    # --- Relationships ---
    user = db.relationship("User", back_populates="predictions")
    alerts = db.relationship(
        "Alert", back_populates="prediction", passive_deletes=True, lazy="dynamic"
    )

    _serializable_fields = (
        "id", "user_id", *FEATURE_NAMES, "prediction", "confidence",
        "location_name", "location_area", "location_city", "location_district",
        "location_state", "location_country",
        "location_pincode", "location_lat", "location_lng",
        "water_source_type", "nearby_water_source", "nearby_water_source_distance",
        "param_provenance",
    )
    _serializable_datetime_fields = ("created_at",)

    def features(self) -> dict:
        """Return the six measured parameters as floats.

        The hand-off point to the ML layer: models never reach the predictor,
        a plain dict does.
        """
        return {name: float(getattr(self, name)) for name in FEATURE_NAMES}

    def place_dict(self) -> dict:
        """The sample's location as a PLACE, with the exact coordinates removed.

        This is the privacy boundary. A privileged reader (the admin console)
        needs to know WHERE a prediction came from at the level of a place - the
        name, city, state, country and pincode, and the water source - so results
        can be grouped and reviewed. The EXACT coordinates are the user's precise
        position and are deliberately left out: a pin identifies a home, a place
        name does not.

        The user's own endpoints never use this; they return `to_dict()`, which
        keeps the coordinates for the account that owns them.
        """
        return {
            "location_name": self.location_name,
            "location_area": self.location_area,
            "location_city": self.location_city,
            "location_district": self.location_district,
            "location_state": self.location_state,
            "location_country": self.location_country,
            "location_pincode": self.location_pincode,
            "water_source_type": self.water_source_type,
            "nearby_water_source": self.nearby_water_source,
            "nearby_water_source_distance": self.nearby_water_source_distance,
            "param_provenance": self.param_provenance,
        }

    @property
    def is_safe(self) -> bool:
        return self.prediction == "safe"

    def __repr__(self) -> str:  # pragma: no cover
        return f"<WaterPrediction id={self.id} verdict={self.prediction} conf={self.confidence}>"
