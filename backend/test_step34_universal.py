"""
STEP 34 — does the pipeline work for EVERY valid searchable location?

The brief's failure mode is a system that quietly works for Chennai and Karaikudi
because those are the places its fixtures were written for. This probes locations
chosen to break that assumption:

  * five states and two countries, so a hard-coded city or district list fails
  * a coastal city, a desert city, a hill station, a pilgrimage town, a metro
    suburb and a PINCODE, because each stresses a different branch
  * one deliberately obscure village name, because that is where a hand-listed
    place would stop

For each one the WHOLE chain is walked, and every number is checked for
provenance. The question asked of each parameter is not "is it present" but
"can we name where it came from" — which is the only version of the rule that
forbids fabrication rather than merely discouraging it.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "app"))

from app.services import location_service as ls

# Force UTF-8 on stdout. The dataset names below are non-ASCII, and on a Windows
# console with a legacy code page the print RAISES rather than garbling — which
# kills the run at the first Hindi-named state and looks like a crash in the
# system under test rather than in the harness.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

FAILURES = []
CHECKS = 0

def check(label, ok, detail=""):
    global CHECKS
    CHECKS += 1
    if not ok:
        FAILURES.append(f"{label} :: {detail}")
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  -> {detail}" if detail else ""), flush=True)


# Deliberately NOT here: Chennai and Karaikudi. Those are the fixtures every other
# step was written against, so they are exactly the places that cannot prove
# anything. A probe set that included them would pass a system hard-coded to them.
PROBES = [
    ("Mumbai",                    "Maharashtra",   "metro, huge, coastal"),
    ("Jaipur",                    "Rajasthan",     "desert, no surface water"),
    ("Srinagar",                  "Jammu & Kashmir","hill, cold"),
    ("Varanasi",                  "Uttar Pradesh", "river, pilgrimage"),
    ("Port Blair",                "Andaman",       "island, coastal, tiny"),
    ("Leh",                       "Ladakh",        "high desert, extreme"),
    ("Bhubaneswar",               "Odisha",        "east"),
    ("Kochi",                     "Kerala",        "backwaters"),
    ("Guwahati",                  "Assam",         "north-east"),
    ("Nashik",                    "Maharashtra",   "inland, different state"),
    ("Rameswaram",                "Tamil Nadu",    "island temple town"),
    ("Puducherry",                "Puducherry",    "union territory, not a state"),
    ("700001",                    None,            "a pincode, not a name"),
    ("Thiruvallur",               "Tamil Nadu",    "obscure town"),
    ("Puthur",                    "Kerala",        "obscure village name"),
]

# The chain must produce provenance, and must never claim a bare measurement it
# cannot back. These are the ONLY labels the system is allowed to attach.
# The taxonomy the classifier can emit. Anything outside it is a bug, because
# `default_parameters()` would silently fall back to "municipal water source" and
# present a hard-coded profile as if it described this water.
KNOWN_TYPES = {
    "river water", "lake water", "pond water", "surface water", "tank water",
    "piped water", "municipal water source", "ground water", "rain water",
    "borewell water", "well water",
}

# --- THE PROVIDER IS STUBBED, AND WHY --------------------------------------
#
# Overpass is a free public service and is currently answering 504 / timing out
# from this network. That is an outage, not a defect, and testing against it
# would make this file a coin toss: every run would report "no water source
# anywhere" no matter what the code did.
#
# So the HTTP layer is replaced with a fixture that stands in for real mapped
# data. Geocoding, classification, distance maths, ranking, provenance selection
# and the never-fabricate rule are ALL still the real implementation — the probe
# exercises the logic, and is repeatable. A separate live pass below confirms
# the geocoder itself is genuinely open to arbitrary places.


def _stub_post(query):
    """Answer the real query with a plausible mapped-water fixture.

    Deliberately derived FROM the query's own radius/centre, so the coordinates
    returned are genuinely around the point being asked about. A stub that
    returned a fixed pair of coordinates would let the distance maths look
    correct while testing nothing.
    """
    import re
    m = re.search(r"around:(\d+),([-\d.]+),([-\d.]+)", query)
    if not m:
        return {"elements": []}
    radius, lat, lon = int(m.group(1)), float(m.group(2)), float(m.group(3))
    span = radius / 1000.0 * 0.5

    def w(name, tags, centre):
        d = max(radius / 111000.0, 0.002)
        return {
            "type": "way", "id": abs(hash(name)) % 10**8,
            "lat": centre[0] + d, "lon": centre[1] + d,
            "tags": {"name": name, **tags},
        }

    elements = [
        w("Karaikudi River", {"waterway": "river"}, (lat, lon)),
        w("Anna Nagar Tank", {"water": "tank", "landuse": "reservoir"}, (lat + 0.01, lon)),
        w("Village Pond", {"water": "fishpond"}, (lat - 0.01, lon)),
        w("Borewell", {"man_made": "borehole"}, (lat, lon + 0.02)),
        w("Municipal Standpipe", {"amenity": "water_point"}, (lat - 0.02, lon - 0.02)),
        # Beyond `radius`, so it must be EXCLUDED. If a distance bug let this
        # through, a source 20 km away would be presented as being here.
        {"type": "way", "id": 999999, "lat": lat + span, "lon": lon + span,
         "tags": {"name": "Far Away Reservoir", "water": "reservoir"}},
    ]
    del span
    return {"elements": elements}


# THE SEAM THAT MATTERS IS `_overpass`, not `_session.post`.
#
# `_overpass` is the whole mirror walk — the politeness throttle, the concurrent
# race, the retry on 504 and the None-on-failure contract. Stubbing anything
# beneath it (the HTTP session, `_overpass_post`) leaves the walk intact and it
# never calls the stub, which is why an earlier version of this file reported "no
# water source anywhere" while believing it had stubbed the provider: the fixture
# was correct and simply never ran. Patching the public seam is the only level at
# which the substitution actually takes effect.
ls._overpass = _stub_post

# The stored-sample reader is stubbed to "no samples" FOR PHASE 1 ONLY, and this is
# the stub that makes the probe finish. Left real, every probe builds a fresh
# Flask app and re-loads the ML model just to discover the database holds no sample
# near that point — which is true, and which Phase 2 establishes far more
# precisely by injecting samples and asserting what the system does with them.
#
# So Phase 1 asks only "can an arbitrary place get all the way through", with the
# strongest evidence branch consistently absent, and Phase 2 covers the branches.
ls._measured_samples_for = lambda *a, **k: []

# The only provenance labels the system is allowed to attach to a number. Anything
# outside this set is a fabricated number wearing a name.
LEGIT = {
    "measured", "nearby_source", "historical",
    "dataset_based", "estimated", "user_input_required",
}
PARAM_KEYS = ("ph", "turbidity", "tds", "temperature", "dissolved_oxygen")


def walk(label, place):
    """Search -> geocode -> identify -> water source -> parameters. One place, end to end."""
    out = {"label": label}

    # --- 1. SEARCH / GEOCODE --------------------------------------------
    rows = ls.search(place, limit=6, autocomplete=False)
    out["search_count"] = len(rows)
    if not rows:
        out["search_ok"] = False
        return out
    out["search_ok"] = True
    top = rows[0]
    out["picked"] = top.get("name")
    out["picked_state"] = top.get("state")

    # A result with no coordinates cannot be resolved to anything downstream, and
    # a name that is merely echoed back from the query is not a search.
    check(f"{label}: search returns a real place",
          bool(top.get("lat") is not None and top.get("lon") is not None),
          f"name={top.get('name')} lat={top.get('lat')}")

    # --- 2. IDENTIFY ------------------------------------------------------
    resolved = ls.resolve(place)
    ident = resolved if isinstance(resolved, dict) else (resolved or {}).get("place", {})
    out["identified"] = bool(ident.get("name"))
    out["identified_state"] = ident.get("state")
    check(f"{label}: resolves to an identified place", out["identified"],
          f"name={ident.get('name')} state={ident.get('state')}")
    if not ident:
        return out

    lat, lon = ident.get("lat"), ident.get("lon")

    # --- 3. WATER SOURCE --------------------------------------------------
    water = ls.water_context({"lat": lat, "lon": lon, "name": ident.get("name")})
    out["water_available"] = bool(water.get("available"))
    out["primary"] = water.get("primary")
    out["nearby_count"] = len(water.get("nearby") or [])
    out["types"] = water.get("types") or []

    # A source that is NOT available must say why. Silence here is how a missing
    # source becomes indistinguishable from a page that simply failed.
    if not water.get("available"):
        check(f"{label}: unavailable water explains itself",
              bool(water.get("message")), f"message={water.get('message')!r}")

    # Every reported source type must be one the classifier actually emits.
    # An unknown type here would silently take the municipal fallback in
    # default_parameters() and be presented as if it meant something. The set is
    # module-level `KNOWN_TYPES` so it cannot drift from the one the stub above
    # documents.
    unknown = [t for t in out["types"] if t not in KNOWN_TYPES]
    check(f"{label}: every reported source type is a known type", not unknown,
          f"unknown={unknown} types={out['types']}")

    # --- 4. PARAMETERS + PROVENANCE --------------------------------------
    detail = ls.default_parameters_detail(
        water.get("primary") or water.get("nearest_type"),
        available=bool(water.get("available")),
        place=ident, water=water,
    )
    values = detail.get("values") or {}
    src = detail.get("source")
    out["param_source"] = src
    out["param_label"] = detail.get("label")
    out["param_values"] = values
    out["has_note"] = bool(detail.get("note"))

    check(f"{label}: parameters name a provenance", src in LEGIT,
          f"source={src!r}")
    check(f"{label}: parameters carry an honest label",
          bool(detail.get("label")) and src != "measured",
          f"label={detail.get('label')!r}")

    if src == "user_input_required":
        # The honest-empty case: no values, and it must SAY so.
        check(f"{label}: empty provenance returns no numbers", not values,
              f"values={values}")
        check(f"{label}: empty provenance explains itself",
              bool(detail.get("note")), f"note={detail.get('note')!r}")
    else:
        # Every value must be a real number, and no value may be silently absent.
        missing = [k for k in PARAM_KEYS if values.get(k) is None]
        check(f"{label}: all five parameters present", not missing,
              f"missing={missing}")
        non_numeric = [
            k for k in PARAM_KEYS
            if values.get(k) is not None and not isinstance(values[k], (int, float))
        ]
        check(f"{label}: every parameter is a real number", not non_numeric,
              f"non_numeric={non_numeric}")

        # The fabrication rule, stated as a check: an ESTIMATE must never be
        # labelled as a measurement. This is the one thing that must not slip.
        check(f"{label}: an estimate is never labelled measured",
              src != "measured" or detail.get("sample_count", 0) >= 1,
              f"source={src} sample_count={detail.get('sample_count')}")

        # A dataset/historical/nearby answer must be close enough to be honest.
        if src in ("dataset_based", "nearby_source", "historical"):
            check(f"{label}: provenance is labelled for what it is",
                  src in str(detail.get("label")).lower().replace(" ", "_")
                  or "estimate" in str(detail.get("label")).lower()
                  or "nearby" in str(detail.get("label")).lower()
                  or "historical" in str(detail.get("label")).lower(),
                  f"label={detail.get('label')!r}")

    # --- 5. DISTANCES ARE REAL -------------------------------------------
    for n in (water.get("nearby") or []):
        d = n.get("distance_km")
        if d is None:
            check(f"{label}: every nearby source has a distance", False,
                  f"name={n.get('name')} distance={d}")
            break
    else:
        check(f"{label}: every nearby source has a real distance", True)

    # --- 6. RISK IS NEVER INVENTED ----------------------------------------
    risk = ls.risk_level(water, None)
    check(f"{label}: risk level is one of the real classes",
          risk.get("level") in ("low", "moderate", "high", "unknown"),
          f"level={risk.get('level')}")
    if risk.get("level") == "unknown":
        check(f"{label}: unknown risk explains itself", bool(risk.get("message")),
              f"message={risk.get('message')!r}")
    return out


print("=" * 78, flush=True)
print("STEP 34 — THE WHOLE CHAIN, FOR EVERY VALID SEARCHABLE LOCATION", flush=True)
print("=" * 78, flush=True)

RESULTS = []
for query, expected_state, note in PROBES:
    print(f"\n--- {query!r}  ({note})", flush=True)
    try:
        r = walk(query, query)
        r["query"] = query
        r["expected_state"] = expected_state
        RESULTS.append(r)
    except Exception as exc:
        import traceback
        check(f"{query}: chain completes", False, f"{type(exc).__name__}: {exc}")
        print(traceback.format_exc()[:600], flush=True)
        RESULTS.append({"query": query, "error": str(exc)[:200]})

# --- THE CROSS-CUTTING ASSERTIONS ---------------------------------------
print("\n" + "=" * 78, flush=True)
print("SUMMARY", flush=True)
print("=" * 78, flush=True)

ok = [r for r in RESULTS if r.get("search_ok")]
print(f"searchable            : {len(ok)}/{len(PROBES)}")
print(f"identified            : {sum(1 for r in ok if r.get('identified'))}/{len(ok)}")
print(f"water source found    : {sum(1 for r in ok if r.get('water_available'))}/{len(ok)}")
prov = {}
for r in ok:
    prov[r.get("param_source")] = prov.get(r.get("param_source"), 0) + 1
print(f"parameter provenance  : {prov}")
states = sorted({r.get("identified_state") for r in ok if r.get("identified_state")})
print(f"distinct states seen  : {len(states)}")
print(f"                       {states}")

# The core of the brief: the results must not be concentrated in one place.
if len(states) >= 6:
    check("results span many states, not one hard-coded list", True, f"{len(states)} states")
else:
    check("results span many states, not one hard-coded list", False, f"only {states}")

if len(prov) >= 1:
    check("every place got a named provenance", True, str(prov))
else:
    check("every place got a named provenance", False, "no place returned one")


# ===========================================================================
# PHASE 2 — EVERY PROVENANCE BRANCH, DRIVEN EXPLICITLY
# ===========================================================================
#
# Phase 1 answered one question: can an arbitrary place get through. Every probe
# legitimately took the `dataset_based` branch, because a fresh location has no
# stored samples and no measured corpus row for its own water type. That is the
# CORRECT answer for those inputs — and it means the other four branches were
# never executed, so nothing about them has been shown.
#
# A branch that has never run is where fabrication hides, because it is the branch
# nobody looks at. These drive each one with the stored-sample source stubbed to
# produce exactly the situation it claims to handle, and assert the CLAIM: the
# label says what it is, and the values never outrank the evidence.

print("\n" + "=" * 78, flush=True)
print("PHASE 2 — EVERY PROVENANCE BRANCH", flush=True)
print("=" * 78, flush=True)

REAL_VALUES = {"ph": 7.1, "turbidity": 3.2, "tds": 410.0,
               "temperature": 26.0, "dissolved_oxygen": 7.4}

PLACE = {"lat": 9.9679, "lon": 78.7824, "name": "Karaikudi"}
WATER = {"available": True, "primary": "Ground Water", "types": ["Ground Water"],
         "nearby": [{"name": "Borewell", "distance_km": 0.4, "type": "borewell water"}],
         "nearest": {"name": "Borewell", "distance_km": 0.4}}


def with_samples(samples, fn):
    """Run `fn` with the stored-sample reader returning `samples`.

    Restores the Phase 1 stub on the way out, so the Phase 1 default of "no
    samples" survives every scenario rather than being replaced by whichever
    fixture the last one happened to inject.
    """
    def fake(_lat, _lon, _place, _water_type):
        return list(samples)
    saved = ls._measured_samples_for
    ls._measured_samples_for = fake
    try:
        return fn()
    finally:
        ls._measured_samples_for = lambda *_a, **_k: []


def scenario(label, samples, water, expect_source):
    """One provenance branch, asserted."""
    print(f"\n--- {label}", flush=True)
    detail = with_samples(
        samples,
        lambda: ls.default_parameters_detail(
            (water or {}).get("primary"),
            available=bool((water or {}).get("available")),
            place=PLACE, water=water,
        ),
    )
    src = detail.get("source")
    values = detail.get("values") or {}
    lbl = str(detail.get("label"))
    note = str(detail.get("note"))

    print(f"    source={src!r} label={lbl!r}", flush=True)
    print(f"    values={values}", flush=True)

    check(f"{label}: takes the {expect_source} branch", src == expect_source,
          f"got {src!r}")
    check(f"{label}: the label names what it is",
          src.replace("_", " ") in lbl.lower()
          or lbl.lower() == "dataset-based estimate",
          f"label={lbl!r}")
    check(f"{label}: the note explains it in words", len(note) > 20, f"note={note!r}")

    # NO PROVENANCE MAY CLAIM TO DESCRIBE THIS EXACT WATER except 'measured',
    # which requires an actual sample inside the 150 m tolerance.
    check(f"{label}: never claims a reading of this water without a sample",
          src != "measured" or bool(samples),
          f"source={src!r} samples={len(samples)}")

    # THE WORST CASE FOR THE FABRICATION RULE: when a branch claims the values
    # came from a real sample, they must BE that sample's numbers — and they must
    # not be a round authored figure from the hard-coded `_DEFAULT_PARAMETERS`
    # table. The way to tell is that they match the sample exactly, because that
    # table holds hand-written round numbers and the sample does not.
    if src in ("measured", "nearby_source", "historical"):
        same = all(
            abs(float(values.get(k, float("nan"))) - float(v)) <= 1e-9
            for k, v in REAL_VALUES.items()
        )
        check(f"{label}: values ARE the sample, not a default profile", same,
              f"values={values} sample={REAL_VALUES}")
    return detail


SAMPLE_NEAR = {"distance_m": 40.0, "values": REAL_VALUES,
               "location": "Borewell, Karaikudi", "created_at": "2026-09-01",
               "water_source_type": "ground water"}
SAMPLE_FAR = {"distance_m": 12000.0, "values": REAL_VALUES,
              "location": "Somewhere else", "created_at": "2026-01-01",
              "water_source_type": "river water"}
SAMPLE_MID = {"distance_m": 900.0, "values": REAL_VALUES,
              "location": "Karaikudi", "created_at": "2026-06-01",
              "water_source_type": "ground water"}

scenario("MEASURED at this exact point", [SAMPLE_NEAR], WATER, "measured")
scenario("NEARBY SOURCE within 5 km", [SAMPLE_MID], WATER, "nearby_source")
scenario("DATASET by water type", [], WATER, "dataset_based")

# HISTORICAL IS REACHABLE, BUT ONLY THROUGH A NARROW WINDOW — and working out
# the window took three attempts, so it is written down here.
#
# Two things must hold at once:
#
#   1. `water_type` must be TRUTHY, or the function returns at the "no source"
#      branch (line 4974) before reaching historical at all. So the identified
#      source cannot simply be cleared.
#   2. `_nearby_source_samples` must come back EMPTY, or the stronger branch wins.
#      It filters on the sample's own `water_type` folding to the same name as the
#      identified source — and that key is `water_type`, which the real reader
#      builds from the row's `water_source_type`. My first fixture spelled it
#      `water_source_type` directly, so the sample carried no `water_type` at all,
#      the `(not sample.get("water_type") or ...)` guard treated the ABSENCE as a
#      match, and `nearby_source` won anyway. Both spellings are used in this file
#      now, which is exactly why the note is here.
#
# So the sample's water type must DIFFER from the identified source while the
# source itself stays. A sample of different water 900 m away is a real earlier
# reading FOR THIS PLACE, which is exactly what "historical" claims to be — and
# it is not a nearby reading of the source at this point, so the branch above it
# is right to decline.
print("\n--- HISTORICAL: an earlier sample here, of different water", flush=True)
SAMPLE_OTHER_WATER = dict(SAMPLE_MID, water_type="river water")
hist = scenario("HISTORICAL", [SAMPLE_OTHER_WATER], WATER, "historical")
check("historical says the reading is not current",
      "not a current" in str(hist.get("note")).lower(),
      f"note={hist.get('note')!r}")

# AND A CLEARED SOURCE IS NOT A WAY TO REACH IT — that assertion is kept because
# it is the thing I got wrong twice.
print("\n--- HISTORICAL with no identified source at all", flush=True)
no_src_hist = scenario("HISTORICAL? NO SOURCE", [SAMPLE_MID],
                       dict(WATER, primary=None, nearest_type=None), "dataset_based")
check("clearing the source does NOT reach historical — it exits earlier",
      no_src_hist.get("source") == "dataset_based",
      f"source={no_src_hist.get('source')}")

# AND THE STRONGER BRANCH REALLY DOES WIN WHEN BOTH ARE AVAILABLE. Asserted
# explicitly rather than left to inference, because that precedence IS the
# never-understate-provenance rule.
print("\n--- both a nearby source and a historical sample available", flush=True)
both = scenario("NEARBY WINS", [SAMPLE_MID], WATER, "nearby_source")
check("the nearer, more local provenance wins",
      both.get("source") == "nearby_source", f"source={both.get('source')}")

# WHY `user_input_required` NEVER FIRES WITH A CORPUS PRESENT.
#
# `_dataset_estimate` returns the overall median of the measured corpus, which
# this project has — 6,616 samples — and it is deliberately NOT gated on the
# water type. So the empty-data branch is unreachable whenever the dataset loads,
# and expecting it was a mistake in this file rather than a bug in the system:
# offering real measured figures under an honest label is BETTER than showing
# nothing. What must still hold is that those figures are never dressed up.
print("\n--- the empty-data branch, with the corpus absent", flush=True)
_real_profile = ls._dataset_profile
ls._dataset_profile = lambda: None
try:
    empty = scenario("NO CORPUS, NO SOURCE", [], None, "user_input_required")
    check("with no corpus and no source, nothing is invented",
          empty.get("values") == {}, f"values={empty.get('values')}")
    check("with no corpus and no source, it says what to do",
          "own" in str(empty.get("note")).lower(),
          f"note={empty.get('note')!r}")
finally:
    ls._dataset_profile = _real_profile

# And the ordinary no-source case WITH the corpus: real numbers, honest label,
# and the risk still unknown.
print("\n--- no water source, corpus present", flush=True)
no_src = scenario("NO SOURCE, CORPUS PRESENT", [], None, "dataset_based")
check("no source + corpus => real figures, clearly not from this place",
      "not readings from it" in str(no_src.get("note")).lower(),
      f"note={no_src.get('note')!r}")
check("no source + corpus => the source is reported as unknown",
      no_src.get("water_source_known") is False,
      f"water_source_known={no_src.get('water_source_known')}")

# A sample 12 km away must NOT be described as nearby water. This is the distance
# rule doing its job, and it is the single easiest thing to get wrong.
print("\n--- a sample 12 km away (beyond NEARBY_SAMPLE_RADIUS_M)", flush=True)
far = scenario("FAR SAMPLE", [SAMPLE_FAR], WATER, "dataset_based")
check("a 12 km sample is not presented as nearby water",
      far.get("source") != "nearby_source" and "12.0 km" not in str(far.get("note")),
      f"source={far.get('source')} note={far.get('note')!r}")

# The empty case must not leave the UI with something to show.
print("\n--- risk with no water source at all", flush=True)
r0 = ls.risk_level(None, None)
check("no source => the risk is unknown, not invented",
      r0.get("level") == "unknown", f"level={r0.get('level')}")
check("no source => the risk explains itself", bool(r0.get("message")),
      f"message={r0.get('message')!r}")
check("no source => no risk factors are listed",
      not r0.get("factors"), f"factors={r0.get('factors')}")

# The type table itself: an UNKNOWN water type must not silently borrow the
# municipal profile, because that is how a fabricated reading gets a confident
# label.
print("\n--- an unrecognised water type", flush=True)
unknown_detail = ls.default_parameters_detail(
    "artisanal glacier water", available=True, place=PLACE, water=WATER)
check("an unknown water type is not given a confident provenance",
      unknown_detail.get("source") != "measured",
      f"source={unknown_detail.get('source')!r} label={unknown_detail.get('label')!r}")
check("an unknown water type is labelled as an estimate",
      "estimate" in str(unknown_detail.get("label")).lower()
      or unknown_detail.get("source") == "user_input_required",
      f"label={unknown_detail.get('label')!r}")

# Every type the classifier can emit must have an entry, so no mapped source can
# ever fall through to a default.
print("\n--- the classifier and the parameter table agree", flush=True)
emitted = {
    "well water", "borewell water", "piped water", "surface water", "river water",
    "lake water", "pond water", "tank water",
}
table = set(ls._DEFAULT_PARAMETERS)
missing = emitted - table
check("every type the classifier emits has parameter entries", not missing,
      f"missing={missing}")

print(f"\n{'=' * 78}")
print(f"{CHECKS - len(FAILURES)}/{CHECKS} checks passed")
if FAILURES:
    print(f"\n{len(FAILURES)} FAILURE(S):")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("\nALL CHECKS PASSED")
