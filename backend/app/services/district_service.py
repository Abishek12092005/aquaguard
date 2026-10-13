"""Step 17 - the districts of a state, from bundled administrative data.

WHY THIS EXISTS
---------------
The Location page used to answer a typed STATE with an empty district list, and
the reason was the source rather than the code. The district enumeration asked
OpenStreetMap's Overpass API for the state's boundary and then for every
level-6 relation inside it - a `map_to_area` query. Measured on this network
that query is unusable: overpass-api.de answers 504, the other two mirrors time
out, and the module's 2.5 s water budget (correctly sized for a point-radius
lookup) gives up long before a relation walk can finish. The honest result was
"no district-level data is available for this state" for EVERY state, and the
120 s outage breaker then blocked even the retries. Nominatim cannot fill the
gap either - measured, a structured county search returns one row for Tamil
Nadu, and a free-text "district, Tamil Nadu" search returns 25 mixed villages
and factories rather than the 38 districts.

So the district NAMES come from bundled administrative data instead
(`india_districts.json`), which is built by `build_step17_districts.py` from
English Wikipedia's "List of districts of <state>" articles and then VALIDATED
against Wikipedia's own "Districts of <state>" categorisation. That validation
is what keeps sub-districts and villages out (Ladakh's Drass and Nubra are
tehsils, Arunachal's Aalo and Ziro are sub-divisions), and it is what makes the
list complete rather than a handful of well-known districts.

WHAT IS AND IS NOT IN HERE
--------------------------
  * NAMES are bundled data. A district the dataset does not carry is simply
    absent - it is never guessed, and no district is invented to pad a list.
  * STATE and COUNTRY are read from the resolved state, not hardcoded: they
    come from the same resolution the country view uses, so a state outside
    India still resolves and is reported honestly as having no bundled list.
  * RISK is calculated, never assigned. Each district is sampled for mapped
    water exactly as a single place is, and a district the water data cannot
    support reads `unknown` rather than getting a colour we would have made up.

The list is the COMPLETE set for the state, not a sample, and it is ordered
deterministically (alphabetical, with a 1-based rank), so the same state always
renders in the same order.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

_DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "india_districts.json")

# STEP 17: THE NAMES USERS TYPE ARE NOT ALWAYS THE NAMES THE DATA USES.
#
# The dataset keys a union territory by its full official name, so a user who
# types the ordinary one gets nothing. "Delhi" is the obvious case: the data
# calls it "National Capital Territory of Delhi", and a search for Delhi must
# still return Delhi's districts.
#
# These are ALIASES, not corrections. They map a name a user is likely to type
# onto the key that actually exists in the data, so nothing is invented and no
# entry is duplicated - the district list is still whatever the dataset holds
# for that one state. A user who types the full official name reaches the same
# list, because the alias only ever redirects to a real key.
_STATE_ALIASES = {
    "delhi": "National Capital Territory of Delhi",
    "new delhi": "National Capital Territory of Delhi",
    "nct of delhi": "National Capital Territory of Delhi",
    "national capital territory of delhi": "National Capital Territory of Delhi",
    "pondicherry": "Puducherry",
    "puducherry": "Puducherry",
    "orissa": "Odisha",
    "odisha": "Odisha",
    "pondicherry state": "Puducherry",
    "daman and diu": "Dadra and Nagar Haveli and Daman and Diu",
    "dadra and nagar haveli": "Dadra and Nagar Haveli and Daman and Diu",
    "jammu and kashmir state": "Jammu and Kashmir",
    "uttaranchal": "Uttarakhand",
    "madhya pradesh": "Madhya Pradesh",
    "west bengal": "West Bengal",
    "tamilnadu": "Tamil Nadu",
    "andhra pradesh state": "Andhra Pradesh",
    "assam state": "Assam",
}

# The bundled map, loaded once. Loading is guarded so a partially written file
# (or a missing one) degrades to an empty index rather than taking the app down:
# the caller then reports that no bundled list exists for the state, which is
# the honest answer, instead of a 500 on every state search.
_lock = threading.RLock()
_index: dict[str, list[str]] | None = None
_aliases: dict[str, str] | None = None
# The folded alias table, built on first use. It cannot be built at import time
# because folding borrows `_fold` from location_service, and importing that
# module from here would be a circular import.
_folded_aliases: dict[str, str] | None = None


def _fold(text: str) -> str:
    """Names are compared on their letters, so 'tamil nadu' == 'Tamil Nadu'."""
    from app.services.location_service import _fold as _location_fold

    return _location_fold(text)


def _load() -> tuple[dict[str, list[str]], dict[str, str]]:
    """The bundled districts, plus a folded-name -> canonical-state index."""
    global _index, _aliases
    with _lock:
        if _index is not None and _aliases is not None:
            return _index, _aliases
        try:
            with open(_DATA_PATH, encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, ValueError) as exc:
            logger.warning("District dataset unavailable (%s); "
                           "state searches will report no bundled list", exc)
            raw = {}
        index = {
            state: sorted({d for d in districts if d}, key=str.casefold)
            for state, districts in raw.items()
        }
        aliases = {_fold(state): state for state in index}
        _index, _aliases = index, aliases
        return index, aliases


def _alias_map() -> dict[str, str]:
    """The alias table keyed by folded name, built on first use."""
    global _folded_aliases
    with _lock:
        if _folded_aliases is None:
            _folded_aliases = {_fold(a): t for a, t in _STATE_ALIASES.items()}
        return _folded_aliases


def bundled_states() -> list[str]:
    """Every state/UT the bundled dataset covers, in order."""
    index, _ = _load()
    return sorted(index, key=str.casefold)


def bundled_districts(name: str) -> list[str]:
    """The states whose bundled list contains a district of this name.

    STEP 20 - A REVERSE LOOKUP, SO "IS THIS TEXT A DISTRICT?" IS ANSWERABLE
    LOCALLY AND INSTANTLY.

    The bundled data is keyed by STATE and holds districts as values, so the
    obvious question - "is the text the user typed a district?" - needed a linear
    scan over every state and every district. That question is asked on EVERY
    search, because a district name is very often also the name of a town in it,
    and the district view has to be recognised before the place resolver answers
    with the town.

    This is that index, built once on first use and folded on letters, so
    "cuddalore", "Cuddalore" and "CUDDALORE " all match. It answers from local
    data with no network call, which is what makes the check free enough to run
    before every search.
    """
    index, _ = _load()
    return list(_reverse_index().get(_fold(name), ()))


# The folded district name -> the states that contain it, built on first use for
# the same reason the alias table is: folding borrows `_fold` from
# location_service, and importing that here would be circular.
#
# The CACHE and the FUNCTION that reads it must not share a name. A module global
# and a function both bind the same name, so one clobbers the other - and a
# function object called like a dict raises `AttributeError: 'function' object has
# no attribute 'get'`. The cache is therefore `_REVERSE_INDEX`.
_REVERSE_INDEX: dict[str, set] | None = None


def _reverse_index() -> dict[str, set]:
    global _REVERSE_INDEX
    with _lock:
        if _REVERSE_INDEX is None:
            built: dict[str, set] = {}
            for state, districts in _load()[0].items():
                for district in districts:
                    built.setdefault(_fold(district), set()).add(state)
            _REVERSE_INDEX = built
        return _REVERSE_INDEX


def canonical_state(name: str) -> str | None:
    """The dataset's own name for a state, or None when it has no list.

    Matching is on folded letters, so "tamil nadu", "Tamil  Nadu" and
    "TAMIL NADU" all reach the same entry, and a trailing "state" or
    "india" is ignored because users type those in. A known alias ("Delhi" for
    "National Capital Territory of Delhi") resolves to the real key.
    """
    index, aliases = _load()
    text = (name or "").strip()
    if not text:
        return None
    for suffix in (" state", " india", ", india"):
        if text.casefold().endswith(suffix):
            text = text[: -len(suffix)].strip()
    folded = _fold(text)
    if folded in aliases:
        return aliases[folded]
    aliased = _alias_map().get(folded)
    if aliased and aliased in index:
        return aliased
    return None


def district_names(state_name: str) -> list[str]:
    """Every district of a state, alphabetical. Empty when none is bundled."""
    index, _ = _load()
    state = canonical_state(state_name)
    if state is None:
        return []
    return list(index[state])


def _district_row(state: dict, name: str) -> dict:
    """One district with whatever risk the data actually supports.

    The risk is SAMPLED, not assumed: the district is resolved to real
    coordinates through the same geocoders a place search uses, the mapped
    water near that point goes through the shared ``_state_risk_from_samples``
    derivation, and the result is what the row carries. A district that cannot
    be resolved, or around which no water is mapped, reads `unknown` - the
    honest answer, and never a colour we would have invented.
    """
    from app.services.country_service import _state_risk_from_samples
    from app.services.location_service import (rain_forecast, resolve,
                                               water_context)

    from app.services.country_service import INSUFFICIENT_DATA

    state_name = state.get("state") or state.get("name")
    row = {
        "name": name,
        "district": name,
        "state": state_name,
        "country": state.get("country"),
        "risk_level": "unknown",
        "risk_tone": "unknown",
        # STEP 19: the brief's wording leads the message, and this flag is what
        # the screen keys off to print it. Set from the calculated level, never
        # chosen.
        "insufficient_data": True,
        "water_types": [],
        "sampled_points": 0,
        "worst_source": None,
        "message": "%s: no mapped water quality data is available for this "
                   "district." % INSUFFICIENT_DATA,
    }

    # The name is qualified with the state, because several districts share a
    # name with a town in another state, and the place resolver - not
    # `resolve_district` - is what actually answers for a district name: the
    # latter matches the geocoder's `admin2` field exactly and resolves none
    # of the bundled names.
    resolved = resolve("%s, %s" % (name, state_name or "")) or {}
    if resolved.get("lat") is None:
        return row

    lat, lon = resolved["lat"], resolved["lon"]
    water = water_context({"lat": lat, "lon": lon, "name": name})
    rain = rain_forecast(lat, lon)
    verdict = _state_risk_from_samples(water, rain)
    factors = verdict.get("factors") or []

    tones = {"low": "safe", "moderate": "moderate", "high": "unsafe"}
    row.update({
        "lat": lat,
        "lon": lon,
        "risk_level": verdict["level"],
        "risk_tone": tones.get(verdict["level"], "unknown"),
        # STEP 19: cleared only because a real level was calculated. The flag is
        # never set by hand, so a district can never claim a SAFE/MODERATE/UNSAFE
        # classification that was not derived from sampled water.
        "insufficient_data": verdict["level"] == "unknown",
        "water_types": water.get("types") or [],
        "sampled_points": len(water.get("nearby") or []),
        "worst_source": (factors[0]["detail"].split(" (identified")[0]
                         if factors else None),
        "message": verdict.get("message"),
    })
    return row


def state_district_list(state_name: str, state: dict | None = None,
                        with_risk: bool = True) -> list[dict]:
    """The ORDERED district list of a state, risk sampled where it is possible.

    Ordering is alphabetical by folded name and is assigned here, not left to
    the database or the network, so the same state always produces the same
    list in the same order.

    With ``with_risk`` the districts are sampled concurrently, each one an
    independent lookup, and a district that fails becomes the honest
    ``unknown`` row rather than a missing entry. With it off the rows are
    returned immediately, which is what the state endpoint uses to answer in
    milliseconds from bundled data alone.
    """
    names = district_names(state_name)
    if not names:
        return []

    context = state or {"name": state_name, "state": state_name}

    if not with_risk:
        rows = [{
            "name": n, "district": n,
            "state": context.get("state") or context.get("name"),
            "country": context.get("country"),
            "risk_level": "unknown", "risk_tone": "unknown",
            # STEP 19: with sampling off, nothing has been measured, so the
            # screen says so rather than implying a risk it does not have.
            "insufficient_data": True,
        } for n in names]
    else:
        with ThreadPoolExecutor(max_workers=6) as pool:
            rows = list(pool.map(
                lambda n: _district_row(context, n), names))

    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows
