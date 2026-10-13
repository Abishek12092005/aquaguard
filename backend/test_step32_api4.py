"""Dump the raw country/state/district overview payloads (slow Overpass calls)."""

import json
import os
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:5000/api/v1"
EMAIL = "step31test@aquaguard.test"
PASSWORD = "Str0ngPass!2026"


def request(path, token, timeout=1200):
    url = BASE + urllib.parse.quote(path, safe="/?&=%")
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def main():
    # THE API IS OPEN: no login endpoint exists (open-auth design); no token.
    token = None

    s = request("/locations/state?q=Tamil%20Nadu&limit=4", token)
    data = s["data"]
    print("STATE_KEYS:", list(data.keys()), flush=True)
    ds = data.get("districts", [])
    print("STATE districts:", len(ds), flush=True)
    if ds:
        print("DISTRICT_ROWS:", json.dumps(ds[:4], ensure_ascii=False)[:600], flush=True)

    d = request("/locations/district?q=Sivaganga&limit=9", token)
    dd = d["data"]
    print("DISTRICT_KEYS:", list(dd.keys()), flush=True)
    places = dd.get("places", [])
    print("PLACES:", len(places), flush=True)
    if places:
        print("PLACE_ROW_KEYS:", list(places[0].keys()), flush=True)
        print("NAMES:", [p.get("name") for p in places], flush=True)
        verdict_keys = [k for p in places for k in p if k in ("prediction", "verdict", "risk_level", "risk_category")]
        print("VERDICT_LABEL_KEYS_ON_PLACES:", sorted(set(verdict_keys)), flush=True)


main()
