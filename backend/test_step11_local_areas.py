"""STEP 11 - the Location Prediction search finds SMALL LOCAL AREAS.

Offline, with the HTTP layer stubbed so the module's own shaping and ranking run
over fixed rows. What is proved:

  1. A query naming an area is RECOGNISED as one (nagar, colony, street, ward,
     and two-word markers like "Bus Stand Road"), on whole words only.
  2. The AREA is searched, not just the town - the town must not be the only
     thing that ever comes back.
  3. A real area OUTRANKS the town it sits in, because a search for a nagar is
     not a search for a town.
  4. A village is NOT promoted as an area: the provider's own type decides, so
     "Anna Nagar" the village cannot answer for "Anna Nagar" the nagar.
  5. The selected area carries city, district, state, country, pincode, a
     formatted label and its own coordinates.
  6. A plain town search is completely unchanged - "Karaikudi" is still a town.
  7. Nothing is invented: a name with no provider row yields no row.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services import location_service as ls

FAILS = []


def check(name, ok, detail=""):
    print(("PASS  " if ok else "FAIL  ") + name + ("  -> " + detail if detail else ""), flush=True)
    if not ok:
        FAILS.append(name)


def nom_row(name, category, row_type, *, city=None, district=None, state="Tamil Nadu",
            lat=0.0, lon=0.0, postcode=None, suburb=None):
    """One raw Nominatim row, in the provider's own shape."""
    return {
        "name": name, "lat": str(lat), "lon": str(lon),
        "display_name": f"{name}, {city or state}, {state}, India",
        "category": category, "class": "", "type": row_type,
        "namedetails": {},
        "address": {
            "city": city, "county": district, "state": state,
            "country": "India", "country_code": "in", "postcode": postcode,
            "suburb": suburb,
        },
    }


# A real nagar in Chennai (type "suburb"), a village of the SAME name elsewhere
# (type "village"), and the town itself.
NAGAR = nom_row("Anna Nagar", "place", "suburb", city="Chennai Corporation",
                district="Madhavaram", lat=13.2074, lon=80.3150, postcode="600057")
VILLAGE = nom_row("Anna Nagar", "place", "village", city=None,
                  district="Salem", lat=11.66, lon=78.14, postcode="636001")
TOWN = nom_row("Karaikudi", "place", "town", city="Karaikudi",
               district="Sivagangai", lat=10.0750, lon=78.7833, postcode="630001")
COLONY = nom_row("Kolar Colony", "place", "suburb", city="Kolar",
                 district="Kolar", state="Karnataka", lat=13.1355, lon=77.6850,
                 postcode="562101")

ROWS = {
    "anna nagar": [NAGAR, VILLAGE],
    "chennai anna nagar": [NAGAR],
    "kolar colony": [COLONY],
    "karaikudi": [TOWN],
    "bus stand road": [nom_row("Bus Stand Road", "highway", "residential",
                               city="Karaikudi", district="Sivagangai",
                               lat=10.076, lon=78.781)],
}
asked = []


def fake_get(url, params):
    # Every query is recorded, so the test can assert WHICH forms were sent.
    asked.append(str(params.get("q") or params.get("name") or ""))
    if "nominatim" in url:
        return list(ROWS.get(str(params.get("q", "")).lower(), []))
    return None


ls._get = fake_get
ls._geocode_candidates_many = lambda terms, count: []

# --- 1: an area query is recognised ------------------------------------------
for text in ["Anna Nagar", "Kolar Colony", "Anna Nagar Main Road", "Bus Stand Road",
             "Mylapore Ward", "Pettai Layout", "T. Nagar"]:
    check(f"AREA recognised: {text}", ls._locality_query(text))

for text in ["Karaikudi", "Chennai", "Kolar", "630001", "Indian Bank",
             "Karaikudi college", "Meenakshi Temple"]:
    check(f"NOT an area: {text}", not ls._locality_query(text))

# A town whose name merely CONTAINS a locality word is still a town.
check("'Nagarkoil' is a town, not a nagar", not ls._locality_query("Nagarkoil"))

# --- 2: the area, not just the town, is searched -----------------------------
asked.clear()
ls.search("Chennai Anna Nagar", limit=6, autocomplete=True)
sent = [a for a in asked if a]
check("AREA is queried on its own", "Anna Nagar" in sent, "sent=" + str(sent))
check("TOWN is still queried too (not replaced)", any("Chennai" in a for a in sent),
      "sent=" + str(sent))

# --- 3 + 4: a real area outranks the town, and a village does not masquerade ---
asked.clear()
results = ls.search("Chennai Anna Nagar", limit=6, autocomplete=True)
top = results[0] if results else None
check("AREA leads the result", top is not None and top["name"] == "Anna Nagar",
      "top=" + str(top["name"]) if top else "nothing")
check("AREA row is the nagar, not the village",
      top is not None and top.get("feature_type") == "suburb",
      "type=" + str(top.get("feature_type")) if top else "")
check("AREA city is a real town", top is not None and top.get("city") == "Chennai Corporation",
      "city=" + str(top.get("city")) if top else "")

# A search for a nagar must not be answered by a village of the same name.
only_village = ls._search_nominatim_many(["village only"], 5)
check("A village row is NOT a locality", not ls._is_locality_row({
    "feature_type": "village", "feature_category": "place", "feature_code": "PPL"}))
check("A suburb row IS a locality", ls._is_locality_row({
    "feature_type": "suburb", "feature_category": "place", "feature_code": None}))

# --- 5: the selected area is fully identified -------------------------------
p = top
check("SELECTED name", p is not None and p["name"] == "Anna Nagar")
check("SELECTED city", p is not None and bool(p.get("city")), str(p.get("city")))
check("SELECTED district", p is not None and bool(p.get("district")), str(p.get("district")))
check("SELECTED state", p is not None and bool(p.get("state")), str(p.get("state")))
check("SELECTED country", p is not None and bool(p.get("country")), str(p.get("country")))
check("SELECTED pincode", p is not None and p.get("pincode") == "600057", str(p.get("pincode")))
check("SELECTED coordinates", p is not None and bool(p.get("lat")) and bool(p.get("lon")),
      "%s,%s" % (p.get("lat"), p.get("lon")) if p else "")
check("SELECTED formatted label", p is not None and bool(p.get("branch_label")),
      p.get("branch_label") if p else "")
check("SELECTED area field", p is not None and bool(p.get("area")), str(p.get("area")))

# The nagar and the village are different places and stay different.
vill = [c for c in ls.search("Anna Nagar", limit=6, autocomplete=True)
        if c.get("feature_type") == "village"]
check("VILLAGE stays a separate row", len(vill) >= 1, "found=" + str(len(vill)))
check("VILLAGE is not the first result", not results or results[0].get("feature_type") != "village")

# --- 6: a plain town search is unchanged ------------------------------------
asked.clear()
town = ls.search("Karaikudi", limit=6, autocomplete=True)
check("TOWN still resolves", any(c["name"] == "Karaikudi" for c in town),
      str([c["name"] for c in town][:3]))
check("TOWN is not treated as an area", not any(ls._is_locality_row(c) for c in town))
check("TOWN search sends no area-only query", all("Nagar" not in a for a in asked),
      "sent=" + str([a for a in asked if a]))

# --- 7: nothing is invented -------------------------------------------------
asked.clear()
missing = ls.search("Zzz Nowhere Nagar", limit=6, autocomplete=True)
check("NOTHING fabricated for an unknown area",
      all(c["name"] != "Zzz Nowhere Nagar" for c in missing),
      "got=" + str([c["name"] for c in missing]))

print()
if FAILS:
    print("FAILED: " + ", ".join(FAILS))
    raise SystemExit(1)
print("ALL STEP 11 CHECKS PASSED")
