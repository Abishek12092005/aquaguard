"""Location blueprint — the location-based water quality surface.

    GET /api/v1/locations/search          find a place by name / pincode / landmark
    GET /api/v1/locations/pincode         a PIN code -> the area, city, district, state
    GET /api/v1/locations/reverse         device coordinates -> an address
    GET /api/v1/locations/context         water source + nearby sources + rain + risk
    GET /api/v1/locations/parameters      default prediction readings for a source
    GET /api/v1/locations/country         country overview: every state + its risk
    GET /api/v1/locations/state           state overview: every district + its risk

The flow this blueprint supports:

    user location -> validation -> water source identification -> nearby source
    -> distance -> risk information -> rain alert -> automatic prediction
    parameters -> the EXISTING Random Forest prediction endpoint

Nothing here predicts anything. `/locations/parameters` returns a starting set of
readings for the Predict form; the prediction itself still goes through
`POST /predictions/predict`, unchanged, so there is exactly one model path.

No route here requires a token. The application is open, and a location lookup
is a plain geocoding read that every visitor performs before submitting a sample;
gating it would mean refusing the first thing a visitor asks for.
"""

from __future__ import annotations

import logging

from flask import Blueprint, request

from app.utils.errors import AquaGuardError
from app.utils.responses import error_response, success_response

logger = logging.getLogger(__name__)

location_bp = Blueprint("locations", __name__)


def _failure(exc: AquaGuardError):
    return error_response(exc.message, exc.status_code, exc.errors)


def _number_arg(name: str, required: bool = True) -> float | None:
    """Read a numeric query parameter, raising a clear error when it is bad.

    A missing coordinate is a 422 with the field named, not a 500 from a failed
    float conversion three layers down.
    """
    from app.utils.errors import ValidationError

    raw = request.args.get(name)
    if raw is None or raw == "":
        if required:
            raise ValidationError(f"{name} is required", {name: "This field is required"})
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        raise ValidationError(f"{name} must be a number", {name: "Must be a number"}) from None


def _coordinate(name: str) -> float:
    """Read a latitude or longitude, and refuse one that is not on the globe.

    A number being PARSEABLE is not the same as it being a coordinate. `lat=999`
    converts fine and is then handed to the geocoder, which spends a request
    discovering that no such place exists and answers 404 - a "not found" for
    what is really a bad argument. The two have different causes and different
    fixes, so the range is checked here where the error can still name the field.
    """
    from app.utils.errors import ValidationError

    value = _number_arg(name)
    limit = 90.0 if name == "lat" else 180.0
    if value is None or not -limit <= value <= limit:
        raise ValidationError(
            f"{name} must be between {-limit:g} and {limit:g}",
            {name: f"Must be between {-limit:g} and {limit:g}"},
        )
    return value


def _optional_coordinate(name: str) -> float | None:
    """Read a coordinate that may be absent, but must be a real one when present.

    STEP 36. The same check `_coordinate` performs, with the "may be omitted"
    behaviour `_number_arg` has. `/water` and `/context` accept EITHER
    coordinates or a place name, so their coordinates are optional - but before
    this they were read with `_number_arg`, which only proved the value parses.
    `lat=999&lon=999` was therefore accepted and answered 200 with a place
    literally named "999.0000, 999.0000" and an empty water block, which reads
    as a real result for a point that is not on the globe. A bad argument and a
    place with no water are different problems and now get different answers.
    """
    from app.utils.errors import ValidationError

    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    # `_coordinate` requires the argument, so parse here and range-check with the
    # same limits it uses.
    value = _number_arg(name, required=False)
    limit = 90.0 if name == "lat" else 180.0
    if value is None or not -limit <= value <= limit:
        raise ValidationError(
            f"{name} must be between {-limit:g} and {limit:g}",
            {name: f"Must be between {-limit:g} and {limit:g}"},
        )
    return value


def _scope() -> tuple[str | None, str | None]:
    """The admin-fixed state / country, when one has been set.

    A THIN RE-EXPORT of `location_service.active_scope`, so the location routes
    and the PREDICTION endpoint answer "what is the scope?" from ONE rule. Two
    copies of a security-relevant read is how one of them comes to disagree with
    the other after a change, and the prediction guard added for requirement 7
    had to read the same mode the search filters do.

    Read lazily and defensively: the scope lives in the single-row admin settings
    table, and a location lookup must still work if that row cannot be read.
    """
    from app.services.location_service import active_scope

    return active_scope()


def _scoped(candidates: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split search results into (allowed, blocked) by the admin scope.

    Blocked rows are returned rather than dropped so the UI can say WHY a place
    is not selectable, instead of the search appearing to have found nothing.
    """
    from app.services.location_service import within_scope

    state, country = _scope()
    if not state and not country:
        return candidates, []

    allowed: list[dict] = []
    blocked: list[dict] = []
    for candidate in candidates:
        verdict = within_scope(candidate, scope_state=state, scope_country=country)
        if verdict["allowed"]:
            allowed.append(candidate)
        else:
            blocked.append({**candidate, "blocked_reason": verdict["reason"]})
    return allowed, blocked


@location_bp.get("/search")
def search():
    """Find a place by name, pincode or a famous landmark.

    Query parameters:

        q            the search text (place name, pincode, landmark)
        limit        how many candidates to return (1..10, default 6)
        autocomplete "true" for the typing-as-you-go dropdown, which asks the
                     providers for fewer spelling variants so the first suggestion
                     arrives quickly. Omit it when resolving ONE place, where every
                     variant is worth asking about. Both return only real
                     geocoder hits; the difference is how many spellings were tried.
        state       OPTIONAL (Step 9). The STATE the browser's own position was
        district    reverse-geocoded into. When both are sent with autocomplete,
                     the providers are additionally asked for hits inside that
                     state and the results are ORDERED so local places lead. This
                     only changes the order: nothing is filtered, so another state
                     or country is still fully searchable, and omitting both
                     (permission refused) leaves the search exactly as it was.

    Responses: 200 with `data` = allowed places and `meta.blocked` = the ones
    outside the administrator's state/country scope; 401 without a token;
    422 when `q` is empty.
    """
    try:
        from app.services.location_service import search as search_places

        query = request.args.get("q") or request.args.get("query") or ""
        limit = request.args.get("limit", 6)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 6
        autocomplete = (request.args.get("autocomplete") or "").lower() in ("1", "true", "yes")

        # Step 9: the device's own administrative area, as the browser resolved
        # it. Read as plain text and passed through untouched - these are only
        # ever used to RANK and to qualify a provider query, never to invent or
        # override a result, and they are ignored entirely when absent.
        device_state = (request.args.get("state") or "").strip() or None
        device_district = (request.args.get("district") or "").strip() or None

        candidates = search_places(
            query,
            limit=limit,
            autocomplete=autocomplete,
            device_state=device_state,
            device_district=device_district,
        )
        allowed, blocked = _scoped(candidates)
        return success_response(
            data=allowed,
            meta={"count": len(allowed), "blocked": blocked},
        )
    except AquaGuardError as exc:
        return _failure(exc)


@location_bp.get("/resolve")
def resolve():
    """Resolve a single location for the search bar, or refuse it.

    This is the "identify one place" call the Location page makes when the user
    searches a name, a pincode or a famous landmark. It returns the single best
    match with every field the selected-location card shows, or a 404 when the
    text does not correspond to any known place — which is how an invalid or
    unsupported location is rejected rather than guessed at.

    Query parameters:

        q        the search text (place name, pincode or landmark)

    Responses: 200 with the resolved place; 401 without a token; 422 when `q`
    is empty; 404 when nothing matches.
    """
    try:
        from app.services.location_service import (
            resolve as resolve_place,
            village_disambiguation,
            within_scope,
        )
        query = (request.args.get("q") or request.args.get("query") or "").strip()

        # STEP 22: A BARE VILLAGE NAME IS NOT ENOUGH TO ANSWER WITH.
        #
        # Village names repeat all over the country, and answering one with the
        # first map hit would confidently report a water source for a completely
        # different village. So the geocoder is asked what kind of place this is,
        # and a VILLAGE with no district in the text is refused a direct answer
        # and given the list of villages it could be instead.
        #
        # This runs before the resolve, is decided by the provider's own place
        # type, and returns None for every city, town, area, nagar, colony,
        # company, shop, college, school, hotel, hospital and landmark - so those
        # resolve exactly as they always have.
        if request.args.get("allow_ambiguous", "").lower() not in ("1", "true", "yes"):
            pending = village_disambiguation(query)
            if pending is not None:
                return success_response(
                    data=pending, meta={"requires_district": True})

        place = resolve_place(query)
        if place is None:
            return error_response(f"No location found for {query!r}", 404)

        state, country = _scope()
        verdict = within_scope(place, scope_state=state, scope_country=country)
        if not verdict["allowed"]:
            # ENFORCED HERE, not in the browser. An out-of-scope place is refused
            # with a 403 and the standard message, so a client that ignores the
            # frontend never receives an allowed location outside the scope.
            #
            # PROMPT 13, REQUIREMENT 8: a place we could not PLACE is a 409, not a
            # 403. It is refused either way - the restriction is never relaxed -
            # but 409 asks the caller to disambiguate, while 403 states a
            # boundary verdict. Reporting "outside the area" about an unresolved
            # point would be claiming something the lookup never established.
            if verdict.get("ambiguous"):
                return error_response(
                    verdict["reason"], 409, {"location": "ambiguous", "requires_clarification": True},
                )
            return error_response(
                verdict["reason"], 403, {"location": "outside the configured scope"}
            )

        # STEP 24: THE OTHER BRANCHES OF A CHAIN, WHEN THE WINNER IS NOT ALONE.
        #
        # A chain with several branches in the same town is one search with
        # several correct answers, and answering with the first one means the
        # water-quality result that follows describes a branch the user never
        # chose. The service returns every other real branch alongside the
        # winner, and they are published here so the UI can ask which one - the
        # winning branch is still returned as `data`, because it is a genuinely
        # good answer and refusing to answer at all would be a worse regression.
        #
        # Each branch is scope-checked on its OWN address, not the winner's: two
        # branches of one chain sit in different towns, and the one outside the
        # configured area is listed with the reason rather than silently offered
        # as selectable.
        branches: list[dict] = []
        for branch in place.get("branches") or []:
            branch_verdict = within_scope(
                branch, scope_state=state, scope_country=country
            )
            branches.append(
                branch if branch_verdict["allowed"]
                else {**branch, "blocked_reason": branch_verdict["reason"]}
            )
        place.pop("branches", None)

        return success_response(
            data=place,
            meta={
                "in_scope": True,
                "scope_reason": None,
                "branches": branches,
                "branch_count": len(branches),
            },
        )
    except AquaGuardError as exc:
        return _failure(exc)

@location_bp.get("/pincode")
def pincode():
    """STEP 23: identify the area behind a typed PINCODE.

    A pincode is an address, not a place name, so it is looked up through the
    postal interface rather than the free-text search. Every field on the answer
    - area, city/town, district, state, country, pincode - is a value the postal
    data actually returned; a part it does not carry is reported as null and the
    UI shows "Not available" for it.

    Nothing is fabricated. A number that is not a well-formed PIN code is
    rejected with 422, and a well-formed number the postal data does not know is
    a 404 - never a place that happens to share the digits. Measured before this
    existed, the text search answered "999999" with a railway station in Italy
    and "12345" with a rural council in Ukraine.

    When one pincode genuinely covers several areas, all of them are returned in
    `areas` so the user can choose, rather than one being picked for them.

    Query parameters:

        q       the pincode (required)

    Responses: 200 with the identified place; 401 without a token; 422 when `q`
    is missing or is not a valid PIN code; 404 when the postal data does not know
    it; 403 when the place is outside the configured scope.
    """
    try:
        from app.services.location_service import (
            is_pincode,
            resolve_pincode,
            within_scope,
        )
        query = (request.args.get("q") or request.args.get("pincode") or "").strip()

        if not query:
            return error_response("A pincode is required", 422)
        if not is_pincode(query):
            # Rejected here, before any geocoder call, so a malformed number can
            # never be resolved as something else entirely.
            return error_response(
                f"{query!r} is not a valid PIN code. An Indian PIN code is six "
                "digits and does not start with 0.",
                422,
            )

        place = resolve_pincode(query)
        if place is None:
            return error_response(
                f"No postal area found for pincode {query!r}. It is not in the "
                "postal data, so no location can be identified from it.",
                404,
            )

        state, country = _scope()
        verdict = within_scope(place, scope_state=state, scope_country=country)
        if not verdict["allowed"]:
            # Enforced on the server, exactly as for every other location, so a
            # client that ignored this screen still could not read water data for
            # a place outside the configured scope.
            return error_response(
                verdict["reason"], 403, {"location": "outside the configured scope"}
            )

        return success_response(data=place, meta={"in_scope": True, "scope_reason": None})
    except AquaGuardError as exc:
        return _failure(exc)


@location_bp.get("/reverse")
def reverse():
    """Resolve the device's coordinates into an address ("use my location").

    Query parameters: `lat` and `lon` (required).
    """
    try:
        from app.services.location_service import reverse as reverse_geocode

        lat = _coordinate("lat")
        lon = _coordinate("lon")
        place = reverse_geocode(lat, lon)
        if place is None:
            return error_response("That location could not be resolved to a place", 404)

        from app.services.location_service import within_scope

        state, country = _scope()
        verdict = within_scope(place, scope_state=state, scope_country=country)
        if not verdict["allowed"]:
            # Same backend enforcement as /resolve: a device fix or a manual pin
            # outside the scope is refused here, not only hidden in the browser.
            return error_response(
                verdict["reason"], 403, {"location": "outside the configured scope"}
            )
        return success_response(data=place, meta={"in_scope": True, "scope_reason": None})
    except AquaGuardError as exc:
        return _failure(exc)


@location_bp.get("/context")
def context():
    """Everything known about a place's water, in one call.

    Accepts EITHER `lat` + `lon`, OR `name` (a place name or pincode). Coordinates
    win when both are supplied, because a pin is more specific than a name.

    Returns the identified water source types, the nearby sources with their
    distances, the rain forecast, the location's risk factors, and the default
    prediction parameters for "Go to Predict".
    """
    try:
        from app.services.location_service import (
            default_parameters,
            default_parameters_detail,
            rain_forecast,
            risk_factors,
            risk_level,
            water_context,
        )
        from app.constants import FEATURE_NAMES, FEATURE_LABELS as _FEATURE_LABELS
        from app.constants import FEATURE_UNITS as _FEATURE_UNITS

        lat = _optional_coordinate("lat")
        lon = _optional_coordinate("lon")
        name = (request.args.get("name") or "").strip() or None

        if (lat is None or lon is None) and not name:
            return error_response("Provide either lat and lon, or a place name", 422)

        # Resolve a name to coordinates first, so the scope check and the water
        # lookups all run against the same, validated place.
        place: dict
        if lat is not None and lon is not None:
            from app.services.location_service import reverse as reverse_geocode

            resolved = reverse_geocode(lat, lon) or {}
            place = {
                "name": resolved.get("name") or name or f"{lat:.4f}, {lon:.4f}",
                "label": resolved.get("label"),
                "country": resolved.get("country"),
                "state": resolved.get("state"),
                "district": resolved.get("district"),
                "pincode": resolved.get("pincode"),
                "lat": lat,
                "lon": lon,
            }
        else:
            from app.services.location_service import search as search_places

            matches = search_places(name, limit=1)
            if not matches:
                return error_response(f"Could not find a place called {name!r}", 404)
            place = matches[0]

        from app.services.location_service import within_scope

        state, country = _scope()
        verdict = within_scope(place, scope_state=state, scope_country=country)
        if not verdict["allowed"]:
            # The full context build is the most expensive lookup and the one that
            # leads to a prediction, so it is refused here too - before any water
            # lookup runs - for a place outside the configured scope.
            #
            # PROMPT 13, REQUIREMENT 8: an UNPLACEABLE point is a 409 asking for
            # clarification, not a 403 claiming it is outside the area. Refused
            # either way, so the restriction still holds.
            if verdict.get("ambiguous"):
                return error_response(
                    verdict["reason"], 409, {"location": "ambiguous", "requires_clarification": True},
                )
            return error_response(
                verdict["reason"], 403, {"location": "outside the configured scope"}
            )

        # STEP 16: THE WATER LOOKUP AND THE FORECAST ARE INDEPENDENT, SO THEY RUN
        # AT THE SAME TIME.
        #
        # They were called one after the other, so the page waited for the SUM of
        # the two when it only ever needed the SLOWER of them. `water_context` is
        # the Overpass lookup and `rain_forecast` is open-meteo: different hosts,
        # different data, no shared state. Neither reads the other's result, so
        # asking for them together is safe and changes nothing that is returned.
        from concurrent.futures import ThreadPoolExecutor as _TPE

        with _TPE(max_workers=2) as pool:
            water_future = pool.submit(water_context, place)
            rain_future = pool.submit(rain_forecast, place["lat"], place["lon"])
            water = water_future.result()
            rain = rain_future.result()
        # STEP 12/13: the readings WITH their provenance, resolved against THIS
        # place - a real sample taken here, a sample from a named nearby source,
        # an earlier reading for this location, the measured dataset, or the
        # plain estimate. `place` and `water` are passed in because the answer
        # depends on both: the coordinates decide which stored sample is
        # relevant, and the identified source is what the "nearby source"
        # provenance is measured against.
        #
        # STEP 13: `water["primary"]` is null whenever no source is mapped AT the
        # location, even though a nearby one may exist. Falling straight through
        # with None would drop the location to the generic "no source" answer
        # and lose the fact that we DO know what water is around here, so the
        # nearest source's type is used for the estimate instead. It is still
        # only ever an estimate, and the note already says the readings are not
        # from this location.
        source_type = water.get("primary") or water.get("nearest_type")
        detail = default_parameters_detail(
            source_type,
            available=bool(water["available"]),
            place=place,
            water=water,
        )

        return success_response(
            data={
                "place": place,
                "in_scope": True,
                "scope_reason": None,
                "water": water,
                "rain": rain,
                "risks": risk_factors(water["types"]),
                # The coarse risk CATEGORY (low/moderate/high) the Location page
                # shows, derived only from the source type and the rain outlook.
                "risk_level": risk_level(water, rain),
                # Step 12: the readings are taken from the SAME detail object the
                # provenance describes, so the numbers on screen and the label
                # beside them can never disagree about what they are.
                "default_parameters": detail["values"],
                "default_parameters_detail": detail,
                # STEP 13: WATER SOURCE INFORMATION, EXPLICITLY.
                #
                # `water.primary` is non-null ONLY when a mapped source is within
                # EXACT_SOURCE_RADIUS_M of the selected point; otherwise it is
                # null and `water.nearby` carries the real list. The two are
                # published separately here so the UI cannot present a nearby
                # feature as "the water source for this location":
                #
                #   * `water_source_type`  - the source AT this location, or null
                #   * `nearby_sources`     - every real source found, with its
                #                             name (or an honest "Unnamed ..."
                #                             label), its type, and the distance
                #                             computed from real coordinates
                #   * `water_source_known` - which of the two the UI should show
                "water_source_type": water.get("primary"),
                "water_source_known": bool(water.get("exact")),
                "nearby_sources": water.get("nearby") or [],
                "supported_water_types": water.get("supported_types") or [],
                # The five parameters the brief names, in canonical order, so the
                # UI renders the list rather than hard-coding it.
                "parameter_definitions": [
                    {
                        "name": name,
                        "label": _FEATURE_LABELS[name],
                        "unit": _FEATURE_UNITS[name],
                    }
                    for name in FEATURE_NAMES
                ],
            }
        )
    except AquaGuardError as exc:
        return _failure(exc)


@location_bp.get("/water")
def water():
    """The water source at a location, and the sources near it.

    Accepts EITHER `lat` + `lon`, OR `name` (a place name, pincode or landmark),
    using the same resolution as `/context`. Coordinates win when both are given.

    Returns:

        place      the resolved place (so the UI can show "Selected Location")
        available  True only when OpenStreetMap has mapped water near the point
        message    the "unavailable" sentence when available is False
        primary    the type of the nearest real source
        types      the categories actually observed nearby
        nearby     real sources with their real distances, nearest first
        nearest    the closest source (also the first entry of nearby)

    NOTHING HERE IS INVENTED. Every source is a real OpenStreetMap feature with
    real coordinates; the distance is computed from those coordinates. When there
    is no mapped water, `available` is False and `message` is the honest
    "unavailable" sentence - no source is guessed.

    The admin location scope is enforced before any lookup runs.
    """
    try:
        from app.services.location_service import water_context, within_scope

        lat = _optional_coordinate("lat")
        lon = _optional_coordinate("lon")
        name = (request.args.get("name") or "").strip() or None
        if (lat is None or lon is None) and not name:
            return error_response("Provide either lat and lon, or a place name", 422)

        # Resolve the place the same way /context does, so the scope check and the
        # water lookup both run against one validated location.
        if lat is not None and lon is not None:
            from app.services.location_service import reverse as reverse_geocode

            resolved = reverse_geocode(lat, lon) or {}
            place = {
                "name": resolved.get("name") or name or f"{lat:.4f}, {lon:.4f}",
                "label": resolved.get("label"),
                "display_name": resolved.get("display_name"),
                "country": resolved.get("country"),
                "state": resolved.get("state"),
                "district": resolved.get("district"),
                "pincode": resolved.get("pincode"),
                "lat": lat,
                "lon": lon,
            }
        else:
            from app.services.location_service import search as search_places

            matches = search_places(name, limit=1)
            if not matches:
                return error_response(f"Could not find a place called {name!r}", 404)
            place = matches[0]

        state, country = _scope()
        verdict = within_scope(place, scope_state=state, scope_country=country)
        if not verdict["allowed"]:
            return error_response(
                verdict["reason"], 403, {"location": "outside the configured scope"}
            )

        return success_response(data={"place": place, "water": water_context(place)})
    except AquaGuardError as exc:
        return _failure(exc)


@location_bp.get("/country")
def country():
    """The country-level overview: every supported state and its water risk.

    Query parameters:

        q        the country to search (e.g. "India")
        limit    how many states to return (1..100, default 100)
        risk     "false" to skip the per-state water sampling and answer with
                 the state NAMES, the order, the legend and the summary in
                 milliseconds. Every row then reads "Insufficient data", which
                 is honest - it has not been measured yet - and the screen fills
                 the dots in on a second request.

    The brief's rule this endpoint implements: the state risk is CALCULATED
    from available water-quality data, never randomly assigned. Each state's
    indicator comes from the mapped water features near its centre, using the
    same derivation as the single-place `/context` risk, aggregated to one
    worst-observed level per state. A state the data cannot support gets
    `unknown` and the brief's "Insufficient data" wording, never an invented
    colour.

    STEP 18: the default limit is raised from 12 to 100. It was silently
    withholding most of the country — India has 36 states and union territories,
    so a 12-row answer claimed to show a country while hiding two thirds of it,
    and the brief asks for the country's states, not a sample of them.

    Responses: 200 with the country, its states, the legend and the summary;
    401 without a token; 422 when `q` is empty.
    """
    try:
        from app.services.country_service import country_overview

        query = (request.args.get("q") or request.args.get("query") or "").strip()
        if not query:
            return error_response("q is required", 422, {"q": "This field is required"})

        limit = request.args.get("limit", 100)
        try:
            limit = max(1, min(int(limit), 100))
        except (TypeError, ValueError):
            limit = 100

        with_risk = (request.args.get("risk") or "true").lower() not in (
            "0", "false", "no")

        return success_response(
            data=country_overview(query, limit=limit, with_risk=with_risk)
        )
    except AquaGuardError as exc:
        return _failure(exc)


@location_bp.get("/state")
def state_overview_route():
    """Step 20/17: the state-level overview — every district of the state.

    Query parameters:

        q        the state to search (e.g. "Tamil Nadu")
        limit    how many districts to return (1..100, default 100)
        risk     "false" to skip the per-district water sampling and answer
                 from the bundled district list alone, in milliseconds. The
                 names, state and country are identical either way; only the
                 risk summary is absent, and each row then reads `unknown`.

    STEP 17: THE LIST IS COMPLETE, NOT A SAMPLE.

    Typing a state's name returns EVERY district that belongs to it, ordered
    alphabetically with a `rank`, so the user can see the whole state at once
    and never has to click a district merely to discover that it exists. The
    default limit is raised to 100 because India's largest states exceed the
    old 60 - Uttar Pradesh has 75 districts, so a 60-row answer was silently
    withholding a quarter of the state it claimed to list.

    The brief's rule is unchanged: each district's risk is CALCULATED from the
    mapped water data at the district's centre, using the same derivation as
    the single-place `/context` risk, and a district the data cannot support
    gets `unknown` - never an invented colour. The response carries no
    individual place predictions: at state level the user sees districts only.

    Responses: 200 with the state, its districts, the legend and the summary;
    422 when `q` is empty.
    """
    try:
        from app.services.country_service import state_overview

        query = (request.args.get("q") or request.args.get("query") or "").strip()
        if not query:
            return error_response("q is required", 422, {"q": "This field is required"})

        limit = request.args.get("limit", 100)
        try:
            limit = max(1, min(int(limit), 100))
        except (TypeError, ValueError):
            limit = 100

        with_risk = (request.args.get("risk") or "true").lower() not in (
            "0", "false", "no")

        return success_response(
            data=state_overview(query, limit=limit, with_risk=with_risk)
        )
    except AquaGuardError as exc:
        return _failure(exc)


@location_bp.get("/district")
def district_overview_route():
    """Step 21: the district-level view — the nine places, labels hidden.

    Query parameter: `q` (the district to search, e.g. "Sivaganga").

    The response is the nine major / relevant places of the district, gathered
    into the brief's internal 3 SAFE / 3 MODERATE / 3 UNSAFE dataset — but the
    classification stays INTERNAL: each row carries only the fields the card
    displays (place name, town/village/area, district, state). No
    Safe/Moderate/Unsafe label, no colour and no prediction is exposed here;
    the verdict is revealed only when the user clicks a place and the existing
    analysis/prediction path runs.

    Nothing is randomly assigned: the banding comes from the same mapped-water
    derivation every other level uses, and a band the district genuinely does
    not have simply contributes fewer places.

    Responses: 200 with the district, its places and the internal composition;
    401 without a token; 422 when `q` is empty.
    """
    try:
        from app.services.country_service import district_overview

        query = (request.args.get("q") or request.args.get("query") or "").strip()
        if not query:
            return error_response("q is required", 422, {"q": "This field is required"})

        return success_response(data=district_overview(query))
    except AquaGuardError as exc:
        return _failure(exc)


@location_bp.get("/rain-alert")
def rain_alert():
    """The rain situation for the STATE the device is currently in.

    Query parameters: `lat` and `lon` (required) - the browser's own geolocation
    fix, which the Rainy Alerts screen obtains by asking for the permission. The
    backend never guesses a position and never defaults one; a request without
    coordinates is refused.

    WHAT IT DOES, in order: reverse-geocodes the point to a place, reads the
    STATE out of it, resolves that state's administrative centre BY NAME, and
    takes a live forecast there. So the answer is about a region rather than
    about one doorstep, and it works the same for every state - none is named
    anywhere in this code path.

    Responses:

        200 with the place, the state, the source and the forecast
        404 when the coordinates resolve to no place, or to a place with no
            state - the honest answer, rather than weather for somewhere else
        422 when `lat`/`lon` are missing or not numeric
    """
    try:
        from app.services.location_service import state_rain_alert

        lat = _coordinate("lat")
        lon = _coordinate("lon")
        result = state_rain_alert(lat, lon)
        if result is None:
            return error_response(
                "That location could not be matched to a state, so there is no "
                "regional rain forecast to show. The coordinates below are still "
                "used for the forecast if you allow it.",
                404,
                {"location": "no state could be resolved for these coordinates"},
            )
        return success_response(data=result)
    except AquaGuardError as exc:
        return _failure(exc)


@location_bp.get("/regional-alerts")
def regional_alerts():
    """Real rain outlooks for a sample of one state's districts.

    PROMPT 2, B.7-B.9. Accepts either `state` (a state name, e.g. "Tamil Nadu")
    or `lat` + `lon` (the device fix, whose state is reverse-geocoded here so
    the client never has to guess it). Each row is a REAL forecast read at that
    district's own coordinates - never a copy of one location's weather.

    Responses:

        200 with `available` true/false and the rows; a false answer with
            reason "forecast_unavailable" is the honest "alert data
            unavailable", distinct from "no active alerts found"
        422 when neither a state nor coordinates were supplied
    """
    try:
        from app.services.location_service import regional_rain_alerts, reverse as reverse_geocode

        lat = _optional_coordinate("lat")
        lon = _optional_coordinate("lon")
        state = (request.args.get("state") or "").strip() or None

        if not state and (lat is None or lon is None):
            return error_response("Provide either state, or lat and lon", 422)

        if not state and lat is not None and lon is not None:
            place = reverse_geocode(lat, lon) or {}
            state = (
                place.get("state")
                or place.get("district")
                or place.get("city")
            )
            if not state:
                return error_response(
                    "That location could not be matched to a state, so there is "
                    "no regional alert list to show.",
                    404,
                    {"location": "no state could be resolved for these coordinates"},
                )

        # THE CHOSEN POINT IS PASSED THROUGH. Without it the service could only
        # sample the state's districts in list order, so the same rows appeared
        # for every place in the state. With it the sample is biased to the
        # districts NEAREST the visitor's own location.
        return success_response(data=regional_rain_alerts(state, lat=lat, lon=lon))
    except AquaGuardError as exc:
        return _failure(exc)


@location_bp.get("/parameters")
def parameters():
    """The starting readings for a water source type, for the Predict form.

    Query parameter: `water_type` (e.g. "river water"). An unknown type returns
    the municipal-water defaults rather than an error, so the form is never left
    empty by a value the UI did not expect.
    """
    try:
        from app.services.location_service import default_parameters

        water_type = (request.args.get("water_type") or "").strip() or None
        return success_response(
            data={
                "water_type": water_type,
                "parameters": default_parameters(water_type),
            }
        )
    except AquaGuardError as exc:
        return _failure(exc)
