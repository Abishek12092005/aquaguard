"""Retry ONLY TEST3: /locations/district?q=Sivaganga with a very long timeout."""

import json
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:5000/api/v1"
EMAIL = "step32final@aquaguard.test"
PASSWORD = "Str0ngPass!2026"


def request(path, token=None, timeout=2400):
    url = BASE + urllib.parse.quote(path, safe="/?&= ").replace(" ", "%20")
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


login = json.loads(urllib.request.urlopen(urllib.request.Request(
    BASE + "/auth/login", method="POST",
    data=json.dumps({"email": EMAIL, "password": PASSWORD}).encode(),
    headers={"Content-Type": "application/json"}), timeout=60).read())
token = login["data"]["tokens"]["access_token"]
print("login ok", flush=True)

d = request("/locations/district?q=Sivaganga", token)
data = d["data"]
places = data.get("places")
items = places.get("items", places) if isinstance(places, dict) else (places or [])
print(f"message={data.get('message')!r} places={len(items)}", flush=True)
labels = any(any(k in p for k in ("prediction", "verdict", "risk_category", "risk_level"))
             for p in items if isinstance(p, dict))
for p in items[:9]:
    print(f"  {p.get('name')} | {p.get('area')} | {p.get('district')}, {p.get('state')}", flush=True)
verdict = "PASS" if items and not labels else ("FAIL - labels exposed" if labels else "EMPTY")
print(f"TEST3_RESULT: {verdict}", flush=True)
