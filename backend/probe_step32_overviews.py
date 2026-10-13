"""Probe the country / state / district overview endpoints with a long timeout
and dump the RAW responses so the shapes are visible, not guessed."""

import json
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:5000/api/v1"
EMAIL = "step32final@aquaguard.test"
PASSWORD = "Str0ngPass!2026"


def request(path, method="GET", body=None, token=None, timeout=600):
    url = BASE + urllib.parse.quote(path, safe="/?&=")
    req = urllib.request.Request(url, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(req, data=data, timeout=timeout) as resp:
        return json.loads(resp.read())


def main():
    login = request("/auth/login", "POST", {"email": EMAIL, "password": PASSWORD})
    token = login["data"]["tokens"]["access_token"]
    print("login ok", flush=True)

    print("=== /locations/state?q=Tamil Nadu&limit=4 ===", flush=True)
    try:
        s = request("/locations/state?q=Tamil%20Nadu&limit=4", token=token)
        print(json.dumps(s, ensure_ascii=False)[:1500], flush=True)
    except Exception as exc:
        print(f"STATE ERROR: {exc!r}", flush=True)

    print("=== /locations/country?q=India&limit=3 ===", flush=True)
    try:
        c = request("/locations/country?q=India&limit=3", token=token, timeout=900)
        print(json.dumps(c, ensure_ascii=False)[:1500], flush=True)
    except Exception as exc:
        print(f"COUNTRY ERROR: {exc!r}", flush=True)

    print("=== /locations/district?q=Sivaganga ===", flush=True)
    try:
        d = request("/locations/district?q=Sivaganga", token=token, timeout=900)
        print(json.dumps(d, ensure_ascii=False)[:2000], flush=True)
    except Exception as exc:
        print(f"DISTRICT ERROR: {exc!r}", flush=True)


main()
