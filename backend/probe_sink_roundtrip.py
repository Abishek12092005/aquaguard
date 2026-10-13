"""Send a MIME message straight to the local sink, to verify the sink fix.

The backend's .env now points at real Gmail, so `POST /reports/mail` never
reaches the sink. This drives the sink directly, which isolates the one thing
under test: whether what the sink writes to the log is a real, parseable MIME
message with a named attachment, or the flat blob it used to store.
"""

import email
import smtplib
import sys
from email.message import EmailMessage

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LOG = r"C:\Users\abishek\OneDrive\Desktop\aquagaurd\smtp_messages.log"

msg = EmailMessage()
msg["From"] = "aquaguard@test.local"
msg["To"] = "inbox@example.com"
msg["Subject"] = "Sink round-trip check"
msg.set_content("plain body line")
msg.add_attachment(
    b"%PDF-1.4\n% sink check\n%%EOF\n",
    maintype="application",
    subtype="pdf",
    filename="sink-check.pdf",
)

with smtplib.SMTP("127.0.0.1", 1025, timeout=20) as s:
    s.ehlo()
    s.send_message(msg)
print("sent to sink")

raw = open(LOG, encoding="utf-8", errors="ignore").read()
# Take the LAST matching chunk, then strip the framing that precedes the first
# header line. A previous run may also have written a broken (pre-fix) message
# into the same log, so this must look at the newest one and not an arbitrary
# match - a test that can pass or fail depending on log history is not a test.
chunk = [m for m in raw.split("=====MESSAGE=====") if "Sink round-trip" in m]
print(f"messages containing the subject: {len(chunk)}")
if not chunk:
    raise SystemExit("FAIL: the sink did not record the message")

body = chunk[-1].lstrip("\r\n")
text = body.replace("\r\n", "\n").replace("\n", "\r\n")
parsed = email.message_from_string(text)

print(f"is_multipart : {parsed.is_multipart()}")
print(f"content-type : {parsed.get_content_type()}")
print(f"Subject read : {parsed.get('Subject')!r}")
print(f"defects      : {parsed.defects}")

found = None
for part in parsed.walk():
    if part.get_filename():
        found = part
        break

if not found:
    raise SystemExit("FAIL: no named attachment found in the stored message")

payload = found.get_payload(decode=True) or b""
print(f"attachment   : {found.get_filename()} ({found.get_content_type()}, {len(payload)} bytes)")
print(f"payload      : {payload[:40]!r}")

ok = (
    parsed.is_multipart()
    and parsed.get_content_type() == "multipart/mixed"
    and parsed.get("Subject") == "Sink round-trip check"
    and found.get_filename() == "sink-check.pdf"
    and payload.startswith(b"%PDF")
)
print(f"\n{'PASS' if ok else 'FAIL'}: the sink stores a real, parseable MIME message")
raise SystemExit(0 if ok else 1)
