"""Retest TEST7 (famous place) + TEST2 (state) through the live API."""

import json
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:5000/api/v1"
EMAIL = "step32final@aquaguard.test"
PASSWORD = "Str0ngPass!2026"


def request(path, method="GET", body=None, token=None, timeout=300):
    url = BASE + urllib.parse.quote(path, safe="/?&=")
    req = urllib.request.Request(url, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(req, data=data, timeout=timeout) as resp:
        return json.loads(resp.read())


login = request("/auth/login", "POST", {"email": EMAIL, "password": PASSWORD})
token = login["data"]["tokens"]["access_token"]

print("=== TEST7 /locations/search?q=Meenakshi Temple ===", flush=True)
try:
    r = request("/locations/search?q=Meenakshi%20Temple&limit=5", token=token)
    items = r["data"] if isinstance(r["data"], list) else []
    print(f"count={len(items)}", flush=True)
    if items:
        top = items[0]
        print(json.dumps(top, ensure_ascii=False)[:400], flush=True)
except Exception as exc:
    print(f"ERROR: {exc!r}", flush=True)

print("=== TEST2 /locations/state?q=Tamil Nadu&limit=5 ===", flush=True)
try:
    s = request("/locations/state?q=Tamil%20Nadu&limit=5", token=token)
    print(json.dumps(s, ensure_ascii=False)[:600], flush=True)
except Exception as exc:
    print(f"ERROR: {exc!r}", flush=True)
