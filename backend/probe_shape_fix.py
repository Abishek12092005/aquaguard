"""Quick verify of TEST6 / TEST10 / TEST11 shape fixes only (no Overpass)."""

import json
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:5000/api/v1"
EMAIL = "step32final@aquaguard.test"
PASSWORD = "Str0ngPass!2026"


def request(path, method="GET", body=None, token=None, timeout=60):
    url = BASE + urllib.parse.quote(path, safe="/?&= ").replace(" ", "%20")
    req = urllib.request.Request(url, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(req, data=data, timeout=timeout) as resp:
        return json.loads(resp.read())


login = request("/auth/login", "POST", {"email": EMAIL, "password": PASSWORD})
token = login["data"]["tokens"]["access_token"]

pred = request("/predictions/predict", "POST", {
    "ph": 7.0, "turbidity": 4.0, "tds": 350.0,
    "temperature": 26.0, "dissolved_oxygen": 6.0,
    "location_name": "Karaikudi", "location_district": "Sivaganga",
    "location_state": "Tamil Nadu", "location_country": "India",
    "location_pincode": "630001", "water_source_type": "ground water",
}, token=token)
p = pred["data"]
print("TEST6:", p["prediction"], round(p["confidence"], 3), "is_safe=", p["is_safe"],
      "district=", p.get("location_district"), "pincode=", p.get("location_pincode"))

hist = request("/predictions/history?page=1&per_page=5", token=token)
rows = hist["data"]["items"] if isinstance(hist["data"], dict) else hist["data"]
with_loc = [r for r in rows if r.get("location_name")]
print("TEST10 rows:", len(rows), "| loc rows:", len(with_loc),
      "| first:", with_loc[0].get("location_name"), with_loc[0].get("location_pincode") if with_loc else None)

adm = request("/admin/reports?page=1&per_page=3", token=token)
items = adm["data"].get("items", adm["data"]) if isinstance(adm["data"], dict) else adm["data"]
row = items[0] if items else {}
print("TEST11 items:", len(items),
      "| keys:", [k for k in row.keys() if "location" in k or "prediction" in k or "source" in k][:8],
      "| name:", row.get("location_name"), "pincode:", row.get("location_pincode"),
      "source:", row.get("water_source_type") or row.get("water_source"),
      "prediction:", row.get("prediction"))
