"""One e2e send for POST /api/v1/reports/mail against the local SMTP sink.

WHAT WAS WRONG WITH THE ORIGINAL, and why each fix is here rather than guessed:

  1. `shekabi2005@gmail.com` does not exist in this database. Signing in as it
     returned 401 "Invalid email or password", so the script died on its FIRST
     request and never reached the send it was written to exercise. The account
     below is one that demonstrably exists and has reports.

  2. `own_id` was used in the payload but never defined - the lookup above it
     bound `own`, not `own_id`. That is a NameError waiting behind the 401.

  3. `prediction_id` was being sent with `ALL_CSV`. The backend REJECTS a
     prediction id on the ALL options: they attach every report the account
     owns, and an id there is meaningless. It is now omitted, which is also what
     the React popup does - `prediction_id` is only sent for REPORT_PDF and
     REPORT_CSV.

  4. The history envelope was unpacked by hand. `GET /predictions/history`
     answers `{data: [ ...rows... ], meta: {page, per_page, total, ...}}` — the
     rows are the list in `data` and the PAGINATION lives separately in `meta`.
     The original's `rows[0] if isinstance(rows, list) else rows["items"][0]`
     therefore happened to be right, and the version below reads it directly
     instead. (An intermediate draft of this fix asserted the rows came back
     under `data.items`; that was wrong, and the API said so.)

  5. HTTP errors were raised as tracebacks. A 401/404/422/503 from this endpoint
     is a normal answer carrying a message meant for a human, so it is printed
     as a code plus a message rather than as an unhandled exception.
"""

import json
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:5000/api/v1"
EMAIL = "step32final@aquaguard.test"
PASSWORD = "Str0ngPass!2026"
RECIPIENT = "inbox@example.com"


def call(path, method="GET", body=None, token=None, timeout=180):
    """One request. Returns (status, parsed-body) instead of raising.

    This endpoint's interesting failures are HTTP statuses with a useful message
    attached - a 422 for a bad option, a 404 for an unowned report, a 503 when
    the mail transport is not allowed to run. Raising on them would replace a
    readable explanation with a traceback, which is the opposite of helpful.
    """
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read() or b"{}"
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"message": raw.decode("utf-8", "ignore")}


# --- 1. Sign in ---------------------------------------------------------------
code, body = call("/auth/login", "POST", {"email": EMAIL, "password": PASSWORD})
if code != 200:
    print(f"FAIL  login as {EMAIL} -> {code}: {body.get('message')}")
    raise SystemExit(1)
token = body["data"]["tokens"]["access_token"]
user = body["data"]["user"]
print(f"OK    signed in as {user['email']} (id={user['id']})")

# --- 2. The account's own newest report ---------------------------------------
# `data` is the LIST of rows; the pagination counters live in `meta`, not here.
code, body = call("/predictions/history?page=1&per_page=1", token=token)
if code != 200:
    print(f"FAIL  history -> {code}: {body.get('message')}")
    raise SystemExit(1)

rows = body.get("data") or []
if not rows:
    print("FAIL  this account has no reports, so there is nothing to send.")
    print("      Submit a prediction first, or use an account that has one.")
    raise SystemExit(1)

own_id = rows[0]["id"]
total = (body.get("meta") or {}).get("total")
print(f"OK    newest own report id={own_id} (account holds {total} in total)")

# --- 3. Send ALL_CSV ----------------------------------------------------------
# No `prediction_id`: the ALL options attach every report the account owns and
# reject an id, which is exactly the check this call is there to exercise.
code, body = call(
    "/reports/mail",
    "POST",
    {"email": RECIPIENT, "option": "ALL_CSV"},
    token,
)
data = body.get("data") or {}
print(f"\n{'PASS' if code == 200 else 'FAIL'}  ALL_CSV -> {code}")
print(f"      message: {body.get('message')}")
if code == 200:
    print(f"      status:            {data.get('status')}")
    print(f"      recipient:         {data.get('recipient')}")
    print(f"      reports_included:  {data.get('reports_included')}")
    print(f"      attachment:        {data.get('attachment_name')} "
          f"({data.get('attachment_size')} bytes)")
else:
    print(f"      detail: {data.get('detail') or body.get('errors') or '(none)'}")
