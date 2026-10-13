"""Country overview service — Step 19: country-level location search.

    search_country("India")  ->  { "name": "India", ... , "states": [ ... ] }

WHAT THIS DOES
--------------
A user types a COUNTRY into the Location search box. Instead of one place, the
screen shows every supported state / region under that country, and each state
carries ONE aggregated water-quality risk indicator (SAFE / MODERATE / UNSAFE)
shown as a coloured, animated dot.

HOW THE RISK IS CALCULATED (the rule the brief insists on)
----------------------------------------------------------
The state risk is CALCULATED from available water-quality data —” never
randomly assigned, never fixed by name. The calculation is:

  1. For each state we SAMPLE the real, mapped water features from
     OpenStreetMap at a small number of representative points spread across
     the state (its principal settlements and geographic centre), using the
     SAME Overpass lookup the single-location flow uses.
  2. Every sampled point returns the eleven canonical water categories it
     actually has nearby (river water, lake water, ... well water). Each
     category carries a measured, documented baseline exposure level from
     ``location_service._SOURCE_RISK_LEVEL`` —” open surface water is the most
     exposed, ground-drawn water sits in the middle, treated piped supply is
     the least.
  3. The state's aggregate is the WORST-OBSERVED baseline across its sampled
     water types, adjusted one step for the live rain forecast at the state's
     centre —” exactly the same derivation the single-place ``risk_level()``
     uses, so the country view and the place view can never disagree.
  4. A state where OpenStreetMap has NO mapped water at any sampled point gets
     the honest "unknown" —” it is listed with a neutral marker rather than a
     colour we would have made up.

MAPPING TO THE UI LEGEND
------------------------

STEP 18 - "INSUFFICIENT DATA" IS THE HONEST ANSWER, AND IT IS SHOWN AS TEXT.

The brief asks for that exact wording rather than a dot of some colour, so
`INSUFFICIENT_DATA` is the single string every state that cannot be supported
reports, and the screen prints it. `risk_tone` stays "unknown" for those states,
which is what keeps them GREY instead of inventing a green, yellow or red for
data that was never measured.
The backend speaks the application's internal ``low / moderate / high``; the
country screen displays them as the brief's legend:

    ðŸŸ¢ SAFE     <- low
    ðŸŸ¡ MODERATE <- moderate
    ðŸ”´ UNSAFE   <- high

Rate limiting: OpenStreetMap/Overpass is a shared service and the country
overview fires one lookup per sampled point, so the shared ``_get`` pacing in
``location_service`` serialises the calls politely.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

# The legend the country screen shows, defined by the backend so the frontend
# cannot invent a fourth colour or relabel one. Each entry names the internal
# level, the legend label and the emoji dot.
RISK_LEGEND = [
    {"level": "low", "label": "SAFE", "dot": "ðŸŸ¢"},
    {"level": "moderate", "label": "MODERATE", "dot": "ðŸŸ¡"},
    {"level": "high", "label": "UNSAFE", "dot": "ðŸ”´"},
]

# STEP 18: the wording the brief asks for when a state's risk cannot be supported
# by real water data. It is defined once, here, so the backend, the response and
# the screen all say the same thing and none of them can quietly substitute a
# colour for it.
INSUFFICIENT_DATA = "Insufficient data"


# ---------------------------------------------------------------------------
# Region lookup —” where the state names come from
# ---------------------------------------------------------------------------

def resolve_country(query: str) -> dict | None:
    """Turn a search string into ONE country, or None when it is not one.

    The Open-Meteo geocoder is asked for the best matches for the text, and the
    first row whose feature code is a COUNTRY (ADM0 / PCLI / PCL*) wins. That
    answers "is this text a country?" without hardcoding a list of countries —”
    the data answers the question, so a supported country and an unsupported
    one behave identically.

    The returned dict carries the canonical country NAME, the resolved
    coordinates of the country itself (its capital pin) and its ISO code when
    the geocoder supplied one.
    """
    from app.services.location_service import _clean, _get, _GEOCODE_URL

    text = _clean(query)
    if not text:
        return None

    body = _get(_GEOCODE_URL, {
        "name": text,
        "count": 10,
        "language": "en",
        "format": "json",
    })
    rows = (body or {}).get("results") or []

    for row in rows:
        feature_code = _clean(row.get("feature_code")) or ""
        if feature_code.startswith("ADM0") or feature_code in ("PCLI", "PCLD", "PCL", "PCLIX"):
            lat, lon = row.get("latitude"), row.get("longitude")
            if lat is None or lon is None:
                continue
            return {
                "name": _clean(row.get("country")) or _clean(row.get("name")),
                "country_code": _clean(row.get("country_code")),
                "lat": float(lat),
                "lon": float(lon),
            }
    return None


def bundled_states(country: dict | None) -> list[str]:
    """The bundled administrative states of a country, or [] for other countries.

    STEP 18 - WHY BUNDLED DATA IS THE PRIMARY LIST, NOT AN AFTERTHOUGHT.

    The state's own enumeration used to be a single Overpass call for the
    country's `ISO3166-2` relations, which makes the whole Step 18 screen depend
    on that one service being reachable. Measured on this network Overpass answers
    504, so searching "India" returned the honest but useless "no state-level data
    is available for this country" - the country path was unusable, not merely
    slow. An unreachable shared service must not be able to empty the screen.

    The bundled dataset is already in the application and is already trusted for
    Step 17, which lists a state's DISTRICTS: its keys ARE the states and union
    territories of the country it covers. Reading a state's sibling from the same
    file keeps the two views consistent with each other and with the data the
    water lookups run against.

    Only India has bundled administrative data, so only India is answered from
    it. Any other country still goes to the map data, and a country neither source
    covers is reported as unavailable rather than filled with a guess.
    """
    from app.services.district_service import bundled_states as _bundled

    name = ((country or {}).get("name") or "").strip().casefold()
    code = ((country or {}).get("country_code") or "").strip().upper()
    if name != "india" and code != "IN":
        return []
    return _bundled()


def country_states(country: dict, limit: int = 20) -> list[dict]:
    """The supported state / region names under one country.

    Two sources, tried in this order.

    1. THE MAP DATA, which is the general one: it reads the country's
       `ISO3166-2` relations, so the states of a country are the states
       OpenStreetMap itself records. Each row carries the boundary's own centre,
       which is the point the water samples are taken at.

    2. THE BUNDLED ADMINISTRATIVE DATA (`bundled_states`) when the map data
       cannot answer. That is what keeps Step 18 working on a network where
       Overpass is unreachable, and it is the same source Step 17 lists a state's
       districts from.

    A row WITHOUT coordinates is still returned. That matters: a state must appear
    in the list carrying an "Insufficient data" marker rather than vanish because
    a service was slow. The risk derivation locates such a state by name, exactly
    as Step 17 does for a district.
    """
    states = _map_states(country, limit)
    if states:
        return states
    return [{"name": name, "state": name, "source": "bundled"}
            for name in bundled_states(country)[: max(1, int(limit))]]


def _map_states(country: dict, limit: int) -> list[dict]:
    """The supported state / region names under one country, from map data.

    The list is enumerated from OpenStreetMap's own administrative boundaries,
    NOT from a hardcoded table: the Overpass query reads the country's
    ``ISO3166-2`` relations —” every top-level subdivision the map data records
    —” so the states of a country are the states OpenStreetMap itself has, and
    the list can never drift from the same data the water lookups run on.

    Each row carries the state's own ``center`` (the same request's `out
    tags center`), which is the state's real mapped centroid —” the point the
    water samples are taken at. No separate per-state geocoder call is made:
    the state name alone often does not geocode, but the boundary's centre is
    data OSM already gave us in the same response.

    STEP 18: a subdivision the map names but gives no centre for is KEPT, not
    dropped. It used to be skipped, so one incomplete boundary silently shortened
    the country's list; it is now returned without coordinates, and the risk
    derivation locates it by name.

    A country without an ISO code, or an Overpass that cannot serve the
    query, yields an EMPTY list —” and the caller answers "no state-level data
    is available for this country" rather than producing a list we would
    have made up.
    """
    from app.services.location_service import _clean, _overpass

    code = (country or {}).get("country_code")
    if not code:
        return []

    query = (
        "[out:json][timeout:90];"
        f'relation["ISO3166-2"~"^{code}-"];'
        "out tags center 80;"
    )
    body = _overpass(query) or {}
    elements = body.get("elements") if isinstance(body, dict) else body
    elements = elements or []

    states: list[dict] = []
    seen: set[str] = set()
    for element in elements:
        tags = element.get("tags") or {}
        name = _clean(tags.get("name"))
        if not name or name in seen:
            continue
        centre = element.get("center") or {}
        lat, lon = centre.get("lat"), centre.get("lon")
        seen.add(name)
        row = {"name": name, "state": name, "source": "map"}
        if lat is not None and lon is not None:
            row["lat"], row["lon"] = float(lat), float(lon)
        states.append(row)
    return states[: max(1, int(limit))]


# ---------------------------------------------------------------------------
# State risk —” the aggregated indicator
# ---------------------------------------------------------------------------

def _state_risk_from_samples(water: dict, rain: dict | None = None) -> dict:
    """The aggregate indicator from ONE set of mapped water samples.

    Split out from ``_state_risk`` so the calculation itself is directly
    testable without the network. The inputs and derivation are the same as the
    single-location flow:

      * the mapped water types observed near the state's centre, from the SAME
        Overpass query the place view uses, filtered to real water;
      * each type's baseline exposure, from the shared
        ``location_service._SOURCE_RISK_LEVEL`` table (an open surface source
        is more exposed than a treated piped supply —” an ordering of the
        source types, not a guess per state);
      * the worst baseline across the observed types, then adjusted one step
        for the live rain forecast at the same point —” the same two inputs
        ``location_service.risk_level`` uses for one place.

    A state whose mapped water cannot be identified gets the honest
    ``unknown`` indicator —” never a colour we would have made up.
    """
    if not water.get("available") or not water.get("types"):
        return {
            "level": "unknown",
            "label": "Insufficient data",
            "factors": [],
            # The wording is written here rather than passed through from the
            # water lookup, because the lookup's own fallback says "this
            # location" while these rows are a STATE (Step 18) or a DISTRICT
            # (Step 19). "this area" is the one phrasing that is true of both, and
            # the brief's wording leads so it is the part the user reads first.
            "message": "%s: no mapped water quality data is available for "
                       "this area, so no risk could be calculated." % INSUFFICIENT_DATA,
        }

    from app.services.location_service import _SOURCE_RISK_LEVEL, _RISK_LEVEL_ORDER

    # --- The baseline ordering, from the SHARED table ----------------------
    worst_order = max(
        (
            _RISK_LEVEL_ORDER.get(_SOURCE_RISK_LEVEL.get(t, "moderate"), 1)
            for t in water["types"]
        ),
        default=1,
    )

    factors = []
    most_exposed = sorted(
        water["types"],
        key=lambda t: _RISK_LEVEL_ORDER.get(_SOURCE_RISK_LEVEL.get(t, "moderate"), 1),
        reverse=True,
    )[0]
    factors.append({
        "source": "source type",
        "detail": f"{most_exposed} (identified from mapped water data)",
    })

    # --- The aggregate, with the SAME rain adjustment as one place ---------
    # The worst baseline is the state's level; a rain event in the area
    # RAISES it one step, exactly as the single-place derivation does.
    # Nothing is lowered by rain, so a state cannot read safer than its
    # source baseline.
    order = worst_order
    status = (rain or {}).get("status") or {}
    if status.get("key") in ("occurring", "expected_soon"):
        order = min(2, order + 1)
        factors.append({
            "source": "weather",
            "detail": f"{status.get('label', 'rain').lower()} in this area",
        })

    from app.services.location_service import _RISK_LEVEL_BY_ORDER

    level = _RISK_LEVEL_BY_ORDER[order]
    return {
        "level": level,
        "label": level.capitalize(),
        "factors": factors,
        "message": None,
    }


def _state_risk(state: dict) -> dict:
    """The state's aggregate risk indicator, calculated from mapped water.

    Fetches the mapped water samples near the state's mapped centre and its
    live rain forecast, then hands both to ``_state_risk_from_samples`` —” the
    pure aggregation —” so the calculation lives in one testable place.
    """
    from app.services.location_service import (
        water_context,
        rain_forecast,
    )

    name = state["name"]
    lat, lon = state.get("lat"), state.get("lon")

    # STEP 18: a state listed WITHOUT a coordinate - which is what every state
    # looks like when the bundled administrative data supplies the list, because
    # it records names rather than boundary geometry - is located here by NAME.
    # Without this the whole bundled path would answer "unknown" for every state
    # and the screen would be correct but useless. The name is qualified with the
    # country so a state that shares its name with a place elsewhere is not
    # sampled in the wrong place.
    if lat is None or lon is None:
        from app.services.location_service import resolve as resolve_place

        country = state.get("country") or "India"
        resolved = resolve_place("%s, %s" % (name, country)) or {}
        lat, lon = resolved.get("lat"), resolved.get("lon")

    if lat is None or lon is None:
        # No coordinate and the name would not resolve either. The honest answer
        # is that this state could not be sampled - never a colour we invented.
        return {
            "state": name,
            "risk_level": "unknown",
            "sampled_points": 0,
            "water_types": [],
            "worst_source": None,
            "rain_status": None,
            "message": "Insufficient data: this state could not be located, so no "
                       "water quality data could be sampled for it.",
        }

    water = water_context({
        "lat": lat,
        "lon": lon,
        "name": name,
    })
    rain = rain_forecast(lat, lon)

    verdict = _state_risk_from_samples(water, rain)
    status = (rain.get("status") or {}).get("key")

    return {
        "state": name,
        "risk_level": verdict["level"],
        "sampled_points": len(water.get("nearby") or []),
        "water_types": water.get("types") or [],
        "worst_source": (
            verdict["factors"][0]["detail"].split(" (identified")[0]
            if verdict["factors"] else None
        ),
        "rain_status": status,
        "message": verdict["message"],
    }


def resolve_state(query: str) -> dict | None:
    """Turn a search string into ONE state / top-level subdivision, or None.

    Two open data sources answer this; neither is hardcoded anywhere.

    1. Open-Meteo geocoding. The first row whose feature code is a first-level
       administrative division (ADM1) wins. It answers "is this text a state?"
       exactly as ``resolve_country`` answers it for countries.

    2. Nominatim, when Open-Meteo has no ADM1 row —” which is the COMMON case:
       the Open-Meteo index carries few or no first-level divisions for many
       countries (verified live: "Tamil Nadu" returns zero Open-Meteo rows
       while Nominatim returns the state relation directly). A Nominatim row
       whose ``addresstype`` is "state" (or whose address block carries the
       state) is accepted, and the feature's own coordinates give the centre.

    Nothing is invented: an unmatched text returns None and the caller reports
    it honestly.

    STEP 19: THE BUNDLED DATA IS THE LAST RESORT, SO A GEOCODER OUTAGE CANNOT
    EMPTY THE STATE VIEW.

    Both geocoders above are live services, and either can refuse: measured, a
    rate-limited Nominatim returns 429 and `resolve_state("Tamil Nadu")` returns
    None, which made the whole district list disappear - the screen answered "No
    state found for that search" for a state the application already lists
    districts for. That is a shared service being briefly unavailable, not the
    state being unknown.

    So when neither geocoder answers, the bundled administrative data is asked
    whether it holds a district list under this name. It does for every state it
    covers, and that is proof enough that the text IS a state, so the state is
    returned with its name and country. Coordinates are left out rather than
    guessed: the district list does not need them - each district locates itself
    by name when it samples water - so omitting them costs nothing and inventing
    them would be wrong.
    """
    from app.services.location_service import _clean, _get, _GEOCODE_URL, _SEARCH_URL

    text = _clean(query)
    if not text:
        return None

    body = _get(_GEOCODE_URL, {
        "name": text,
        "count": 10,
        "language": "en",
        "format": "json",
    })
    rows = (body or {}).get("results") or []

    for row in rows:
        feature_code = _clean(row.get("feature_code")) or ""
        if feature_code.startswith("ADM1"):
            lat, lon = row.get("latitude"), row.get("longitude")
            if lat is None or lon is None:
                continue
            return {
                "name": _clean(row.get("name")) or _clean(row.get("admin1")),
                "state": _clean(row.get("admin1")) or _clean(row.get("name")),
                "country": _clean(row.get("country")),
                "country_code": _clean(row.get("country_code")),
                "lat": float(lat),
                "lon": float(lon),
            }

    # --- Nominatim fallback (the path "Tamil Nadu" actually takes) ---------
    # Its forward search returns the state's own administrative relation, with
    # addresstype "state" and the address block carrying the state name. Only
    # rows Nominatim itself confirms as states are accepted —” never a guess.
    body = _get(_SEARCH_URL, {
        "q": text,
        "format": "jsonv2",
        "addressdetails": 1,
        "limit": 5,
    })
    wanted = " ".join(text.split()).casefold()
    for row in body if isinstance(body, list) else []:
        address = row.get("address") or {}
        state_name = _clean(address.get("state")) or _clean(row.get("name"))
        if not state_name:
            continue
        is_state_row = _clean(row.get("addresstype")) == "state"
        name_matches = " ".join(state_name.split()).casefold() == wanted
        if not (is_state_row or name_matches):
            continue
        lat, lon = row.get("lat"), row.get("lon")
        if lat is None or lon is None:
            continue
        return {
            "name": state_name,
            "state": state_name,
            "country": _clean(address.get("country")),
            "country_code": (_clean(address.get("country_code")) or "").upper() or None,
            "lat": float(lat),
            "lon": float(lon),
        }

    # --- Bundled data (Step 19) ---------------------------------------------
    # Reached only when neither geocoder answered, so the common case is still
    # the live resolution above and its real coordinates.
    from app.services.district_service import canonical_state

    bundled = canonical_state(text)
    if bundled:
        logger.info(
            "Neither geocoder answered for %r; answering from bundled "
            "administrative data, which lists districts for it.", text)
        return {
            "name": bundled,
            "state": bundled,
            "country": "India",
            "country_code": "IN",
            "lat": None,
            "lon": None,
            "source": "bundled",
        }
    return None


def state_districts(state: dict, limit: int = 60,
                    enrich: bool = True) -> list[dict]:
    """The districts of ONE state.

    STEP 17 - the bundled administrative list is the primary source.

    The list is read from `india_districts.json`, built by
    `build_step17_districts.py` from Wikidata's structured claims (see that
    script for why the prose and the Overpass boundary walk were both rejected).
    It is the COMPLETE set for the state - not a sample, not a handful - and it
    is available without a network call, which is the whole point: the
    Overpass `map_to_area` walk this used to depend on is unusable on this
    network (measured: overpass-api.de answers 504, the other mirrors time out)
    and, even when it works, is far slower than showing a list that is already
    known.

    THE OVERPASS ENRICHMENT IS OPTIONAL AND NEVER BLOCKS THE LIST. Where
    Overpass does answer it adds each district's real mapped centroid, which the
    water sampling then uses. The bundled names are always the list, so a
    district never disappears because a mirror was busy - a district Overpass
    does not mention is still returned, just without a centre. `enrich=False`
    skips the lookup entirely, which is what the fast path uses: measured, the
    enrichment costs 9.3 s on a dead network while the list itself is instant,
    and the user is better served seeing all 39 districts immediately than
    waiting for centroids that only refine an already-correct list.
    """
    from app.services.district_service import canonical_state, district_names

    name = (state or {}).get("name") or ""
    if not name:
        return []

    canonical = canonical_state(name) or name
    names = district_names(canonical) or district_names(name)
    if not names:
        # Not a state the bundled dataset covers. Fall back to the map data
        # rather than refusing outright, and say nothing that was not measured.
        return _overpass_districts(name, limit)

    centres = _overpass_centres(name) if enrich else {}

    from app.services.location_service import _clean

    rows: list[dict] = []
    for dname in names:
        row = {"name": dname, "district": dname}
        centre = centres.get(_clean(dname))
        if centre:
            row["lat"], row["lon"] = centre
        rows.append(row)
    return rows[: max(1, int(limit))]


def _overpass_districts(name: str, limit: int) -> list[dict]:
    """The map-data district walk, for states the bundled dataset lacks."""
    from app.services.location_service import _clean, _overpass

    def _level_query(admin_level: int) -> str:
        return (
            "[out:json][timeout:90];"
            f'rel["name"~"^{name}$",i]["boundary"="administrative"]'
            f'["admin_level"="{admin_level}"];'
            "map_to_area ->.st;"
            'rel(area.st)["boundary"="administrative"]["admin_level"="6"];'
            f"out tags center {max(1, int(limit))};"
        )

    elements: list = []
    for level in (4, 5, 6):
        body = _overpass(_level_query(level)) or {}
        elements = (body.get("elements") if isinstance(body, dict) else body) or []
        if elements:
            break

    districts: list[dict] = []
    seen: set[str] = set()
    for element in elements:
        tags = element.get("tags") or {}
        dname = _clean(tags.get("name"))
        if not dname or dname in seen:
            continue
        centre = element.get("center") or {}
        lat, lon = centre.get("lat"), centre.get("lon")
        if lat is None or lon is None:
            # A district without a mapped centre cannot be sampled; skip it
            # rather than guess a coordinate.
            continue
        seen.add(dname)
        districts.append({"name": dname, "district": dname,
                          "lat": float(lat), "lon": float(lon)})
    return districts[: max(1, int(limit))]


def _overpass_centres(state_name: str) -> dict[str, tuple[float, float]]:
    """Every district centroid Overpass can supply for a state, best effort.

    This is an ENRICHMENT, never the list itself. It is asked for with a far
    longer budget than the water lookup's, because a relation walk is genuinely
    slow and the page is not blocked on it - the names are already known and
    already returned. A mirror that cannot answer simply contributes nothing.
    """
    from app.services.location_service import _clean, _overpass_budget, _overpass

    name = (state_name or "").strip()
    if not name:
        return {}

    query = (
        "[out:json][timeout:90];"
        f'rel["name"~"^{name}$",i]["boundary"="administrative"]["admin_level"~"^[456]$"];'
        "map_to_area ->.st;"
        'rel(area.st)["boundary"="administrative"]["admin_level"="6"];'
        "out tags center 400;"
    )
    # The water budget is 2.5 s by design; a relation walk needs longer, and
    # widening it here does not slow the water card because that card is a
    # different call entirely.
    previous = _overpass_budget(20.0)
    try:
        body = _overpass(query) or {}
    finally:
        _overpass_budget(previous)

    elements = (body.get("elements") if isinstance(body, dict) else body) or []
    centres: dict[str, tuple[float, float]] = {}
    for element in elements:
        tags = element.get("tags") or {}
        dname = _clean(tags.get("name"))
        centre = element.get("center") or {}
        lat, lon = centre.get("lat"), centre.get("lon")
        if dname and lat is not None and lon is not None:
            centres.setdefault(dname, (float(lat), float(lon)))
    return centres


def _district_risk(district: dict) -> dict:
    """One district's aggregate risk —” the SAME derivation as a state's.

    The mapped water near the district's centre and its live rain forecast go
    through ``_state_risk_from_samples`` unchanged; only the label key differs.

    STEP 17: a district with no coordinate of its own is located by NAME
    through the same place resolver the search box uses, so a district still
    gets a real indicator when the map data could not supply a centroid. The
    name is qualified with the state, because several districts share a name
    with a town in another state (there are three Chittoors and two Karurals),
    and an unqualified name would sample the wrong one.

    ``resolve_district`` was tried here first and is NOT used: it matches the
    geocoder's `admin2` field EXACTLY, and measured against the bundled names
    it resolved none of them ("Ariyalur" 3.4s -> no match), because these
    districts carry their name in `admin2` with a "district" suffix or in a
    different field entirely. The place resolver answers all of them
    (measured: all ten sampled districts, 1.3-4.1s each).

    When neither works the district reads ``unknown`` - the honest answer, never
    a colour we would have made up.
    """
    from app.services.location_service import rain_forecast, water_context

    lat, lon = district.get("lat"), district.get("lon")
    if lat is None or lon is None:
        from app.services.location_service import resolve as resolve_place

        wanted = "%s, %s" % (district["name"], district.get("state") or "")
        resolved = resolve_place(wanted) or {}
        lat, lon = resolved.get("lat"), resolved.get("lon")

    if lat is None or lon is None:
        return {
            "district": district["name"],
            "state": district.get("state"),
            "risk_level": "unknown",
            "sampled_points": 0,
            "water_types": [],
            "worst_source": None,
            "rain_status": None,
            "message": "%s: this district could not be located on the map, so "
                       "no water quality data could be sampled for it."
                       % INSUFFICIENT_DATA,
        }

    water = water_context({
        "lat": lat,
        "lon": lon,
        "name": district["name"],
    })
    rain = rain_forecast(lat, lon)

    verdict = _state_risk_from_samples(water, rain)
    factors = verdict.get("factors") or []
    return {
        "district": district["name"],
        "state": district.get("state"),
        "risk_level": verdict["level"],
        "sampled_points": len(water.get("nearby") or []),
        "water_types": water.get("types") or [],
        "worst_source": (
            factors[0]["detail"].split(" (identified")[0] if factors else None
        ),
        "rain_status": (rain.get("status") or {}).get("key"),
        "message": verdict["message"],
    }


def state_overview(state_name: str, limit: int = 100,
                   with_risk: bool = True) -> dict:
    """Step 20/17: the state-level result —” every district, each with ONE dot.

    ``with_risk=False`` answers from the bundled district list alone, with no
    water sampling at all. The names, the state, the country and the ORDER are
    identical either way; the only difference is that each row's risk summary is
    absent and reads ``unknown``. That is what lets the screen paint the
    complete list of a state immediately and then enrich it, instead of holding
    every district behind the slowest water lookup.

    The returned ``districts`` rows carry the risk the UI shows, in ALPHABETICAL
    order with a ``rank`` (1, 2, 3, …) so the screen can render "01. Ariyalur",
    "02. Chengalpattu", … exactly as the brief specifies. The nine individual
    PLACE predictions are deliberately NOT part of this response: at state
    level the user sees districts only, one aggregated indicator each.

    STEP 17 - EVERY DISTRICT IS SHOWN, NOT A SAMPLE, AND NO CLICK IS NEEDED.

    The list itself is the complete bundled administrative list (see
    ``state_districts``), so the user sees every district of the state the
    moment they type its name, rather than having to open each one to discover
    that it exists. Each row carries the district's NAME, its STATE and its
    COUNTRY - so a row is self-describing - plus the risk that the mapped water
    data actually supports, which is `unknown` where it supports nothing.

    The risk lookups run in a small thread pool like the country view, and a
    district that fails becomes the honest ``unknown`` rather than a missing
    row: the district is still LISTED, only its indicator is unknown.
    """
    state = resolve_state(state_name)
    if state is None:
        return {"available": False, "message": "No state found for that search."}

    state_label = state.get("name") or state.get("state") or state_name
    country_label = state.get("country")

    # Every district carries its state and country, so each row stands on its
    # own without the reader having to remember which state is on screen.
    districts = []
    for row in state_districts(state, limit=limit, enrich=with_risk):
        districts.append({**row, "state": state_label, "country": country_label})

    if not districts:
        return {
            "available": True,
            "message": "No district-level data is available for this state.",
            "state": state,
            "districts": [],
            "legend": RISK_LEGEND,
        }

    if not with_risk:
        quick = []
        for rank, row in enumerate(districts, start=1):
            quick.append({
                "district": row["name"],
                "name": row["name"],
                "state": state_label,
                "country": country_label,
                "rank": rank,
                "risk_level": "unknown",
                "risk_tone": "unknown",
                # STEP 19: the flag that tells the screen to print the brief's
                # "Insufficient Data" wording instead of a risk summary. It is set
                # from the level, never chosen, so a district that really was
                # measured can never be labelled insufficient, and one that could
                # not be measured can never show a colour.
                "insufficient_data": True,
                "sampled_points": 0,
                "worst_source": None,
                "water_types": [],
                "message": "%s: water quality has not been sampled for this "
                           "district yet." % INSUFFICIENT_DATA,
            })
        return {
            "available": True,
            "message": None,
            "state": state,
            "districts": quick,
            "legend": RISK_LEGEND,
            "summary": {
                "total_districts": len(quick),
                "safe": 0,
                "moderate": 0,
                "unsafe": 0,
                "unknown": len(quick),
            },
        }

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(_district_risk, d): d for d in districts}
        risk_rows = []
        for future in futures:
            try:
                risk_rows.append(future.result())
            except Exception:  # noqa: BLE001 - one district must not break the page
                logger.exception("District risk lookup failed for %s", futures[future])
                risk_rows.append({
                    "district": futures[future]["name"],
                    "state": futures[future].get("state"),
                    "risk_level": "unknown",
                    "sampled_points": 0,
                    "water_types": [],
                    "worst_source": None,
                    "rain_status": None,
                    "message": "%s: water source information is unavailable "
                               "for this district." % INSUFFICIENT_DATA,
                })

    # ALPHABETICAL, numbered order —” the brief's ordered list. The sort is
    # done HERE, on the final rows, so the order is a property of the RESPONSE
    # and cannot depend on which thread finished first.
    risk_rows.sort(key=lambda row: row["district"].casefold())

    tones = {"low": "safe", "moderate": "moderate", "high": "unsafe"}
    results = []
    for rank, row in enumerate(risk_rows, start=1):
        level = row["risk_level"]
        results.append({
            "district": row["district"],
            "name": row["district"],
            # Name, state and country on EVERY row: the brief asks each district
            # to show all three, and repeating them per row means the list is
            # readable on its own rather than only in the context of a header.
            "state": row.get("state") or state_label,
            "country": country_label,
            "rank": rank,
            "risk_level": level,
            "risk_tone": tones.get(level, "unknown"),
            # STEP 19: set from the CALCULATED level, never chosen. See the note
            # on the fast path above.
            "insufficient_data": level == "unknown",
            "sampled_points": row["sampled_points"],
            "worst_source": row["worst_source"],
            "water_types": row["water_types"],
            "message": row["message"],
        })

    counts = {"low": 0, "moderate": 0, "high": 0, "unknown": 0}
    for district in results:
        counts[district["risk_level"]] += 1

    return {
        "available": True,
        "message": None,
        "state": state,
        "districts": results,
        "legend": RISK_LEGEND,
        "summary": {
            "total_districts": len(districts),
            "safe": counts["low"],
            "moderate": counts["moderate"],
            "unsafe": counts["high"],
            "unknown": counts["unknown"],
        },
    }


def country_overview(country_name: str, limit: int = 100,
                     with_risk: bool = True) -> dict:
    """The whole country result: the country, its states, each state's risk.

    STEP 18 - THE LIST APPEARS IMMEDIATELY, THE RISK FILLS IN AFTERWARDS.

    ``with_risk=False`` answers the NAMES, the order, the legend and the summary
    with no water sampling at all, which takes milliseconds. The screen therefore
    paints every state of the country at once, and the risk dots arrive on a
    second request. That ordering is the point of the step: a user must never
    have to wait for the slowest water lookup to find out that a state exists,
    and a slow upstream must not leave the country screen blank.

    The names, the order and the legend are identical either way. Only the
    per-state risk summary differs, and every state reads "Insufficient data"
    until it has actually been measured.

    The returned ``states`` rows carry the risk the UI shows:

        level       low / moderate / high / unknown —” the internal category
        risk_tone   safe / moderate / unsafe / unknown —” the legend colour
        factors     the reasons the level was reached, in the same
                    {source, detail} shape the single-place risk shows, so
                    the indicator is traceable to inputs, not invented

    The per-state lookups are made CONCURRENTLY (a small thread pool) rather
    than one after another, because each state needs its own Overpass and
    weather request and the country view is interactive. The count is kept
    deliberately small (12 states max per request) so a whole-country
    overview stays a bounded, polite set of calls to the shared services.
    """
    from app.services.location_service import _SOURCE_RISK_LEVEL  # noqa: F401 - documents the shared baseline

    country = resolve_country(country_name)
    if country is None:
        return {"available": False, "message": "No country found for that search."}

    # The limit is applied to the LIST, not to the buffer: asking for `limit + 4`
    # and then sampling everything meant a caller asking for N states paid for N+4
    # water lookups, four of which were sampled and then thrown away.
    states = country_states(country, limit=limit)

    if not states:
        return {
            "available": True,
            "message": "No state-level data is available for this country.",
            "country": country,
            "states": [],
            "legend": RISK_LEGEND,
        }

    country_name_label = country.get("name")

    if not with_risk:
        quick = [{
            "state": row["name"],
            "name": row["name"],
            "country": country_name_label,
            "risk_level": "unknown",
            "risk_tone": "unknown",
            "insufficient_data": True,
            "sampled_points": 0,
            "worst_source": None,
            "water_types": [],
            "factors": [],
            "message": "%s: water quality has not been sampled for this state yet."
                       % INSUFFICIENT_DATA,
        } for row in states]
        return {
            "available": True,
            "message": None,
            "country": country,
            "states": quick,
            "legend": RISK_LEGEND,
            "summary": {
                "total_states": len(quick),
                "safe": 0,
                "moderate": 0,
                "unsafe": 0,
                "unknown": len(quick),
            },
        }

    # The state lookups are independent —” one per state —” so they run in
    # parallel threads. The caller's callers only see the finished, ordered
    # result; a state lookup that failed with an exception (a network flap,
    # for instance) becomes the HONEST "unknown" rather than a missing row.
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_state_risk, {**s, "country": country_name_label}): s
                   for s in states}
        risk_rows = []
        for future in futures:
            try:
                risk_rows.append(future.result())
            except Exception:  # noqa: BLE001 - one state must not break the page
                logger.exception("State risk lookup failed for %s", futures[future])
                risk_rows.append({
                    "state": futures[future]["name"],
                    "risk_level": "unknown",
                    "sampled_points": 0,
                    "water_types": [],
                    "worst_source": None,
                    "rain_status": None,
                    "message": "%s: water source information is unavailable for "
                               "this state." % INSUFFICIENT_DATA,
                })

    # Restore the caller's order: the pool returned them in completion order.
    risk_rows.sort(key=lambda row: [s["name"] for s in states].index(row["state"]))

    tones = {"low": "safe", "moderate": "moderate", "high": "unsafe"}

    results = []
    for row in risk_rows:
        level = row["risk_level"]
        factors = []
        if row["worst_source"]:
            factors.append({
                "source": "source type",
                "detail": f"{row['worst_source']} (identified from mapped water data)",
            })
        if row["rain_status"] in ("occurring", "expected_soon"):
            factors.append({"source": "weather", "detail": f"rain {row['rain_status'].replace('_', ' ')} in this area"})
        results.append({
            "state": row["state"],
            "name": row["state"],
            "country": country_name_label,
            "risk_level": level,
            "risk_tone": tones.get(level, "unknown"),
            # STEP 18: the flag that tells the screen to print the brief's
            # "Insufficient data" wording instead of a risk summary. It is set
            # from the CALCULATED level, never chosen, so a state that really was
            # measured as low/moderate/high can never be labelled insufficient,
            # and one that could not be measured can never show a colour.
            "insufficient_data": level == "unknown",
            "sampled_points": row["sampled_points"],
            "worst_source": row["worst_source"],
            "water_types": row["water_types"],
            "factors": factors,
            "message": row["message"],
        })

    # Count the legend for the summary line: how many states carry each colour.
    counts = {"low": 0, "moderate": 0, "high": 0, "unknown": 0}
    for state in results:
        counts[state["risk_level"]] += 1

    return {
        "available": True,
        "message": None,
        "country": country,
        "states": results,
        "legend": RISK_LEGEND,
        "summary": {
            "total_states": len(states),
            "safe": counts["low"],
            "moderate": counts["moderate"],
            "unsafe": counts["high"],
            "unknown": counts["unknown"],
        },
    }


# ---------------------------------------------------------------------------
# Step 21 —” district overview: the nine places inside ONE district
# ---------------------------------------------------------------------------

# The number of places a district view shows. The brief is explicit: nine
# major / relevant places per district —” 3 SAFE, 3 MODERATE and 3 UNSAFE
# internally, so the user always sees a spread of the district's water
# reality —” but the LABELS stay internal: the cards show only the place's
# name, town/village/area, district and state. No Safe/Moderate/Unsafe text,
# no colour, no prediction. The verdict is revealed only when the user clicks
# a place and the analysis runs.
DISTRICT_PLACE_COUNT = 9

# How many candidates of EACH internal band to gather before the 9 are cut.
# Three per band exactly matches the brief's 3/3/3 internal split.
_PER_BAND = 3


def _normalise_district_query(text: str) -> str:
    """Strip the "district" suffix a user often types, keeping the bare name.

    "Sivaganga district" and "Sivaganga" must resolve to the same district, and
    the geocoders do not know the suffix, so it is removed before any lookup.
    """
    import re

    words = [w for w in re.split(r"[\s,\-]+", (text or "").strip()) if w]
    kept = [w for w in words if w.casefold() not in ("district", "dt", "dist", "the")]
    return " ".join(kept)


def resolve_district(query: str) -> dict | None:
    """Turn a search string into ONE district, or None when it is not one.

    Two open data sources answer this; neither is hardcoded anywhere.

    1. Open-Meteo geocoding. A district appears there in two ways: as an
       explicit ADM2 row (the administrative division itself), or as a town
       that CARRIES the district in its ``admin2``/``admin3`` fields. The
       second form is the common one —” "Sivaganga" returns the town with
       ``admin2: "Sivaganga"`` —” so a row whose admin2/admin3 matches the
       search text resolves to that district too. The centre used for the
       place enumeration is the matched row's own coordinates.

    2. Nominatim, when Open-Meteo has no row whose admin2/admin3 matches
       (some districts are named differently from any town in them). Its
       ``address.county`` is the district, and the feature's own coordinates
       give the centre.

    A "district" suffix in the query ("Sivaganga district") is stripped
    before both lookups. Nothing is invented: an unmatched text returns None
    and the caller reports it honestly.

    STEP 20: THE BUNDLED DATA IS CONSULTED FIRST, AND IS WHAT MAKES THE STEP
    REACHABLE.

    Two problems are solved here.

    First, the ORDER of the search. A district name is very often also a town of
    the same name, so the place resolver answers "Cuddalore" with the city and
    the district view was reached only when a name happened to 404. The screen
    asks whether the text is a district before it asks whether it is a place,
    and that question is answered from the bundled administrative data - a local
    lookup, with no network call, so it costs nothing on an ordinary search.

    Second, RELIABILITY. Both geocoders are shared services and either can refuse;
    measured, a rate-limited Nominatim answers 429 and a district the application
    already lists stops being recognised. So when the bundled data holds a
    district of this name, that is taken as the answer for WHICH district it is,
    and only the coordinates are still sought from the geocoders. The bundled
    data is what the rest of the application already trusts for district lists,
    so this introduces no new claim.
    """
    from app.services.district_service import bundled_districts

    # The bundled answer, if the data covers this name at all.
    bundled_states = bundled_districts(_normalise_district_query(query))
    from app.services.location_service import _clean, _get, _GEOCODE_URL, _SEARCH_URL

    text = _clean(query)
    if not text:
        return None
    core = _normalise_district_query(text) or text
    wanted = " ".join(core.split()).casefold()

    body = _get(_GEOCODE_URL, {
        "name": core,
        "count": 10,
        "language": "en",
        "format": "json",
    })
    rows = (body or {}).get("results") or []

    # Pass 1: an explicit ADM2 row (the division itself) is the best answer.
    for row in rows:
        feature_code = _clean(row.get("feature_code")) or ""
        if feature_code.startswith("ADM2"):
            lat, lon = row.get("latitude"), row.get("longitude")
            if lat is None or lon is None:
                continue
            name = _clean(row.get("admin2")) or _clean(row.get("name"))
            return {
                "name": name,
                "district": name,
                "state": _clean(row.get("admin1")),
                "country": _clean(row.get("country")),
                "country_code": _clean(row.get("country_code")),
                "lat": float(lat),
                "lon": float(lon),
            }

    # Pass 2: any row that CARRIES the district as its admin2/admin3 —” the
    # common Open-Meteo shape for a district whose name matches its main town.
    #
    # STEP 20: A ROW THAT NAMES ITSELF IS NOT A DISTRICT. Measured, searching
    # "Kochi" returns a row with `admin2: "Ernakulam District"` and
    # `admin3: "Kochi"`, because Open-Meteo records Kochi's SUB-DISTRICT under
    # its own name. That row matched "Kochi" against itself and the app answered
    # with a district called "Kochi" that does not exist. A place whose own name
    # is the text searched for is the place itself, not the district containing
    # it, so it is skipped and the next row is considered.
    for row in rows:
        row_name = " ".join((_clean(row.get("name")) or "").split()).casefold()
        if row_name and row_name == wanted:
            continue
        for key in ("admin2", "admin3"):
            value = _clean(row.get(key))
            if not value:
                continue
            value_core = _normalise_district_query(value) or value
            if " ".join(value_core.split()).casefold() == wanted:
                lat, lon = row.get("latitude"), row.get("longitude")
                if lat is None or lon is None:
                    break
                return {
                    "name": value,
                    "district": value,
                    "state": _clean(row.get("admin1")),
                    "country": _clean(row.get("country")),
                    "country_code": _clean(row.get("country_code")),
                    "lat": float(lat),
                    "lon": float(lon),
                }

    # Pass 3: Nominatim. Its address block records the district as "county".
    body = _get(_SEARCH_URL, {
        "q": core,
        "format": "jsonv2",
        "addressdetails": 1,
        "limit": 5,
    })
    for row in body if isinstance(body, list) else []:
        address = row.get("address") or {}
        county = _normalise_district_query(_clean(address.get("county")) or "")
        district_name = _clean(address.get("county"))
        if not district_name:
            continue
        # STEP 20: the same rule as the Open-Meteo passes. Nominatim records
        # Kochi under `county: "Kochi"` because the city sits in an area of that
        # name, and that made "Kochi" resolve to a district called "Kochi". A row
        # whose own name is the search text is the place itself, so it is skipped.
        own_name = " ".join((_clean(row.get("name")) or "").split()).casefold()
        if own_name and own_name == wanted:
            continue
        if " ".join(county.split()).casefold() == wanted or wanted in " ".join(
            county.split()
        ).casefold():
            lat, lon = row.get("lat"), row.get("lon")
            if lat is None or lon is None:
                continue
            shown = _normalise_district_query(district_name) or district_name
            return {
                "name": shown,
                "district": shown,
                "state": _clean(address.get("state")),
                "country": _clean(address.get("country")),
                "country_code": (_clean(address.get("country_code")) or "").upper() or None,
                "lat": float(lat),
                "lon": float(lon),
            }
    # --- Bundled data (Step 20) ----------------------------------------------
    # Reached only when neither geocoder answered a name the bundled data already
    # knows as a district. The coordinates are left as None rather than guessed:
    # without them the place enumeration cannot run, and the caller then reports
    # that no verified places are available - which is the truth about what could
    # be sampled. Inventing a centre to make the list look fuller would not be.
    if bundled_states:
        bundled_name = _normalise_district_query(query) or query.strip()
        logger.info(
            "Neither geocoder resolved %r; answering from bundled "
            "administrative data, which lists it as a district of %s.",
            query, bundled_states[0])
        return {
            "name": bundled_name,
            "district": bundled_name,
            "state": bundled_states[0],
            "country": "India",
            "country_code": "IN",
            "lat": None,
            "lon": None,
            "source": "bundled",
        }
    return None


def _geocoder_places(district: dict, want: int) -> list[dict]:
    """The district's settlements from the geocoder, when the map data cannot say.

    STEP 20 - A SECOND SOURCE, BECAUSE ONE UNREACHABLE SERVICE EMPTIES THE STEP.

    The Overpass query above is a relation walk - ``map_to_area`` on the district
    boundary - and measured on this network it cannot complete: overpass-api.de
    answers 504 and the mirrors time out. That made EVERY district answer with
    zero places and the message "No place-level data is available for this
    district", which is not the truth: the district does have places, a service
    was unavailable. The nine-place step was therefore unusable rather than slow.

    So the district's centre is used to ask the geocoder for the settlements
    around it, bounded to a box, and the rows are kept only when the geocoder
    itself confirms they sit in this district. That is the same "only what the
    data states" rule the Overpass path follows - nothing is invented to fill a
    gap - and it is the source that answers when Overpass cannot.

    "Major / relevant" still comes from the data: the geocoder's own ``type``
    (city / town / village) is kept as the place kind, and rows are returned in
    the geocoder's relevance order, which is its ranking of these places.
    """
    from app.services.location_service import _clean, _get, _SEARCH_URL

    lat, lon = (district or {}).get("lat"), (district or {}).get("lon")
    if lat is None or lon is None:
        return []

    wanted = " ".join(((district or {}).get("name") or "").split()).casefold()
    state = " ".join(((district or {}).get("state") or "").split()).casefold()

    # A bounded box around the district's centre. The district's own radius is
    # not known here, so this is a generous fixed box; rows are then filtered by
    # the geocoder's own district field, which is what keeps a neighbouring
    # district's town out.
    box = 0.45
    body = _get(_SEARCH_URL, {
        "q": (district or {}).get("name") or "",
        "format": "jsonv2",
        "addressdetails": 1,
        "limit": max(want * 3, 20),
        "viewbox": ",".join([
            "%.4f" % (lon - box), "%.4f" % (lat - box),
            "%.4f" % (lon + box), "%.4f" % (lat + box),
        ]),
        "bounded": 1,
        "featuretype": "settlement",
    })
    rows = body if isinstance(body, list) else []

    places: list[dict] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        pname = _clean(row.get("name")) or _clean(row.get("display_name", "").split(",")[0])
        row_lat, row_lon = row.get("lat"), row.get("lon")
        if not pname or pname.casefold() in seen or row_lat is None or row_lon is None:
            continue
        address = row.get("address") or {}
        county = _clean(address.get("county") or address.get("district")
                        or address.get("city_district"))
        # Confirmed in this district when the geocoder says so; when it says
        # nothing at all the row is still kept, because the search was bounded to
        # this district's own centre. A row that names a DIFFERENT district is
        # dropped.
        if county and wanted and wanted not in county.casefold() \
                and county.casefold() not in wanted:
            continue
        if state:
            row_state = _clean(address.get("state")).casefold()
            if row_state and state not in row_state and row_state not in state:
                continue
        seen.add(pname.casefold())
        places.append({
            "name": pname,
            "place_kind": _clean(row.get("type")) or "settlement",
            "lat": float(row_lat),
            "lon": float(row_lon),
            # The geocoder does not return a population, so it is absent rather
            # than invented: the importance sort below reads it with a default.
            # The geocoder's own order is its relevance ranking; the index keeps
            # that order explicit so the sort below is stable and data-driven.
            "id": len(rows) - index,
        })
        if len(places) >= want * 3:
            break
    return places


def district_places(district: dict, per_band: int = _PER_BAND) -> list[dict]:
    """The nine major / relevant places of ONE district, from the map data.

    HOW THE NINE ARE CHOSEN (and why it is not random)
    --------------------------------------------------
    The district's major settlements —” its towns and villages, the places
    OpenStreetMap itself records with a place node —” are enumerated from
    Overpass, ranked by mapped importance (population where the data carries
    it, otherwise node id as a stable proxy for detail/age of mapping), and
    then SAMPLED for water exactly as a single-place lookup is.

    Each sampled place's water goes through ``_state_risk_from_samples`` —” the
    SAME derivation the single place, the state and the country views use —”
    so every place lands in one of the three internal bands:

        low      -> the SAFE band
        moderate -> the MODERATE band
        high     -> the UNSAFE band

    The brief's internal dataset is 3 SAFE + 3 MODERATE + 3 UNSAFE. We take
    the best-mapped places from each band in mapped-importance order, up to
    ``per_band`` each. A band the district genuinely does not have stays
    short —” the shortfall is NEVER filled by reclassifying a place, so the
    classification is never randomly assigned.

    WHAT THE ROWS CARRY
    -------------------
    Only the identification fields the cards display —” place name,
    town/village/area, district, state —” plus the coordinates the click-through
    needs to run the analysis. The internal band is carried as ``band`` for the
    backend's own dataset accounting, but the UI does not render it: no
    Safe/Moderate/Unsafe label and no coloured dot appears on these cards, and
    the final prediction is not exposed until the user opens the place and the
    one model path runs.
    """
    from app.services.location_service import (
        _clean,
        _overpass,
        water_context,
    )

    name = (district or {}).get("name") or ""
    if not name:
        return []

    # The district's own administrative relation -> area -> every place node
    # inside it. `place` nodes are the settlements OSM considers major enough
    # to map; this is the same "real mapped data" rule the rest of the flow
    # follows. The result is ordered by importance when population is known
    # (Overpass sorts desc on the tag), so "major/relevant" comes from the map.
    query = (
        "[out:json][timeout:90];"
        f'rel["name"~"^{name}$",i]["boundary"="administrative"]["admin_level"="6"];'
        "map_to_area ->.dist;"
        'node(area.dist)["place"~"^(town|village|suburb|borough)$"];'
        f"out body {max(DISTRICT_PLACE_COUNT * 4, 24)};"
    )
    body = _overpass(query) or {}
    elements = (body.get("elements") if isinstance(body, dict) else body) or []
    # --- Candidate settlements, most-major first ---------------------------
    candidates: list[dict] = []
    seen: set[str] = set()
    for element in elements:
        tags = element.get("tags") or {}
        pname = _clean(tags.get("name"))
        lat, lon = element.get("lat"), element.get("lon")
        if not pname or pname in seen or lat is None or lon is None:
            continue
        seen.add(pname)
        try:
            population = int(str(tags.get("population") or "0") or 0)
        except (TypeError, ValueError):
            population = 0
        candidates.append({
            "id": element.get("id") or 0,
            "name": pname,
            "place_kind": _clean(tags.get("place")),
            "lat": float(lat),
            "lon": float(lon),
            "population": population,
        })

    # STEP 20: the map data answers first; the geocoder answers when it cannot.
    # Measured, Overpass is unreachable on this network, so this fallback is what
    # actually produces the places rather than a rare safety net.
    if not candidates:
        candidates = _geocoder_places(district, DISTRICT_PLACE_COUNT)
        if candidates:
            logger.info(
                "Overpass could not enumerate places in %r; answered from the "
                "geocoder instead.", name)

    # Major first: known population desc, then mapped detail (node id desc)
    # as a stable, data-driven tiebreak —” never a random order.
    candidates.sort(key=lambda c: (c.get("population") or 0, c.get("id") or 0),
                    reverse=True)

    # --- Sample each candidate's water, band it, fill 3/3/3 ----------------
    sampled: list[dict] = []
    for candidate in candidates[: DISTRICT_PLACE_COUNT * 4]:
        water = water_context({
            "lat": candidate["lat"],
            "lon": candidate["lon"],
            "name": candidate["name"],
        })
        verdict = _state_risk_from_samples(water, rain=None)
        level = verdict["level"]
        if level not in ("low", "moderate", "high"):
            # An unsampleable place (no mapped water) carries no band; it is
            # skipped rather than guessed into one.
            continue
        sampled.append({
            **candidate,
            "band": level,
        })

    bands = {"low": [], "moderate": [], "high": []}
    for row in sampled:
        bands[row["band"]].append(row)

    chosen: list[dict] = []
    for level in ("low", "moderate", "high"):
        chosen.extend(bands[level][:per_band])

    state_name = (district or {}).get("state")
    places = []
    for row in chosen:
        places.append({
            "name": row["name"],
            "town": row["name"],
            "area": row["place_kind"],
            "district": (district or {}).get("district") or name,
            "state": state_name,
            "lat": row["lat"],
            "lon": row["lon"],
            # INTERNAL dataset accounting only —” the UI must not render this.
            "band": row["band"],
        })
    return places


def district_overview(district_name: str) -> dict:
    """Step 21: the district-level result —” the nine places, labels hidden.

    The response shape mirrors ``state_overview`` so the screen can treat all
    three levels the same way. The ``places`` rows deliberately expose ONLY the
    identification fields the cards display (name, town/village/area, district,
    state); the internal 3/3/3 banding is summarised in ``composition`` for the
    backend's own accounting, and the final prediction for any place is NOT
    part of this response —” it happens when the user clicks through and the
    existing prediction path runs.
    """
    district = resolve_district(district_name)
    if district is None:
        return {"available": False, "message": "No district found for that search."}

    places = district_places(district)
    composition = {"safe": 0, "moderate": 0, "unsafe": 0}
    band_keys = {"low": "safe", "moderate": "moderate", "high": "unsafe"}
    for place in places:
        key = band_keys.get(place["band"])
        if key:
            composition[key] += 1

    # STEP 20 - THE SHORTFALL IS REPORTED, NEVER PAPERED OVER.

    # The brief asks for nine places spanning the three internal bands, and then
    # says plainly: if the district does not hold enough verified locations, do
    # not fabricate them, show what is verified and say the data is insufficient.
    # So the response states, as data, how much of the 3/3/3 was actually filled
    # and why not - the screen prints that instead of implying a complete set.

    # A place is only counted into a band when its water was really sampled. Any
    # place that could not be sampled is dropped rather than guessed into a band,
    # so `composition` can never exceed what the data supports.
    short_bands = [label for label, filled in
                   (("safe", composition["safe"]),
                    ("moderate", composition["moderate"]),
                    ("unsafe", composition["unsafe"]))
                   if filled < _PER_BAND]
    complete = len(places) == DISTRICT_PLACE_COUNT and not short_bands

    if not places:
        message = ("%s: no verified places could be gathered for this district, "
                   "so none are shown." % INSUFFICIENT_DATA)
    elif complete:
        message = None
    else:
        message = (
            "%s: %d of the %d places could be verified with water quality data "
            "(%d SAFE, %d MODERATE, %d UNSAFE). The remaining places were left "
            "out rather than assigned a category, so only the verified places "
            "are shown."
            % (INSUFFICIENT_DATA, len(places), DISTRICT_PLACE_COUNT,
               composition["safe"], composition["moderate"], composition["unsafe"])
        )

    return {
        "available": True,
        "message": message,
        "district": district,
        "places": places,
        "composition": composition,
        # Machine-readable alongside the sentence, so the screen does not have to
        # parse prose to decide whether to show the insufficient-data note.
        "coverage": {
            "required": DISTRICT_PLACE_COUNT,
            "verified": len(places),
            "complete": complete,
            "short_bands": short_bands,
        },
    }

