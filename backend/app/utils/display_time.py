"""One timestamp formatter for every SURFACE the user reads.

THE RULE THIS EXISTS FOR. A prediction is made once, at one instant. Its time
must read the SAME in the History table, in the downloadable PDF, and in the
report email — same clock, same zone, same words. The frontend already renders
every stored UTC timestamp in India Standard Time (`frontend/src/utils/format.js`
picks `Asia/Kolkata`, 12-hour clock, medium date + short time). The mail
attachments used to print the RAW naive UTC (`"%Y-%m-%d %H:%M:%S"`), which is
5h30m BEHIND what the user saw on screen — a prediction made at 6:45 pm IST
arrived in the email reading 1:15 pm. That mismatch is exactly the "exact time"
bug.

`format_ist` is the backend mirror of the frontend's `formatDate`: parse the
stored naive UTC, attach the zone, convert to IST, and print with the same
date style the screens use. Where a row has no timestamp at all the answer is
the honest "" / "Not Available" — never a fabricated clock reading.
"""

from datetime import datetime, timedelta, timezone

# India Standard Time is a fixed UTC+5:30 — no DST, so a constant offset is
# exact (a full `ZoneInfo("Asia/Kolkata")` would be equally correct and needs
# the tzdata package; the fixed offset keeps the dependency list unchanged).
IST = timezone(timedelta(hours=5, minutes=30))

# The words a missing timestamp produces in each context.
PLACEHOLDER = "Not Available"


def to_ist(value: datetime | None) -> datetime | None:
    """A stored naive-UTC datetime, converted to IST. None stays None."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(IST)


def format_ist(value: datetime | None, *, placeholder: str = PLACEHOLDER) -> str:
    """The on-screen form: "18 Sep 2026, 6:45 pm" — matching the app's screens.

    The frontend's `Intl.DateTimeFormat('en-IN', { dateStyle: 'medium',
    timeStyle: 'short', hour12: true, timeZone: 'Asia/Kolkata' })` produces
    "18 Sep 2026, 6:45 pm" for a September evening; this renders the same
    words so a report read in the mail agrees with the row in the History
    table, minute for minute.
    """
    ist = to_ist(value)
    if ist is None:
        return placeholder
    day = ist.day
    month = ist.strftime("%b")
    year = ist.year
    hour_12 = ist.strftime("%I").lstrip("0") or "12"
    minute = ist.strftime("%M")
    marker = "am" if ist.hour < 12 else "pm"
    return f"{day} {month} {year}, {hour_12}:{minute} {marker}"


def format_ist_time(value: datetime | None, *, placeholder: str = PLACEHOLDER) -> str:
    """Just the clock: "6:45:30 pm", IST — the same zone the screens use.

    The mail PDF splits date and time into two cells; both must come from the
    same conversion as `format_ist`, so a report cannot disagree with itself.
    """
    ist = to_ist(value)
    if ist is None:
        return placeholder
    hour_12 = ist.strftime("%I").lstrip("0") or "12"
    marker = "am" if ist.hour < 12 else "pm"
    return f"{hour_12}:{ist.strftime('%M:%S')} {marker}"


def format_ist_csv(value: datetime | None) -> str:
    """The spreadsheet form, still IST: "2026-09-18 18:45:30".

    A spreadsheet column sorts and filters better on a fixed-width stamp than
    on the words `format_ist` produces, so the CSV uses this while keeping the
    SAME clock (IST) — a CSV timestamp that disagreed with the History row by
    five and a half hours was the original bug, and this is what removes it.
    """
    ist = to_ist(value)
    return ist.strftime("%Y-%m-%d %H:%M:%S") if ist else ""
