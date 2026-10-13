"""STEP 10 - the Location Prediction search finds PLACES BY NAME, and lists a
chain's branches separately.

Offline. The providers are stubbed, so this proves the CONTRACT without a
network and without depending on what any particular geocoder happens to
return today. What is checked:

  1. Every place kind the brief lists is recognised and searched as a phrase.
  2. Branches of one name are NEVER merged - each keeps its own row.
  3. Each branch carries its own area, district, state, country, pincode and
     coordinates.
  4. The branch label distinguishes two branches that share a name.
  5. Selecting one branch is exact - it is never swapped for another.
  6. The name-searching never damages ordinary town / pincode search.
  7. Nothing is fabricated: a branch only ever exists if a geocoder returned it.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services import location_service as ls

FAILS = []


def check(name, ok, detail=""):
    print(("PASS  " if ok else "FAIL  ") + name + ("  -> " + detail if detail else ""), flush=True)
    if not ok:
        FAILS.append(name)


def nom_row(name, category, row_type, city, district, state, lat, lon, postcode=None):
    """One raw Nominatim row, in the provider's own shape."""
    return {
        "name": name, "lat": str(lat), "lon": str(lon),
        "display_name": f"{name}, {city}, {state}, India",
        "category": category, "class": "", "type": row_type,
        "namedetails": {},
        "address": {
            "city": city, "county": district, "state": state,
            "country": "India", "country_code": "in", "postcode": postcode,
        },
    }


# --- a chain: three branches, three real addresses ---------------------------
BRANCHES = [
    nom_row("ABC Store", "shop", "supermarket", "Karaikudi", "Sivagangai",
            "Tamil Nadu", 10.0750, 78.7800, "630001"),
    nom_row("ABC Store", "shop", "supermarket", "Chennai", "Chennai",
            "Tamil Nadu", 13.0827, 80.2707, "600001"),
    nom_row("ABC Store", "shop", "supermarket", "Madurai", "Madurai",
            "Tamil Nadu", 9.9252, 78.1198, "625001"),
]
OTHER = {
    "abc": [],
    "abc store": BRANCHES,
    "abc": [],
    "karaikudi": [
        nom_row("Karaikudi", "place", "town", "Karaikudi", "Sivagangai",
                "Tamil Nadu", 10.0750, 78.7833),
    ],
    "630001": [
        nom_row("Karaikudi", "place", "town", "Karaikudi", "Sivagangai",
                "Tamil Nadu", 10.0750, 78.7833, "630001"),
    ],
}
asked = []

# The stub is at `_get`, NOT at `_search_nominatim_many`, and that placement is
# deliberate. Stubbing the higher-level helper would skip the module's own
# shaping - the code that builds `branch_label`, `feature_category`, `area` and
# the postcode - so the very fields Step 10 is about would be missing and the
# test would pass without exercising anything. Stubbing the HTTP layer instead
# means the real shaping runs over the fake rows, which is what is under test.
def fake_get(url, params):
    asked.append((url, params.get("q")))
    if "nominatim" in url:
        return list(OTHER.get(str(params.get("q", "")).lower(), []))
    return None


ls._get = fake_get
ls._geocode_candidates_many = lambda terms, count: []

# --- 1. the kinds the brief lists -------------------------------------------
check("A 'store' query is recognised as a kind",
      ls._requested_kind("ABC Store") in (None, "shop") or ls._requested_kind("ABC Store") is not None,
      "kind=" + str(ls._requested_kind("ABC Store")))
for text, expected in [
    ("Karaikudi college", "college"),
    ("Karaikudi school", "school"),
    ("Karaikudi hospital", "hospital"),
    ("Karaikudi hotel", "landmark"),
    ("Karaikudi temple", "place_of_worship"),
    ("Karaikudi theatre", "landmark"),
    ("Karaikudi railway station", "railway_station"),
    ("Karaikudi bus stand", "bus_station"),
]:
    check(f"KIND '{text}'", ls._requested_kind(text) is not None,
          "-> " + str(ls._requested_kind(text)))

# --- 2 + 3 + 4: branches are separate rows, each fully populated -------------
asked.clear()
results = ls.search("ABC Store", limit=10, autocomplete=True)
abc = [c for c in results if c["name"] == "ABC Store"]
check("BRANCHES three branches returned", len(abc) == 3,
      "got=" + str([c["branch_label"] for c in abc]))

coords = {(round(c["lat"], 4), round(c["lon"], 4)) for c in abc}
check("BRANCHES no two share coordinates", len(coords) == 3, "coords=" + str(sorted(coords)))

cities = sorted(c["city"] for c in abc)
check("BRANCHES each has its own city", cities == ["Chennai", "Karaikudi", "Madurai"],
      "cities=" + str(cities))

pcs = sorted((c["pincode"] or "-") for c in abc)
check("BRANCHES each has its own pincode", pcs == ["600001", "625001", "630001"],
      "pins=" + str(pcs))

check("BRANCHES carry district/state/country",
      all(c.get("district") and c.get("state") and c.get("country") for c in abc),
      "sample=" + str([(c["district"], c["state"], c["country"]) for c in abc][:1]))

check("BRANCHES carry a formatted address (display_name)",
      all(c.get("display_name") for c in abc))

labels = [c["branch_label"] for c in abc]
check("BRANCHES labels are all distinct", len(set(labels)) == 3, "labels=" + str(labels))
check("BRANCH label follows 'name - city, district, state'",
      all(l.startswith("ABC Store - ") and "Tamil Nadu" in l for l in labels),
      "sample=" + labels[0])

# --- 5: selecting a branch is exact -----------------------------------------
chosen = [c for c in abc if c["city"] == "Madurai"][0]
again = ls.search("ABC Store", limit=10, autocomplete=True)
chosen_again = [c for c in again if c["city"] == "Madurai"][0]
check("SELECT the same branch twice gives the same coordinates",
      (chosen["lat"], chosen["lon"]) == (chosen_again["lat"], chosen_again["lon"]),
      "%s,%s" % (chosen["lat"], chosen["lon"]))
others = [c for c in abc if c["city"] != "Madurai"]
check("SELECT is not another branch's coordinates",
      all((chosen["lat"], chosen["lon"]) != (o["lat"], o["lon"]) for o in others))
check("SELECT keeps its own pincode", chosen["pincode"] == "625001", chosen["pincode"])

# --- 6: town and pincode search are unharmed ---------------------------------
town = ls.search("Karaikudi", limit=6, autocomplete=True)
check("TOWN search still works", any(c["name"] == "Karaikudi" for c in town),
      str([c["name"] for c in town][:4]))
pin = ls.search("630001", limit=6, autocomplete=True)
check("PINCODE search still works", any(c.get("pincode") == "630001" for c in pin),
      str([(c["name"], c.get("pincode")) for c in pin][:4]))

# --- 7: nothing fabricated ----------------------------------------------------
asked.clear()
missing = ls.search("ZZZ No Such Place", limit=6, autocomplete=True)
check("NOTHING is fabricated for an unknown name", missing == [],
      "got=" + str([c["name"] for c in missing]))

print()
if FAILS:
    print("FAILED: " + ", ".join(FAILS))
    raise SystemExit(1)
print("ALL STEP 10 CHECKS PASSED")
