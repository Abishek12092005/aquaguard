"""Reports to Mail — attachments built from the OWNER'S OWN reports, sent by email.

THE OWNERSHIP RULE, AND WHY IT LIVES HERE. The frontend names a report by id,
but an id from the network is only ever a HINT: nothing stops a crafted request
from quoting another account's prediction id. Every lookup in this module is
therefore filtered by `user_id == current_user_id()` IN SQL, so a report that
exists but belongs to someone else is indistinguishable from a report that does
not exist at all (both are 404). Ownership is never taken from the request body.

THE OPTIONS, AND WHAT EACH ONE ATTACHES.

    REPORT_PDF   one PDF: the prediction whose id was given (owned, or 404)
    REPORT_CSV   one CSV: the prediction whose id was given (owned, or 404)
    ALL_PDF      one PDF: every prediction the account owns
    ALL_CSV      one CSV: every prediction the account owns

"ALL" is scoped to the authenticated account by the same SQL predicate, not by
what the page happens to have loaded — so the attachment cannot include
anything the account does not own, and cannot miss rows the page never fetched.

THE PDFs. Built with reportlab to the same CONTENT the on-screen report shows —
masthead, verdict, the five parameters against their reference bands, and the
confidence — because an emailed report that disagreed with the page would be
worse than no email. Reportlab rather than a headless browser: a real PDF from
~40 lines of layout code, no browser dependency at send time.

THE CSVs. The same five parameters, verdict, confidence and location fields the
page's CSV export carries.

SENDING, AND WHAT "SUCCESS" MEANS. `mail_service.send_email` is the one transport
in this application, reused unchanged: the attachment is added to the message it
builds, and success is reported ONLY when the provider accepted the message
(`MailResult.status == "sent"`). A generation failure raises before any send is
attempted; a send failure returns the transport's own error — neither is
converted into a success.
"""

from __future__ import annotations

import csv
import io
import logging
import math
from datetime import datetime, timezone
from typing import Any
from xml.sax.saxutils import escape

from sqlalchemy import select

from app.extensions import db
from app.models import WaterPrediction
from app.utils.errors import ValidationError, NotFoundError
from app.utils.validators import validate_email
from app.utils.display_time import format_ist, format_ist_time, format_ist_csv

logger = logging.getLogger(__name__)

# The option codes the API accepts. Upper-case in the contract, exactly as the
# brief words them; anything else is a 422 before any lookup runs.
OPTIONS = ("REPORT_PDF", "REPORT_CSV", "ALL_PDF", "ALL_CSV")

# THE CEILING ON AN "ALL" EXPORT. The ALL options build one page (PDF) or one row
# (CSV) per reading, entirely in memory, before the message is handed to SMTP.
# Without a bound, an account with a long history turns one request into an
# arbitrarily large document, so the newest N are sent and the response states
# plainly how many were included. 250 is roughly a 70-page PDF - already far more
# than is useful in an email, while still covering every realistic account.
MAX_REPORTS_PER_EXPORT = 250

# The five model parameters, in the order the on-screen report prints them.
PARAMETER_ORDER = ("ph", "turbidity", "tds", "temperature", "dissolved_oxygen")

PARAMETER_LABELS = {
    "ph": "pH",
    "turbidity": "Turbidity",
    "tds": "TDS",
    "temperature": "Temperature",
    "dissolved_oxygen": "Dissolved Oxygen",
}

PARAMETER_UNITS = {
    "ph": "pH",
    "turbidity": "NTU",
    "tds": "mg/L",
    "temperature": "°C",
    "dissolved_oxygen": "mg/L",
}

# The printed reference bands, the same ones the page shows beside each value.
NORMAL_LEVELS = {
    "ph": (6.5, 8.5),
    "turbidity": (0.0, 5.0),
    "tds": (50.0, 600.0),
    "temperature": (10.0, 35.0),
    "dissolved_oxygen": (5.0, 10.0),
}


def _current_user_id() -> int:
    """The account the mailed reports are drawn from.

    Delegates to the one shared rule in `app.services.identity`: a request with a
    valid token acts as that account, and anything else acts as the shared
    visitor. Ownership is still verified in SQL against this id, so a report id
    supplied by the client is only ever a pointer.
    """
    from app.services.identity import current_user_id

    return current_user_id()


def _owned_prediction(prediction_id: int, user_id: int) -> WaterPrediction:
    """The prediction with this id, ONLY IF the account owns it.

    A missing id and someone else's id are the same answer — 404 — because
    telling them apart would tell an attacker which ids exist.
    """
    prediction = db.session.execute(
        select(WaterPrediction).where(
            WaterPrediction.id == prediction_id,
            WaterPrediction.user_id == user_id,
        )
    ).scalar_one_or_none()
    if prediction is None:
        raise NotFoundError("Report not found")
    return prediction


def _owned_predictions(user_id: int) -> list[WaterPrediction]:
    """Every prediction the account owns, newest first."""
    return list(
        db.session.execute(
            select(WaterPrediction)
            .where(WaterPrediction.user_id == user_id)
            .order_by(WaterPrediction.created_at.desc(), WaterPrediction.id.desc())
        ).scalars()
    )


def _report_id(prediction: WaterPrediction) -> str:
    """The same AGR-YYYYMMDD-NNNNN id the page and the admin console derive."""
    created = prediction.created_at or datetime(1970, 1, 1)
    stamp = created.strftime("%Y%m%d")
    return f"AGR-{stamp}-{str(prediction.id).zfill(5)}"


def _classification(value: float, low: float, high: float) -> str:
    """Where a reading sits in its reference band, as the page words it."""
    if value is None:
        return "unknown"
    if value < low:
        return "below normal"
    if value > high:
        return "above normal"
    return "in range"


def _safe_cell(value: Any) -> str:
    """One CSV cell, defused against FORMULA INJECTION.

    Excel and Google Sheets treat a cell whose text begins with `=`, `+`, `-`
    or `@` as a FORMULA and evaluate it when the file is opened. A location name
    of `=HYPERLINK("http://evil","click")` would therefore become a live link
    in the reader's spreadsheet, and `=cmd|...` variants have historically run
    commands. These values reach the CSV from the GEOCODER and from place names
    typed into the search box, so they are outside anything this application
    validated - quoting them in the CSV syntax does NOT help, because the
    dangerous character is the first thing in the cell, not a delimiter.

    The standard defence is to prefix the value with a single quote, which
    Excel reads as "this cell is text" and strips on display. The user still
    sees the real name; it just cannot execute.

    Only the leading character is at issue, so the check is deliberately
    narrow: a value that merely CONTAINS one of these characters somewhere in
    the middle ("A & B", "Zone-3") is left exactly as it was.
    """
    text = "" if value is None else str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def _water_source_text(prediction: WaterPrediction) -> str:
    """One honest sentence about a prediction's water source.

    Mirrors the wording the web UI uses, so a PDF and the screen it was exported
    from cannot disagree:

      * an identified source â†’ the type
      * an identified source plus a nearby one â†’ "type (nearest: name — x km)"
      * a nearby source only â†’ "Nearby water sources: name — x km"
      * nothing â†’ "Water source information unavailable"

    Every branch reads a stored column. No type is inferred, defaulted or
    invented when the evidence is absent.
    """
    source_type = (prediction.water_source_type or "").strip()
    nearby_name = (prediction.nearby_water_source or "").strip()
    distance = prediction.nearby_water_source_distance

    nearby = nearby_name
    if nearby_name and distance is not None:
        nearby = f"{nearby_name} — {distance:g} km"

    if source_type:
        return f"{source_type} (nearest: {nearby})" if nearby else source_type
    if nearby:
        return f"Nearby water sources: {nearby}"
    return "Water source information unavailable"


def _confidence_percent(value: Any) -> str:
    """Confidence as a percentage string, or blank when it is not a number.

    `confidence` is a probability, so it belongs in 0..1 and is rendered as
    0.0-100.0. A value outside that range is not silently multiplied into a
    nonsense figure like "140.0%" or "-20.0%" - the model cannot be 140%
    confident, and a report claiming it is worse than one admitting the value
    is unusable. Anything outside 0..1 renders as the same "unknown" the rest of
    the report uses for a missing reading, rather than being invented into a
    plausible number.
    """
    if value is None:
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if not 0.0 <= number <= 1.0:
        return ""
    return f"{number * 100:.1f}"


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

CSV_HEADERS = [
    "Report ID",
    "Prediction ID",
    "Date",
    "Time",
    "pH (pH)",
    "Turbidity (NTU)",
    "TDS (mg/L)",
    "Temperature (°C)",
    "Dissolved Oxygen (mg/L)",
    "Verdict",
    "Risk",
    "Confidence (%)",
    "Location",
    "Area",
    "City",
    "Pincode",
    "District",
    "State",
    "Country",
    "Water Source",
    # PROMPT 4: the nearest real source and its real distance, so a reading
    # whose exact point has no mapped source still says WHICH source the
    # identification came from and HOW FAR away it is. Both are read straight
    # off the stored prediction - nothing is derived or guessed here.
    "Nearest Source",
    "Nearest Source Distance (km)",
]


# The plain-word risk each verdict maps to, matching the screens: a reading of
# the model's own output, never a second score.
RISK_WORDS = {"SAFE": "Low", "MODERATE": "Medium", "UNSAFE": "High"}

# The next steps attached to each verdict, matching the wording the Reports page
# and its PDF use. Keyed by the UPPER-CASE verdict so a stored row cannot miss
# its own advice, and static text rather than a second opinion from anywhere.
VERDICT_STEPS = {
    "SAFE": [
        "This sample is within the healthy band for every parameter measured. The water is treated as potable at the point of testing.",
        "Store it in a clean, covered container and use it within 24 hours of sampling.",
        "Retest on your normal schedule. A single clean reading describes one moment, not the supply.",
    ],
    "MODERATE": [
        "At least one reading sits between the clean and unsafe bands, so the result is a flag rather than a pass.",
        "Do not drink this water untreated. Boil it for at least one minute, or use bottled water, until a retest comes back clean.",
        "Find and correct the parameter marked Below/Above normal in the table above, then sample again from the same tap.",
    ],
    "UNSAFE": [
        "Treat this water as contaminated. Do not drink it, cook with it, or use it to brush teeth while untreated.",
        "Boil for at least one minute, or use bottled water, and keep the source isolated until it is cleared.",
        "Retest from the same point. If the second result is also unsafe, have a laboratory analysis done before using the supply again.",
    ],
}

# The plain-language meaning of each measured parameter, so the sheet explains
# its own numbers. Text only, keyed to the same five parameters everywhere else.
PARAMETER_MEANINGS = {
    "ph": "Below 6.5 is corrosive; above 8.5 tastes flat and scales pipework.",
    "turbidity": "Cloudiness shelters bacteria from disinfection. The usual target is under 5 NTU.",
    "tds": "Dissolved salts and minerals. Above 500 mg/L the taste degrades and the source is suspect.",
    "temperature": "Warm water holds less oxygen and grows bacteria faster.",
    "dissolved_oxygen": "Low readings point to stagnant or heavily loaded water.",
}

# General instructions that apply to every report, printed under the steps.
GENERAL_NOTES = [
    "Sample from the same tap or source each time, and record the time of sampling. Readings taken at different points are not comparable.",
    "Clean the container before sampling and let the water run briefly first, so the sample is what the supply is actually delivering.",
    "The normal ranges printed here are the standard drinking-water reference bands, shown for comparison only. The verdict itself comes from the model, not from these bands.",
    "Confidence is the model's strength of opinion about this sample. A low figure means some parameters were left out - not that the water is uncertain.",
    "This report is a screening result from five measured parameters and a statistical model. It is not a laboratory analysis and must not be treated as one.",
]


def _csv_row(prediction: WaterPrediction) -> list[str]:
    """One CSV row, every free-text cell passed through `_safe_cell`.

    Only the free-text columns need it. The numeric ones are already rendered
    with `:g` from a real float (so a negative TDS reads "-5", a number, not a
    formula), and the date and the two ids are generated here and cannot start
    with a formula character. Everything that came from a geocoder or from a
    name a person typed is escaped.
    """
    created = prediction.created_at
    verdict = (prediction.prediction or "").upper()
    return [
        _report_id(prediction),
        f"PRED-{str(prediction.id).zfill(5)}",
        # IST, matching the screens: the emailed CSV row must read the same
        # clock the History table shows, not raw UTC. Date and time are two
        # slices of the SAME stored instant - never regenerated.
        format_ist_csv(created)[:10],
        format_ist_csv(created)[11:19],
        "" if prediction.ph is None else f"{prediction.ph:g}",
        "" if prediction.turbidity is None else f"{prediction.turbidity:g}",
        "" if prediction.tds is None else f"{prediction.tds:g}",
        "" if prediction.temperature is None else f"{prediction.temperature:g}",
        "" if prediction.dissolved_oxygen is None else f"{prediction.dissolved_oxygen:g}",
        verdict,
        RISK_WORDS.get(verdict, "Not Available"),
        _confidence_percent(prediction.confidence),
        _safe_cell(prediction.location_name),
        _safe_cell(prediction.location_area),
        _safe_cell(prediction.location_city),
        _safe_cell(prediction.location_pincode),
        _safe_cell(prediction.location_district),
        _safe_cell(prediction.location_state),
        _safe_cell(prediction.location_country),
        _safe_cell(prediction.water_source_type),
        _safe_cell(prediction.nearby_water_source),
        "" if prediction.nearby_water_source_distance is None
        else f"{prediction.nearby_water_source_distance:g}",
    ]


def build_csv(predictions: list[WaterPrediction]) -> bytes:
    """One CSV document from the given rows (real data only, in the given order)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_HEADERS)
    for prediction in predictions:
        writer.writerow(_csv_row(prediction))
    return buffer.getvalue().encode("utf-8-sig")


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def build_pdf(predictions: list[WaterPrediction], title: str) -> bytes:
    """One professional PDF document from the given rows.

    THIS IS THE ONLY PDF GENERATOR IN THE APPLICATION. The single-report download
    (GET /reports/pdf/<id>), the bulk download (GET /reports/pdf) and every email
    attachment (REPORT_PDF / ALL_PDF) all call THIS function with the caller's own
    rows. That is the one-generator rule: a downloaded report and an emailed one
    cannot drift because there is no second layout to drift from - same data,
    same stored timestamp, same formatting, same watermark.

    THE TIMESTAMP IS READ, NEVER RE-GENERATED. Every date and time printed here
    comes from `prediction.created_at`, the instant written once when the
    prediction was created, rendered in India Standard Time by the shared
    `app.utils.display_time` helpers - the same wording the History table and the
    on-screen Reports sheet use. A PDF built today still shows the prediction's
    own time, not the time the document was made.

    LAYOUT. A centred masthead with the brand mark sits above a centred summary
    block (Prediction ID, Report ID, Date, exact Time, Verdict, Risk, Confidence),
    then a centred location block, then the five measured parameters against their
    reference bands, then the next steps and notes. Tables are centred on the
    page, every heading and every value is centred within its column, margins are
    equal on both sides, and the blocks are sized so the page fills naturally
    rather than leaving a large blank band at the foot.
    """
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Flowable,
        KeepTogether,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    buffer = io.BytesIO()

    # Content geometry, shared by the masthead, the tables and the footer so the
    # three agree on where the page's edges are. Equal left and right margins are
    # what make the sheet read as balanced rather than inset on one side only.
    MARGIN = 14 * mm
    CONTENT_WIDTH = A4[0] - MARGIN * 2
    BRAND_BLUE = colors.HexColor("#0163a0")
    RULE = colors.HexColor("#cbd5e1")
    SLATE = colors.HexColor("#334155")
    INK = colors.HexColor("#0f172a")
    MUTED = colors.HexColor("#64748b")
    LABEL_BG = colors.HexColor("#f1f5f9")

    # ---------------------------------------------------------------------
    # THE WATERMARK - a subtle AquaGuard water-drop circular SEAL on every page.
    #
    # Drawn in the page callbacks so it lies UNDER the flowed content, and as
    # vector paths so it stays crisp at any zoom or print resolution. The brief
    # asks for a VISIBLE graphical watermark that is a filled SEAL, not an empty
    # outline, and that stays very light so the report text keeps full contrast.
    #
    # It is built from three parts, all in the palest brand tints:
    #   1. a filled disc with a soft rim          -> the seal body
    #   2. a hairline inner ring                  -> the seal's second circle
    #   3. a FILLED teardrop water drop           -> the AquaGuard mark itself
    # plus the words "AQUAGUARD AI" curved around the top of the seal and
    # "WATER QUALITY" around the bottom, which is what makes it read as a
    # professional stamp rather than as a random shape. A hard-coded pale colour
    # needs no renderer support for transparency, so on white paper it can only
    # ever read as a faint tint in every viewer and on paper.
    # ---------------------------------------------------------------------
    def _draw_drop(canvas, cx, cy, drop, fill, stroke, line_width):
        """A teardrop: two Bezier curves meeting at a point, FILLED."""
        canvas.setFillColor(fill)
        canvas.setStrokeColor(stroke)
        canvas.setLineWidth(line_width)
        path = canvas.beginPath()
        path.moveTo(cx, cy + drop * 0.72)
        path.curveTo(cx + drop * 0.52, cy + drop * 0.1,
                     cx + drop * 0.5, cy - drop * 0.5, cx, cy - drop * 0.55)
        path.curveTo(cx - drop * 0.5, cy - drop * 0.5,
                     cx - drop * 0.52, cy + drop * 0.1, cx, cy + drop * 0.72)
        canvas.drawPath(path, stroke=1, fill=1)

    def _watermark(canvas, doc):
        """The AquaGuard background SEAL: a filled water-drop stamp.

        A NORMAL PDF IS STATIC, so this is a professionally designed STATIC seal
        rather than anything animated - it is the watermark that any standard
        viewer can render. It is drawn in the page callback so it lies UNDER the
        flowed content, and as VECTOR geometry so it stays crisp at any zoom or
        print resolution.

        IT IS A FILLED GRAPHICAL MARK, NOT AN OUTLINE. An earlier cut filled the
        disc and the drop with tints so pale (#eef8ff / #d7edfd) that on white
        paper they were indistinguishable from the page: at normal reading
        distance the working watermark was, in practice, the two thin rings and
        so read as an EMPTY OUTLINE - exactly what the brief rules out. The fills
        here are one clear step up the brand ramp (a soft blue disc and a solid
        drop), which makes the seal a VISIBLE filled graphic at 100% zoom while
        still sitting far below body-text contrast, so the report text stays
        fully readable.

        CALIBRATION IS THE WHOLE TRICK. The first cut was so pale it vanished
        (an outline); an over-correction made the drop a big saturated shape that
        fought the parameter table. This sits between the two: the disc is a very
        light wash, the rings carry the seal's structure, and the drop is filled
        but small - at 100% the report text keeps full contrast, while the seal
        is unmistakably a filled water-drop stamp rather than a bare outline.

        Structure, all in the brand blues:
          1. a filled disc + a defined outer ring      -> the seal body
          2. two inner rings and a dotted outer ring    -> the seal's second circle
          3. a FILLED teardrop water drop               -> the AquaGuard mark
          4. curved "AQUAGUARD AI" / "WATER QUALITY"     -> the seal lettering
             with two small star separators
        A hard-coded pale colour needs no renderer support for transparency, so
        on white paper it can only ever read as a faint tint in every viewer and
        on paper.
        """
        width, height = A4
        cx, cy = width / 2.0, height / 2.0
        # 132mm diameter: a page-scale background seal that clearly reads as a
        # stamp in the middle of the sheet while staying well inside the margins
        # (14mm each side) so it never collides with the body content edges.
        r = 66 * mm
        canvas.saveState()

        # 1. Seal body: the lightest blue wash, filled, with a soft rim. The wash
        #    is deliberately paler than the drop so the drop stays the focal mark.
        canvas.setFillColor(colors.HexColor("#f2faff"))
        canvas.setStrokeColor(colors.HexColor("#bcdff8"))
        canvas.setLineWidth(1.4)
        canvas.circle(cx, cy, r, stroke=1, fill=1)

        # 2. The inner rings that make it read as a proper seal: a hairline ring,
        #    a second finer ring, and a dotted outer ring just inside the rim.
        canvas.setStrokeColor(colors.HexColor("#c3e3fa"))
        canvas.setLineWidth(0.9)
        canvas.circle(cx, cy, r - 4.5 * mm, stroke=1, fill=0)
        canvas.setStrokeColor(colors.HexColor("#d3ebfc"))
        canvas.setLineWidth(0.6)
        canvas.circle(cx, cy, r - 8.5 * mm, stroke=1, fill=0)
        canvas.setLineWidth(0.5)
        canvas.setDash(1, 3)
        canvas.circle(cx, cy, r - 1.8 * mm, stroke=1, fill=0)
        canvas.setDash()
        # A faint central medallion behind the drop, so the mark sits on a "field"
        # the way a real seal's device does rather than floating on the wash.
        canvas.setFillColor(colors.HexColor("#eaf6ff"))
        canvas.circle(cx, cy - 2 * mm, r * 0.5, stroke=0, fill=1)

        # 3. The water drop, FILLED so it reads as an actual drop and not as a
        #    traced outline. Kept modest in size: it is the seal's device, not a
        #    page-scale shape, so the parameter table over it stays legible.
        _draw_drop(canvas, cx, cy - 3 * mm, r * 0.34,
                   colors.HexColor("#bfe3fb"),
                   colors.HexColor("#9bd2f4"), 0.9)
        # A pale inner highlight, so the drop reads as a rounded, glossy graphic
        # rather than a flat silhouette.
        _draw_drop(canvas, cx - r * 0.045, cy - 4 * mm, r * 0.15,
                   colors.HexColor("#e6f4ff"),
                   colors.HexColor("#e6f4ff"), 0.5)

        # 4. The curved seal lettering. Each character is placed on the ring at
        #    its own polar angle and rotated to the ring's tangent, so the word
        #    ARCS across the top and bottom instead of spiralling down a side.
        #    The span is centred on 90 deg (top) and 270 deg (bottom).
        ring = r - 9.5 * mm

        def _arc_text(text, centre_angle, spread, font, size, colour):
            canvas.setFillColor(colour)
            canvas.setFont(font, size)
            count = max(len(text) - 1, 1)
            start = centre_angle + spread / 2.0
            step = spread / count
            for index, char in enumerate(text):
                if char == " ":
                    continue
                angle = start - index * step
                radians = math.radians(angle)
                x = cx + ring * math.cos(radians)
                y = cy + ring * math.sin(radians)
                canvas.saveState()
                canvas.translate(x, y)
                canvas.rotate(angle - 90)
                canvas.drawCentredString(0, 0, char)
                canvas.restoreState()

        _arc_text("AQUAGUARD AI", 90.0, 112.0, "Helvetica-Bold", 14,
                  colors.HexColor("#8fc6ee"))
        _arc_text("WATER QUALITY", 270.0, -112.0, "Helvetica", 9.5,
                  colors.HexColor("#9ecdf0"))
        # Two small star separators on the horizontal axis, the way a stamp marks
        # its left and right edges and closes the lettering into a ring.
        canvas.setFillColor(colors.HexColor("#9ecdf0"))
        canvas.setFont("Helvetica-Bold", 11)
        canvas.drawCentredString(cx - ring, cy, "\u2726")
        canvas.drawCentredString(cx + ring, cy, "\u2726")

        canvas.restoreState()

    # The small brand mark at the top of the masthead: the same drop-in-circle
    # geometry, drawn in the brand blues so it reads on the white page.
    def _brand_mark(canvas, cx, cy, diameter):
        r = diameter / 2.0
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#e0f2fe"))
        canvas.setStrokeColor(colors.HexColor("#0284c7"))
        canvas.setLineWidth(diameter * 0.06)
        canvas.circle(cx, cy, r, stroke=1, fill=1)
        drop = r * 0.78
        canvas.setFillColor(colors.HexColor("#0ea5e9"))
        canvas.setStrokeColor(colors.HexColor("#0ea5e9"))
        p = canvas.beginPath()
        p.moveTo(cx, cy + drop * 0.72)
        p.curveTo(cx + drop * 0.52, cy + drop * 0.1,
                  cx + drop * 0.5, cy - drop * 0.5, cx, cy - drop * 0.55)
        p.curveTo(cx - drop * 0.5, cy - drop * 0.5,
                  cx - drop * 0.52, cy + drop * 0.1, cx, cy + drop * 0.72)
        canvas.drawPath(p, stroke=1, fill=1)
        canvas.restoreState()

    class _Mark(Flowable):
        """The brand mark as a flowable, so it can be centred above the words."""

        def __init__(self, size):
            super().__init__()
            self.size = size
            self.width = size
            self.height = size

        def draw(self):
            _brand_mark(self.canv, self.size / 2.0, self.size / 2.0, self.size)

    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=13 * mm,
        bottomMargin=13 * mm,
        title=title,
        author="AquaGuard AI",
    )

    styles = getSampleStyleSheet()
    brand = ParagraphStyle(
        "Brand", parent=styles["Title"], fontSize=17, leading=20,
        textColor=INK, alignment=TA_CENTER, spaceAfter=1,
    )
    kicker = ParagraphStyle(
        "Kicker", parent=styles["Normal"], fontSize=8.5, leading=11,
        textColor=colors.HexColor("#007cc6"), alignment=TA_CENTER, spaceAfter=2,
    )
    doc_title = ParagraphStyle(
        "DocTitle", parent=styles["Normal"], fontSize=11, leading=14,
        textColor=colors.HexColor("#1e3a60"), alignment=TA_CENTER,
        fontName="Helvetica-Bold", spaceBefore=2,
    )
    # Every label and every value is centred, so a value always sits under its
    # own heading and in the middle of its own column.
    field_label = ParagraphStyle(
        "FieldLabel", parent=styles["Normal"], fontSize=8, leading=10,
        textColor=MUTED, alignment=TA_CENTER,
    )
    field_value = ParagraphStyle(
        "FieldValue", parent=styles["Normal"], fontSize=9, leading=11,
        textColor=INK, alignment=TA_CENTER,
    )
    param_head = ParagraphStyle(
        "ParamHead", parent=styles["Normal"], fontSize=8.5, leading=11,
        textColor=colors.white, alignment=TA_CENTER, fontName="Helvetica-Bold",
    )
    param_cell = ParagraphStyle(
        "ParamCell", parent=styles["Normal"], fontSize=9, leading=11,
        textColor=INK, alignment=TA_CENTER,
    )
    summary_value = ParagraphStyle(
        "SummaryValue", parent=styles["Normal"], fontSize=10, leading=13,
        textColor=INK, alignment=TA_CENTER, fontName="Helvetica-Bold",
    )
    section = ParagraphStyle(
        "Section", parent=styles["Normal"], fontSize=10.5, leading=13,
        textColor=colors.white, alignment=TA_CENTER, fontName="Helvetica-Bold",
    )
    body = ParagraphStyle(
        "Body", parent=styles["Normal"], fontSize=8, leading=10.2,
        textColor=SLATE,
    )
    bullet = ParagraphStyle(
        "Bullet", parent=styles["Normal"], fontSize=7.2, leading=9.2,
        textColor=SLATE, leftIndent=7, bulletIndent=1,
    )
    footnote = ParagraphStyle(
        "Footnote", parent=styles["Normal"], fontSize=7.2, leading=9.4,
        textColor=MUTED, alignment=TA_CENTER,
    )

    # Reportlab's Paragraph parses its text as XML, so a value containing `&`,
    # `<` or `>` raises at build time. Every one of these strings is a value
    # from the database - a place name, a city, a water-source type - and those
    # come from the geocoder, where "R & Sons Street" and "Zone A <North>" are
    # entirely ordinary. Passing one through unescaped turns a legitimate place
    # into a 502, so all database text is escaped at the point it becomes markup.
    def field(text: Any, style: ParagraphStyle = field_value) -> Paragraph:
        return Paragraph(escape("" if text is None else str(text)), style)

    def section_bar(text: str) -> Table:
        """A full-width brand-blue bar with a centred white section title."""
        bar = Table([[Paragraph(escape(text), section)]], colWidths=[CONTENT_WIDTH])
        bar.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), BRAND_BLUE),
            ("TOPPADDING", (0, 0), (-1, -1), 2.6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.6),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]))
        return bar

    def hairline() -> Table:
        """A single hairline spanning exactly the content width."""
        line = Table([[""]], colWidths=[CONTENT_WIDTH])
        line.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (-1, -1), 0.5, RULE),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        return line

    story: list = []
    for index, prediction in enumerate(predictions):
        if index > 0:
            story.append(PageBreak())

        # --- Masthead: brand mark, wordmark, project line, document title ---
        mark_row = Table([[_Mark(9 * mm)]], colWidths=[CONTENT_WIDTH])
        mark_row.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.append(mark_row)
        story.append(Spacer(1, 1.5 * mm))
        story.append(Paragraph("AquaGuard AI", brand))
        story.append(Paragraph(
            "Water Quality Monitoring &amp; Prediction", kicker
        ))
        story.append(Paragraph("WATER QUALITY REPORT", doc_title))

        # A generated-at stamp is useful provenance. It is NOT the prediction's
        # time and is labelled as such, so it can never be mistaken for the
        # report's own timestamp (which is read from the stored row below).
        generated = format_ist(datetime.now(timezone.utc), placeholder="-")
        story.append(Paragraph(
            f"<font size=7 color='#94a3b8'>Generated {escape(generated)} IST</font>",
            footnote,
        ))
        story.append(Spacer(1, 1.5 * mm))
        story.append(hairline())
        story.append(Spacer(1, 2.5 * mm))

        verdict = (prediction.prediction or "unknown").upper()
        verdict_colour = {
            "SAFE": "#15803d",
            "MODERATE": "#b45309",
            "UNSAFE": "#b91c1c",
        }.get(verdict, "#475569")

        # THE EXACT-TIME RULE. Date and Time come from the ONE stored
        # `created_at`, rendered in IST by the shared helpers - the same wording
        # the History table and the Reports sheet use. Nothing is regenerated.
        created = prediction.created_at
        date_text = format_ist(created, placeholder="-")
        time_text = format_ist_time(created, placeholder="-")
        confidence_text = _confidence_percent(prediction.confidence)
        confidence_display = f"{confidence_text}%" if confidence_text else "-"
        risk_text = RISK_WORDS.get(verdict, "Not available")
        prediction_id_text = f"PRED-{str(prediction.id).zfill(5)}"
        report_id_text = _report_id(prediction)

        # --- Top summary: the identity of the report, centred and boxed ---
        story.append(section_bar("REPORT SUMMARY"))
        story.append(Spacer(1, 2 * mm))
        summary_rows = [
            [Paragraph("Prediction ID", field_label),
             Paragraph("Date", field_label),
             Paragraph("Exact Time", field_label),
             Paragraph("Verdict", field_label)],
            [Paragraph(escape(prediction_id_text), summary_value),
             Paragraph(escape(date_text), summary_value),
             Paragraph(escape(time_text), summary_value),
             Paragraph(
                 f"<font color='{verdict_colour}'>{escape(verdict)}</font>",
                 summary_value,
             )],
        ]
        summary_table = Table(summary_rows, colWidths=[CONTENT_WIDTH / 4.0] * 4)
        summary_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), LABEL_BG),
            ("GRID", (0, 0), (-1, -1), 0.5, RULE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(summary_table)
        story.append(Spacer(1, 2.5 * mm))

        # --- Location and source block, centred two-column grid ---
        story.append(section_bar("LOCATION & WATER SOURCE"))
        story.append(Spacer(1, 2 * mm))
        loc_rows = [
            [Paragraph("Report ID", field_label),
             Paragraph(escape(report_id_text), field_value),
             Paragraph("Risk", field_label),
             Paragraph(escape(risk_text), field_value)],
            [Paragraph("Location", field_label),
             field(prediction.location_name or "Not recorded"),
             Paragraph("Confidence", field_label),
             Paragraph(escape(confidence_display), field_value)],
            [Paragraph("Area", field_label),
             field(prediction.location_area or "Not available"),
             Paragraph("City / Town", field_label),
             field(prediction.location_city or "Not available")],
            [Paragraph("District", field_label),
             field(prediction.location_district or "Not available"),
             Paragraph("State", field_label),
             field(prediction.location_state or "Not available")],
            [Paragraph("Country", field_label),
             field(prediction.location_country or "Not available"),
             Paragraph("Pincode", field_label),
             field(str(prediction.location_pincode) if prediction.location_pincode else "Not available")],
            [Paragraph("Water Source", field_label),
             field(_water_source_text(prediction)),
             Paragraph("Model version", field_label),
             field(getattr(prediction, "model_version", None) or "Not available")],
        ]
        loc_table = Table(
            loc_rows,
            colWidths=[CONTENT_WIDTH * 0.2, CONTENT_WIDTH * 0.3,
                       CONTENT_WIDTH * 0.2, CONTENT_WIDTH * 0.3],
        )
        loc_table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, RULE),
            ("BACKGROUND", (0, 0), (0, -1), LABEL_BG),
            ("BACKGROUND", (2, 0), (2, -1), LABEL_BG),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("TOPPADDING", (0, 0), (-1, -1), 2.8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.8),
        ]))
        story.append(loc_table)
        story.append(Spacer(1, 2.5 * mm))

        # --- The five measured parameters, centred heading and values ---
        story.append(section_bar("MEASURED PARAMETERS"))
        story.append(Spacer(1, 2 * mm))
        parameter_rows = [[
            Paragraph("Parameter", param_head),
            Paragraph("Measured", param_head),
            Paragraph("Normal range", param_head),
            Paragraph("Status", param_head),
        ]]
        for key in PARAMETER_ORDER:
            value = getattr(prediction, key, None)
            low, high = NORMAL_LEVELS[key]
            measured = "-" if value is None else f"{float(value):g} {PARAMETER_UNITS[key]}"
            parameter_rows.append([
                Paragraph(escape(PARAMETER_LABELS[key]), param_cell),
                Paragraph(escape(measured), param_cell),
                Paragraph(
                    escape(f"{low:g} - {high:g} {PARAMETER_UNITS[key]}"), param_cell
                ),
                Paragraph(escape(_classification(value, low, high).title()), param_cell),
            ])
        parameter_table = Table(
            parameter_rows,
            colWidths=[CONTENT_WIDTH * 0.28, CONTENT_WIDTH * 0.24,
                       CONTENT_WIDTH * 0.26, CONTENT_WIDTH * 0.22],
        )
        parameter_table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, RULE),
            ("BACKGROUND", (0, 0), (-1, 0), BRAND_BLUE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            # CENTERED: every heading and every value sits in the middle of its
            # own column, so the table reads as an even grid rather than as
            # left-leaning text against centred headings.
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(parameter_table)
        story.append(Spacer(1, 2.5 * mm))

        # --- Steps to take, keyed to the verdict ---
        steps = (
            VERDICT_STEPS.get(verdict)
            or VERDICT_STEPS.get((prediction.prediction or "").lower())
            or VERDICT_STEPS["SAFE"]
        )
        steps_block = [section_bar("WHAT TO DO NEXT"), Spacer(1, 1.5 * mm)]
        for step_index, line in enumerate(steps, start=1):
            steps_block.append(
                Paragraph(f"<b>{step_index}.</b>&nbsp; {escape(line)}", body)
            )
            steps_block.append(Spacer(1, 1 * mm))
        story.append(KeepTogether(steps_block))
        story.append(Spacer(1, 2 * mm))

        # --- What each parameter means ---
        meaning_block = [section_bar("WHAT EACH PARAMETER MEANS"), Spacer(1, 1.5 * mm)]
        for key in PARAMETER_ORDER:
            label = PARAMETER_LABELS[key]
            unit = PARAMETER_UNITS[key]
            note = PARAMETER_MEANINGS.get(key, "")
            meaning_block.append(
                Paragraph(
                    f"<b>{escape(label)} ({escape(unit)}):</b>&nbsp; {escape(note)}",
                    body,
                )
            )
            meaning_block.append(Spacer(1, 0.8 * mm))
        story.append(KeepTogether(meaning_block))
        story.append(Spacer(1, 2 * mm))

        # --- Reading and sampling notes ---
        notes_block = [section_bar("READING & SAMPLING NOTES"), Spacer(1, 1.5 * mm)]
        for line in GENERAL_NOTES:
            notes_block.append(Paragraph(f"\u2022&nbsp; {escape(line)}", bullet))
            notes_block.append(Spacer(1, 0.8 * mm))
        story.append(KeepTogether(notes_block))
        story.append(Spacer(1, 1.5 * mm))

        # --- Disclaimer: a formal closing notice, set off by a hairline ---
        story.append(Spacer(1, 1 * mm))
        story.append(hairline())
        story.append(Spacer(1, 1 * mm))
        story.append(Paragraph(
            "<i>Disclaimer: This report is generated by the AquaGuard AI screening "
            "model from five measured parameters. It is not certified laboratory "
            "testing and must not be used as the sole basis for decisions about "
            "drinking-water safety.</i>",
            footnote,
        ))

    # The footer is drawn per page in the same pass as the watermark, so every
    # page - including pages a long table flowed onto - carries one identifying
    # line. Both are drawn AFTER the content has been laid out, so the watermark
    # can never sit on top of the text.
    def _page_decorations(canvas, doc):
        _watermark(canvas, doc)
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawCentredString(
            A4[0] / 2.0, 9 * mm,
            "AquaGuard AI - Water Quality Report  |  "
            f"page {doc.page}  |  Times in India Standard Time (IST)",
        )
        canvas.restoreState()

    document.build(story, onFirstPage=_page_decorations, onLaterPages=_page_decorations)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# The API operation
# ---------------------------------------------------------------------------

def send_reports_mail(payload: dict) -> dict[str, Any]:
    """The whole Reports-to-Mail operation: validate, verify, build, send.

    Returns a plain dict the route serialises, and raises AquaGuardError
    subclasses for everything the caller must fix (bad body, unknown option,
    unowned report). A send failure is RETURNED, not raised — the transport's
    own verdict is the honest one, and `ok` is true only for a provider-
    accepted message.
    """
    recipient = validate_email((payload or {}).get("email"))
    option = str((payload or {}).get("option") or "").strip().upper()
    if option not in OPTIONS:
        raise ValidationError(
            f"option must be one of {', '.join(OPTIONS)}",
            {"option": f"Must be one of {', '.join(OPTIONS)}"},
        )

    user_id = _current_user_id()

    # --- Resolve the rows, ownership-checked IN SQL -------------------------
    if option in ("REPORT_PDF", "REPORT_CSV"):
        raw_id = (payload or {}).get("prediction_id") or (payload or {}).get("report_id")
        if raw_id is None or str(raw_id).strip() == "":
            raise ValidationError(
                "prediction_id is required for single-report options",
                {"prediction_id": "Required for REPORT_PDF and REPORT_CSV"},
            )
        try:
            prediction_id = int(str(raw_id).strip())
        except (TypeError, ValueError):
            raise ValidationError(
                "prediction_id must be the numeric report id",
                {"prediction_id": "Must be a number"},
            ) from None
        predictions = [_owned_prediction(prediction_id, user_id)]
        scope = f"report {_report_id(predictions[0])}"
    else:
        predictions = _owned_predictions(user_id)
        if not predictions:
            raise NotFoundError("You have no reports to send yet")
        scope = f"all {len(predictions)} of your reports"

    # --- Build the attachment BEFORE any send is attempted ------------------
    # EVERYTHING AFTER THIS POINT IS UNBOUNDED WORK. ALL_PDF renders one full
    # page per reading and ALL_CSV one row per reading, so an account with
    # thousands of readings would build a multi-megabyte document in memory,
    # base64 it for SMTP, and hold all of it on the request - a cheap way to make
    # this endpoint hang or exhaust memory, driven purely by how many rows the
    # account happens to have accumulated.
    #
    # The cap is applied to the ROWS, and it is reported rather than silent: the
    # response says how many were included, and a truncated export says so in the
    # subject line, because an attachment quietly missing 400 reports and one
    # that plainly states it carries the newest 250 are very different things for
    # someone relying on it. The single-report options are never affected - they
    # carry exactly one row by construction.
    if len(predictions) > MAX_REPORTS_PER_EXPORT:
        logger.info(
            "Reports to Mail: capping %s from %d to %d rows for user=%s",
            option, len(predictions), MAX_REPORTS_PER_EXPORT, user_id,
        )
        predictions = predictions[:MAX_REPORTS_PER_EXPORT]
        scope = f"the {MAX_REPORTS_PER_EXPORT} most recent of your reports " \
                f"(of {len(predictions)} included)"

    if option in ("REPORT_PDF", "ALL_PDF"):
        title = (
            "Single reading report"
            if option == "REPORT_PDF"
            else f"{len(predictions)} reading{'s' if len(predictions) != 1 else ''}"
        )
        attachment_bytes = build_pdf(predictions, title)
        attachment_name = (
            f"aquaguard-report-{_report_id(predictions[0])}"
            if option == "REPORT_PDF"
            else f"aquaguard-reports-all-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
        ) + ".pdf"
        mime = "application/pdf"
    else:
        attachment_bytes = build_csv(predictions)
        attachment_name = (
            f"aquaguard-report-{_report_id(predictions[0])}"
            if option == "REPORT_CSV"
            else f"aquaguard-reports-all-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
        ) + ".csv"
        mime = "text/csv"

    # --- The message, from the shared mail templates ------------------------
    from app.services.mail_service import report_mail_message, send_email

    subject, text_body, html_body = report_mail_message(
        recipient=recipient, option=option, scope=scope,
        attachment_name=attachment_name, size=len(attachment_bytes),
    )

    result = send_email(
        to=recipient,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        attachments=[(attachment_name, attachment_bytes, mime)],
    )

    # --- PROMPT 12: record the request in the append-only audit trail --------
    # Recorded for EVERY real attempt, sent or failed — the transport's own
    # status is stored verbatim. Never raised: an audit failure must not turn a
    # successful send into an error for the user.
    _record_audit(
        recipient=recipient,
        option=option,
        status=result.status,
        reports_included=len(predictions),
        user_id=user_id,
        payload=payload or {},
    )

    logger.info(
        "Reports to Mail: option=%s user=%s recipient=%s -> %s (%s, %d bytes)",
        option, user_id, recipient, result.status, attachment_name, len(attachment_bytes),
    )

    return {
        "status": result.status,
        "detail": result.detail,
        "recipient": result.recipient,
        "option": option,
        "reports_included": len(predictions),
        "attachment_name": attachment_name,
        "attachment_size": len(attachment_bytes),
    }


# ---------------------------------------------------------------------------
# PROMPT 12: the audit trail writer
# ---------------------------------------------------------------------------

# The only location source the audit accepts. Anything else is a location the
# system did not legitimately obtain, and is dropped rather than stored.
VALID_LOCATION_SOURCES = ("browser",)


def _record_audit(
    *,
    recipient: str,
    option: str,
    status: str,
    reports_included: int,
    user_id: int,
    payload: dict,
) -> None:
    """Append one audit row for a real report-mail request. Never raises.

    The location fields are filled ONLY from an explicitly supplied,
    consented, place-granularity location in the request. There is no fallback:
    when the requester's browser did not provide one, the row stores nothing and
    the admin view honestly says "Location unavailable".
    """
    try:
        from flask import has_app_context

        from app.models import ReportEmailAudit, User
        from app.models.mixins import utcnow

        requester_name = None
        if user_id is not None and has_app_context():
            user = db.session.get(User, user_id)
            if user is not None:
                requester_name = user.name

        # --- Location: only what the client explicitly and legitimately sent.
        loc = payload.get("device_location") or {}
        loc_fields = {
            "location_name": None,
            "location_city": None,
            "location_state": None,
            "location_country": None,
            "location_pincode": None,
            "location_source": None,
        }
        if isinstance(loc, dict) and loc.get("source") in VALID_LOCATION_SOURCES:
            for key in ("name", "city", "state", "country", "pincode"):
                value = loc.get(key)
                if isinstance(value, str) and value.strip():
                    loc_fields[f"location_{key}"] = value.strip()[:190]
            # Source is stored only when at least one real place field came
            # with it — a bare "browser" label with no place would be a claim
            # the row cannot back up.
            if any(loc_fields[k] for k in loc_fields if k != "location_source"):
                loc_fields["location_source"] = "browser"

        device = payload.get("device_label")
        row = ReportEmailAudit(
            recipient_email=recipient,
            report_option=option,
            delivery_status=status,
            reports_included=reports_included,
            user_id=user_id,
            requester_name=requester_name,
            admin_username=(payload.get("admin_username") or None),
            device_label=(device[:80] if isinstance(device, str) and device.strip() else None),
            created_at=utcnow(),
            **loc_fields,
        )
        db.session.add(row)
        db.session.commit()
    except Exception:  # noqa: BLE001 - audit must not break the user's send
        db.session.rollback()
        logger.exception("Report-mail audit row could not be recorded")
