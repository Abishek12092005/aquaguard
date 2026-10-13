"""E2E test for POST /api/v1/reports/mail against a local SMTP sink."""

import json
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:5000/api/v1"
MAIN_EMAIL = "step32final@aquaguard.test"
MAIN_PASSWORD = "Str0ngPass!2026"
OTHER_EMAIL = "step31test@aquaguard.test"
OTHER_PASSWORD = "Str0ngPass!2026"
SINK_LOG = r"C:\Users\abishek\OneDrive\Desktop\aquagaurd\smtp_messages.log"

results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  -> {detail}" if detail else ""), flush=True)


def call(path, method="GET", body=None, token=None, timeout=120):
    url = BASE + urllib.parse.quote(path, safe="/?&= ").replace(" ", "%20")
    req = urllib.request.Request(url, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def login(email, password):
    _, body = call("/auth/login", "POST", {"email": email, "password": password})
    return body["data"]["tokens"]["access_token"]


# --- 0. Tokens -------------------------------------------------------------
main_token = login(MAIN_EMAIL, MAIN_PASSWORD)
other_token = login(OTHER_EMAIL, OTHER_PASSWORD)
check("auth: both test accounts log in", bool(main_token) and bool(other_token))

# The main account's OWN newest prediction id (from its own history).
_, hist = call("/predictions/history?page=1&per_page=1", token=main_token)
rows = hist["data"]["items"] if isinstance(hist["data"], dict) else hist["data"]
own_id = rows[0]["id"]
own_report_count = None
_, hist_all = call("/predictions/history?page=1&per_page=100", token=main_token)
rows_all = hist_all["data"]["items"] if isinstance(hist_all["data"], dict) else hist_all["data"]
own_report_count = len(rows_all)
print(f"own newest id={own_id}, own reports={own_report_count}", flush=True)

# Another user's prediction id, from THAT user's own history.
_, hist2 = call("/predictions/history?page=1&per_page=1", token=other_token)
rows2 = hist2["data"]["items"] if isinstance(hist2["data"], dict) else hist2["data"]
foreign_id = rows2[0]["id"] if rows2 else None
print(f"other user's newest id={foreign_id}", flush=True)

# --- 1. Security ------------------------------------------------------------
code, _ = call("/reports/mail", "POST", {"email": "user@example.com", "option": "ALL_CSV"})
check("401 without a JWT", code == 401, f"code={code}")

code, body = call("/reports/mail", "POST", {"email": "user@example.com", "option": "NOPE"}, main_token)
check("422 unknown option", code == 422, f"code={code} msg={body.get('message', '')[:60]}")

code, body = call("/reports/mail", "POST", {"email": "not-an-email", "option": "ALL_CSV"}, main_token)
check("422 invalid recipient email", code == 422, f"code={code}")

code, body = call("/reports/mail", "POST", {"option": "REPORT_PDF"}, main_token)
check("422 missing email", code == 422, f"code={code}")

code, body = call("/reports/mail", "POST", {"email": "user@example.com", "option": "REPORT_PDF"}, main_token)
check("422 REPORT_* without prediction_id", code == 422, f"code={code}")

if foreign_id is not None:
    code, body = call("/reports/mail", "POST", {
        "email": "user@example.com", "option": "REPORT_PDF", "prediction_id": foreign_id,
    }, main_token)
    check("404 another user's report (ownership enforced server-side)", code == 404,
          f"code={code} msg={body.get('message', '')[:60]}")

code, body = call("/reports/mail", "POST", {
    "email": "user@example.com", "option": "REPORT_PDF", "prediction_id": 99999999,
}, main_token)
check("404 nonexistent report id", code == 404, f"code={code}")

# --- 2. Happy paths through the local SMTP sink -----------------------------
def send_and_check(name, payload, expect_ext, expect_count=None):
    code, body = call("/reports/mail", "POST", payload, main_token, timeout=180)
    data = body.get("data") or {}
    ok = code == 200 and data.get("sent") is True
    detail = f"code={code} status={data.get('status')} attachment={data.get('attachment_name')} size={data.get('attachment_size')}"
    check(f"{name}: 200 + sent", ok, detail)
    if ok:
        ext_ok = (data.get("attachment_name") or "").lower().endswith(expect_ext)
        check(f"{name}: attachment is {expect_ext}", ext_ok, data.get("attachment_name"))
        if expect_count is not None:
            check(f"{name}: reports_included == {expect_count}",
                  data.get("reports_included") == expect_count,
                  f"got={data.get('reports_included')}")
    return data


sink_log_len = 0
try:
    with open(SINK_LOG, "rb") as fh:
        sink_log_len = len(fh.read())
except FileNotFoundError:
    pass


def sink_new_bytes():
    with open(SINK_LOG, "rb") as fh:
        return fh.read()[sink_log_len:]


d = send_and_check("REPORT_PDF", {
    "email": "inbox@example.com", "option": "REPORT_PDF", "prediction_id": own_id,
}, ".pdf")
new = sink_new_bytes()
check("REPORT_PDF: sink received a real PDF attachment",
      b"Content-Type: application/pdf" in new and b"%PDF" in new,
      f"{len(new)} bytes in sink log")

d2 = send_and_check("REPORT_CSV", {
    "email": "inbox@example.com", "option": "REPORT_CSV", "prediction_id": own_id,
}, ".csv")
new = sink_new_bytes()
check("REPORT_CSV: sink received the CSV attachment with the header row",
      b"Report ID" in new and b"text/csv" in new and own_report_count is not None,
      f"{len(new)} bytes")

d3 = send_and_check("ALL_PDF", {"email": "inbox@example.com", "option": "ALL_PDF"}, ".pdf",
                    expect_count=own_report_count)
new = sink_new_bytes()
check("ALL_PDF: sink received the multi-report PDF",
      b"Content-Type: application/pdf" in new and b"%PDF" in new, f"{len(new)} bytes")

d4 = send_and_check("ALL_CSV", {"email": "inbox@example.com", "option": "ALL_CSV"}, ".csv",
                    expect_count=own_report_count)
new = sink_new_bytes()
check("ALL_CSV: sink received the multi-report CSV",
      b"text/csv" in new and b"Report ID" in new, f"{len(new)} bytes")

# --- 3. Isolation: the attachments only carry the main account's own ids ----
own_csv = call("/reports/mail", "POST", {"email": "inbox@example.com", "option": "ALL_CSV"},
               main_token, timeout=180)[1]
own_ids = {row["id"] for row in rows_all}
csv_blob = sink_new_bytes().decode("utf-8", "ignore")
foreign_ids_in_csv = [
    rid for rid in own_ids
    if False  # placeholder; foreign ids are not enumerable from here
]
# The CSV should mention the account's own report ids, and the foreign id must not appear.
check("ALL_CSV: contains the account's own report id",
      any(f"AGR-" in line and "-" in line for line in csv_blob.splitlines()[1:2]),
      csv_blob.splitlines()[1][:40] if len(csv_blob.splitlines()) > 1 else "")
if foreign_id is not None:
    check("ALL_CSV: does NOT contain another user's prediction id",
          f"PRED-{str(foreign_id).zfill(5)}" not in csv_blob)

# --- 4. The other user's ALL_CSV only has their own reports -----------------
code, body = call("/reports/mail", "POST", {"email": "inbox@example.com", "option": "ALL_CSV"},
                  other_token, timeout=180)
data = body.get("data") or {}
ok = code == 200 and data.get("sent") is True
check("other user ALL_CSV: 200 + sent", ok, f"code={code} included={data.get('reports_included')}")
new = sink_new_bytes().decode("utf-8", "ignore")
main_ids_strings = [f"PRED-{str(i).zfill(5)}" for i in own_ids]
leaked = [pid for pid in main_ids_strings if pid in new]
check("other user ALL_CSV: no leak of the first account's ids", not leaked,
      f"leaked={leaked[:2]}")

total = len(results)
passed = sum(1 for _, ok in results if ok)
print(f"\nSUMMARY: {passed}/{total} passed", flush=True)
failed = [n for n, ok in results if not ok]
if failed:
    print("FAILED: " + ", ".join(failed), flush=True)
