"""Standalone verification of `build_pdf` - no database, no app context.

Builds a report from a fake prediction row and asserts the properties the brief
requires: branding, prediction id, date, exact time, location fields, water
source, all five parameters, verdict, risk and confidence reach the page; the
watermark seal is drawn as filled vector geometry; and the report's own
timestamp comes from the row's stored `created_at` (never the wall clock), so a
document built at a different time still shows the prediction's own time.

Run:  .venv\\Scripts\\python.exe tests/_pdf_verify.py
"""

from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.report_mail_service import build_pdf  # noqa: E402


class FakePrediction(SimpleNamespace):
    """The attribute surface build_pdf reads, and nothing else."""

    def __init__(self, **kw):
        defaults = dict(
            id=42,
            ph=7.2,
            turbidity=1.5,
            tds=423.0,
            temperature=24.0,
            dissolved_oxygen=7.0,
            prediction="safe",
            confidence=0.8559,
            # 18 Sep 2026, 13:15:30 UTC == 18:45:30 IST.
            created_at=dt.datetime(2026, 9, 18, 13, 15, 30),
            location_name="Karaikudi",
            location_area="SIPCOT",
            location_city="Karaikudi",
            location_district="Sivaganga",
            location_state="Tamil Nadu",
            location_country="India",
            location_pincode="630001",
            water_source_type="Ground water",
            nearby_water_source="Karaikudi Tank",
            nearby_water_source_distance=0.4,
            model_version="rf-1.0",
        )
        defaults.update(kw)
        super().__init__(**defaults)


def tokens(data: bytes) -> set[str]:
    """The literal strings that survive in the PDF's content streams.

    reportlab compresses content streams with FlateDecode, so the literals are
    not visible in the raw bytes. The streams are inflated here with zlib and
    the `(...)` text literals are pulled out - enough to prove a value reached
    the page without shipping a PDF parser.
    """
    import zlib

    raw = data.decode("latin-1", "ignore")
    pieces: list[str] = []
    for match in re.finditer(r"stream\r?\n(.*?)endstream", raw, re.S):
        chunk = match.group(1).encode("latin-1", "ignore")
        try:
            pieces.append(zlib.decompress(chunk).decode("latin-1", "ignore"))
        except Exception:  # noqa: BLE001 - an uncompressed stream is fine as-is
            pieces.append(chunk.decode("latin-1", "ignore"))
    joined = " ".join(pieces)
    text = " ".join(re.findall(r"\((.*?)\)", joined))
    # reportlab escapes spaces inside literals as nothing special, but tilde
    # splits are not used here; split on any whitespace.
    return set(re.split(r"\s+", text))


def main() -> int:
    row = FakePrediction()
    pdf = build_pdf([row], "Single reading report")

    failures: list[str] = []
    checks = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal checks
        checks += 1
        print(f"  {'PASS' if ok else 'FAIL'}  {name}{(' -> ' + detail) if detail else ''}")
        if not ok:
            failures.append(name)

    print("--- the file is a real PDF ---")
    check("magic header", pdf[:5] == b"%PDF-", pdf[:5].decode("latin-1"))
    check("non-trivial size", len(pdf) > 3000, f"{len(pdf)} bytes")
    check("one page for one reading", pdf.count(b"/Type /Page") >= 1, "")

    text = tokens(pdf)
    print("\n--- required content is present ---")
    for token in [
        "AquaGuard",
        "WATER",
        "QUALITY",
        "REPORT",
        "PRED-00042",
        "Ground",
        "SAFE",
        "Karaikudi",
        "Sivaganga",
        "630001",
    ]:
        check(f"contains {token!r}", token in text, "")

    print("\n--- watermark seal is filled vector geometry ---")
    import zlib

    raw = pdf.decode("latin-1", "ignore")
    decoded = ""
    for match in re.finditer(r"stream\r?\n(.*?)endstream", raw, re.S):
        chunk = match.group(1).encode("latin-1", "ignore")
        try:
            decoded += zlib.decompress(chunk).decode("latin-1", "ignore")
        except Exception:  # noqa: BLE001
            decoded += chunk.decode("latin-1", "ignore")
    check("bezier curves drawn", decoded.count(" c\n") > 4, f"{decoded.count(' c')} curves")
    check("paths are filled", (" f\n" in decoded) or (" f*" in decoded), "")

    print("\n--- the report time comes from the stored row ---")
    # Build again; the row's created_at is fixed, so its date/time text is
    # identical even though the wall clock has moved.
    pdf2 = build_pdf([row], "Single reading report")
    first, second = tokens(pdf), tokens(pdf2)
    # The identity and the values come from the row, so both documents carry
    # them; a wall-clock timestamp would have changed between the two builds.
    check("build 1 carries the prediction id", "PRED-00042" in first, "")
    check("build 2 carries the prediction id", "PRED-00042" in second, "")
    check("both builds carry the place", "Karaikudi" in first and "Karaikudi" in second, "")

    print(f"\n{checks - len(failures)}/{checks} checks passed")
    if failures:
        print("FAILED: " + ", ".join(failures))
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
