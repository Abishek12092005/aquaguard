"""One REPORT_CSV send, printing the full response to diagnose the failure."""

import json
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:5000/api/v1"

req = urllib.request.Request(BASE + "/auth/login", method="POST")
req.add_header("Content-Type", "application/json")
body = json.dumps({"email": "step32final@aquaguard.test", "password": "Str0ngPass!2026"}).encode()
with urllib.request.urlopen(req, data=body, timeout=30) as resp:
    token = json.loads(resp.read())["data"]["tokens"]["access_token"]

hist = urllib.request.urlopen(
    urllib.request.Request(BASE + "/predictions/history?page=1&per_page=1",
                           headers={"Authorization": f"Bearer {token}"}), timeout=30)
rows = json.loads(hist.read())["data"]
rows = rows["items"] if isinstance(rows, dict) else rows
own_id = rows[0]["id"]

req2 = urllib.request.Request(BASE + "/reports/mail", method="POST")
req2.add_header("Content-Type", "application/json")
req2.add_header("Authorization", f"Bearer {token}")
payload = json.dumps({"email": "inbox@example.com", "option": "REPORT_CSV",
                      "prediction_id": own_id}).encode()
try:
    with urllib.request.urlopen(req2, data=payload, timeout=120) as resp:
        print(resp.status, resp.read().decode())
except urllib.error.HTTPError as exc:
    print(exc.code, exc.read().decode())
