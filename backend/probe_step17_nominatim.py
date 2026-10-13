"""Can Nominatim enumerate a state's districts on its own?"""
import json
import sys
import time

sys.path.insert(0, r"c:\Users\abishek\OneDrive\Desktop\aquagaurd\backend")

import requests

H = {"User-Agent": "AquaGuardAI/1.0 (water-quality-app)"}
S = requests.Session()

trials = [
    ("featureType=county + state", {
        "q": "",
        "state": "Tamil Nadu",
        "country": "India",
        "featureType": "county",
        "format": "jsonv2",
        "addressdetails": 1,
        "limit": 50,
    }),
    ("featureType=county + q", {
        "q": "Tamil Nadu",
        "featureType": "county",
        "format": "jsonv2",
        "addressdetails": 1,
        "limit": 50,
    }),
    ("featureType=state_district", {
        "q": "",
        "state": "Tamil Nadu",
        "country": "India",
        "featureType": "state_district",
        "format": "jsonv2",
        "addressdetails": 1,
        "limit": 50,
    }),
    ("q=districts in state", {
        "q": "district, Tamil Nadu, India",
        "format": "jsonv2",
        "addressdetails": 1,
        "limit": 50,
    }),
]

for label, params in trials:
    params = {k: v for k, v in params.items() if v != ""}
    t = time.perf_counter()
    try:
        r = S.get("https://nominatim.openstreetmap.org/search", params=params,
                  headers=H, timeout=45)
        dt = time.perf_counter() - t
        if r.status_code != 200:
            print("%-28s %s in %.1fs" % (label, r.status_code, dt), flush=True)
            continue
        rows = r.json()
        names = []
        for row in rows:
            ad = row.get("address") or {}
            nm = ad.get("county") or ad.get("state_district") or row.get("name")
            if nm and nm not in names:
                names.append(nm)
        print("%-28s 200 in %.1fs -> %d rows / %d districts" % (label, dt, len(rows), len(names)), flush=True)
        for n in sorted(names):
            print("     ", n, flush=True)
    except Exception as exc:  # noqa: BLE001
        print("%-28s FAILED in %.1fs: %s" % (label, time.perf_counter() - t, exc), flush=True)
    time.sleep(1.2)
