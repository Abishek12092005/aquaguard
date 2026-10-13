"""Decode every message in smtp_messages.log with the email parser and verify
the attachments' real content (PDF starts with %PDF, CSV has the header row)."""

import email
import email.policy
import re

LOG = r"C:\Users\abishek\OneDrive\Desktop\aquagaurd\smtp_messages.log"

raw = open(LOG, encoding="utf-8", errors="ignore").read()
messages = [m for m in raw.split("=====MESSAGE=====") if m.strip()]
print(f"messages received: {len(messages)}")

pdfs = 0
csvs = 0
all_csv_rows = 0
leaks = set()

for blob in messages:
    blob = blob.lstrip("\r\n").split("=====END=====")[0]
    message = email.message_from_string(blob, policy=email.policy.default)
    for part in message.iter_attachments():
        name = part.get_filename() or ""
        payload = part.get_payload(decode=True) or b""
        if name.endswith(".pdf"):
            pdfs += 1
            assert payload[:4] == b"%PDF", f"{name}: not a PDF!"
            print(f"PDF OK: {name} starts with %PDF, {len(payload)} bytes")
        elif name.endswith(".csv"):
            csvs += 1
            text = payload.decode("utf-8-sig")
            rows = [line for line in text.splitlines() if "AGR-" in line]
            kind = "ALL" if name.startswith("aquaguard-reports-all") else "single"
            print(f"CSV OK: {name} header={text.splitlines()[0][:30]!r} rows={len(rows)} ({kind})")
            if kind == "ALL":
                all_csv_rows = len(rows)
            for prediction_id in re.findall(r"PRED-(\d{5})", text):
                leaks.add(prediction_id)

print(f"\nPDFs verified: {pdfs}  CSVs verified: {csvs}")
print(f"ALL_CSV data rows: {all_csv_rows}")
print(f"prediction ids seen across ALL_CSVs: {sorted(leaks)}")
