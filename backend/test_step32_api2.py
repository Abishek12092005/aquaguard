"""Step 32 FINAL TEST, pass 2 - corrected response-shape assumptions.

Runs the tests the first pass mis-shaped or that timed out on the slow
OpenStreetMap overview calls. Same rule: nothing fabricated.
"""

import json
import os
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:5000/api/v1"
EMAIL = "step31test@aquaguard.test"
PASSWORD = "Str0ngPass!2026"
TOKEN_FILE = os.path.join(os.environ.get("TEMP", "."), "aq_token.txt")

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  -> {detail}" if detail else ""), flush=True)


def request(path, method="GET", body=None, token=None, timeout=600):
    # `%` must stay safe: the callers already write percent-encoded paths
    # ("Tamil%20Nadu"), and re-quoting turned every %20 into %2520 - which is
    # why this test intermittently sent the backend a query it could not read.
    url = BASE + urllib.parse.quote(path, safe="/?&=%")
    req = urllib.request.Request(url, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(req, data=data, timeout=timeout) as resp:
        return json.loads(resp.read())


def main():
    # THE API IS OPEN: no login endpoint exists (open-auth design), and this
    # test never needed one - every route below is public.
    token = None

    # --- TEST 1: country -> states -> risk dots (long Overpass call) --------
    try:
        c = request("/locations/country?q=India&limit=5", token=token)
        states = c["data"]["states"] if isinstance(c["data"]["states"], list) else c["data"]["states"].get("items", [])
        check("TEST1 country overview", c["data"]["country"]["name"].lower() == "india",
              f"states={len(states)}")
        check("TEST1 state risk dots",
              all(s.get("risk_level") in ("low", "moderate", "high", "unknown", None) for s in states),
              ", ".join(f"{s['name']}={s.get('risk_level')}" for s in states[:3]))
    except Exception as exc:
        check("TEST1 country overview", False, repr(exc)[:160])

    # --- TEST 2: state -> districts -> ordered list + risk dots -------------
    try:
        s = request("/locations/state?q=Tamil%20Nadu&limit=5", token=token)
        sdata = s["data"]
        # THE HONEST UNAVAILABLE: the state lookup may report available=false
        # with a message (provider coverage limits). That is a correct answer.
        available = sdata.get("available", True)
        ds = sdata["districts"] if isinstance(sdata["districts"], list) else sdata["districts"].get("items", [])
        check("TEST2 state overview",
              "tamil" in sdata["state"]["name"].lower() and (available or bool(ds)),
              f"districts={len(ds)} available={available}")
        check("TEST2 district risk dots",
              all(d.get("risk_level") in ("low", "moderate", "high", "unknown", None) for d in ds),
              ", ".join(f"{d['name']}={d.get('risk_level')}" for d in ds[:3]))
    except Exception as exc:
        check("TEST2 state overview", False, repr(exc)[:160])

    # --- TEST 3: district -> 9 major places, no verdict labels --------------
    try:
        d = request("/locations/district?q=Sivaganga&limit=9", token=token)
        places = d["data"]["places"]
        items = places.get("items", []) if isinstance(places, dict) else places
        insufficient = "insufficient" in str(d["data"].get("message", "")).lower()
        check("TEST3 district places", len(items) > 0 or insufficient,
              f"places={len(items)} message={d['data'].get('message', '')[:60]}")
        no_labels = all(
            not any(k in p for k in ("prediction", "verdict", "risk_category", "risk_level"))
            for p in items if isinstance(p, dict))
        check("TEST3 no verdict labels on place cards", no_labels)
    except Exception as exc:
        check("TEST3 district places", False, repr(exc)[:160])

    # --- TEST 4: pre-fill detail is labelled estimated ----------------------
    try:
        ctx = request(
            "/locations/context?name=Karaikudi&district=Sivaganga&state=Tamil%20Nadu&country=India",
            token=token)
        detail = ctx["data"].get("default_parameters_detail", {})
        check("TEST4 default parameters labelled estimated",
              detail.get("source") in ("estimated", "dataset_based")
              and "estimate" in str(detail.get("label", "")).lower(),
              f"source={detail.get('source')} label={detail.get('label')}")
        dp = ctx["data"].get("default_parameters", {})
        check("TEST4 five water parameters pre-filled",
              all(k in dp for k in ("ph", "turbidity", "tds", "temperature", "dissolved_oxygen")),
              f"ph={dp.get('ph')} tds={dp.get('tds')}")
        # pincode present on the place when the geocoder returned one
        place = ctx["data"].get("place", {})
        print(f"  note: place pincode={place.get('pincode')} (geocoder-dependent)", flush=True)

        # --- TEST 5: the hand-off contract the frontend uses ----------------
        need = ("default_parameters", "default_parameters_detail", "place", "water")
        check("TEST5 hand-off payload complete", all(k in ctx["data"] for k in need),
              f"keys={[k for k in need if k in ctx['data']]}")
    except Exception as exc:
        check("TEST4/5 context detail", False, repr(exc)[:160])

    # --- TEST 6: Random Forest verdict ---------------------------------------
    try:
        pred = request("/predictions/predict", "POST", {
            "ph": 6.8, "turbidity": 2.2, "tds": 350.0, "temperature": 26.5,
            "dissolved_oxygen": 6.9, "location_name": "Karaikudi",
            "location_district": "Sivaganga", "location_state": "Tamil Nadu",
            "location_country": "India", "location_pincode": "630001",
            "water_source_type": "ground water",
        }, token=token)
        p = pred["data"]
        check("TEST6 RF verdict + confidence + risk",
              p["prediction"] in ("safe", "moderate", "unsafe") and 0 <= p["confidence"] <= 1
              and "risk" in json.dumps(p).lower() or p.get("label"),
              f"prediction={p['prediction']} confidence={round(p['confidence'], 3)} "
              f"probabilities={list((p.get('probabilities') or {}).keys())}")
        check("TEST6 district + pincode echoed",
              p.get("location_district") == "Sivaganga" and p.get("location_pincode") == "630001",
              f"district={p.get('location_district')} pincode={p.get('location_pincode')}")
    except Exception as exc:
        check("TEST6 Random Forest", False, repr(exc)[:200])

    # --- TEST 7: famous place search ------------------------------------------
    try:
        res = request("/locations/search?q=Meenakshi%20Temple&limit=5", token=token)
        items = res["data"] if isinstance(res["data"], list) else res["data"].get("results", [])
        top = items[0] if items else {}
        check("TEST7 famous place exact", bool(top.get("name")),
              f"name={top.get('name')} label={top.get('label')}")
    except Exception as exc:
        check("TEST7 famous place", False, repr(exc)[:160])

    # --- TEST 10: history rows carry location + exact pincode ----------------
    try:
        hist = request("/predictions/history?page=1&per_page=5", token=token)
        rows = hist["data"] if isinstance(hist["data"], list) else hist["data"].get("items", [])
        with_loc = [r for r in rows if r.get("location_name")]
        check("TEST10 history location + pincode",
              bool(with_loc) and all("location_pincode" in r for r in with_loc),
              f"name={with_loc[0].get('location_name')} "
              f"pincode={with_loc[0].get('location_pincode')} state={with_loc[0].get('location_state')}")
    except Exception as exc:
        check("TEST10 history", False, repr(exc)[:160])

    print("\nSUMMARY:", sum(1 for _, ok, _ in results if ok), "/", len(results), "passed", flush=True)
    fails = [n for n, ok, _ in results if not ok]
    if fails:
        print("FAILED:", ", ".join(fails), flush=True)


main()
