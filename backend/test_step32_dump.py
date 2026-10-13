import json, os, urllib.parse, urllib.request

BASE = "http://127.0.0.1:5000/api/v1"
EMAIL = "step31test@aquaguard.test"
PASSWORD = "Str0ngPass!2026"

def request(path, method="GET", body=None, token=None, timeout=590):
    url = BASE + urllib.parse.quote(path, safe="/?&=")
    req = urllib.request.Request(url, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(req, data=data, timeout=timeout) as resp:
        return json.loads(resp.read())

print("requesting (open API - no login)...", flush=True)
# THE API IS OPEN: no login endpoint exists (open-auth design); no token.
token = None

c = request("/locations/country?q=India&limit=5", token=token)
print("COUNTRY data keys:", list(c["data"].keys()), flush=True)
print("COUNTRY country:", json.dumps(c["data"]["country"])[:200], flush=True)
for s in c["data"]["states"]:
    print("  STATE ITEM:", json.dumps(s)[:300], flush=True)

s = request("/locations/state?q=Tamil%20Nadu&limit=5", token=token)
print("STATE data keys:", list(s["data"].keys()), flush=True)
print("STATE message:", s["data"].get("message"), flush=True)
print("STATE available:", s["data"].get("available"), "state:", json.dumps(s["data"].get("state"))[:200], flush=True)

res = request("/locations/search?q=Meenakshi%20Temple&limit=5", token=token)
print("SEARCH data type:", type(res["data"]).__name__, json.dumps(res["data"])[:600], flush=True)
