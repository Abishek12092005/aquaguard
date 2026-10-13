# File: backend/test_step32_dump2.py
import json, urllib.parse, urllib.request, sys

BASE = "http://127.0.0.1:5000/api/v1"
EMAIL = "step31test@aquaguard.test"
PASSWORD = "Str0ngPass!2026"

def request(path, method="GET", body=None, token=None, timeout=120):
    # `%` is safe: the callers pass percent-encoded paths, and re-quoting
    # produced %2520 (the double-encoding that broke space searches).
    url = BASE + urllib.parse.quote(path, safe="/?&=%")
    req = urllib.request.Request(url, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(req, data=data, timeout=timeout) as resp:
        return json.loads(resp.read())

def p(label, obj):
    print(f"{label}: {json.dumps(obj)[:500]}", flush=True)

# THE API IS OPEN: no login endpoint exists (open-auth design); no token.
token = None

res = request("/locations/search?q=Meenakshi%20Temple&limit=5", token=token)
p("SEARCH", res["data"])

try:
    s = request("/locations/state?q=Tamil%20Nadu&limit=5", token=token, timeout=90)
    p("STATE", s["data"])
except Exception as e:
    p("STATE ERROR", repr(e))

try:
    d = request("/locations/district?q=Sivaganga&limit=5", token=token, timeout=90)
    p("DISTRICT", d["data"])
except Exception as e:
    p("DISTRICT ERROR", repr(e))
