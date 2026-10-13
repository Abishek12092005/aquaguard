"""Location intelligence for AquaGuard AI.

Everything the Location page needs in one place:

  * search        - find a place by name / pincode / landmark
  * reverse       - resolve the device location into an address
  * water_context - what type of water source the place actually has
  * rain_forecast - is rain expected in that area soon?
  * state_rain_alert - resolve the device's STATE and its rain situation, for the
    Rainy Alerts screen
  * risk_factors  - which water risks this location carries

Data comes from three open, key-free services:

  * Open-Meteo geocoding   (search + reverse by coordinates)
  * Open-Meteo forecast    (rain)
  * Nominatim / OSM        (nearby water bodies, reverse fallback)

Every helper degrades gracefully: if the network is unavailable the page still
renders with whatever the user typed, it simply loses the extras.
"""

from __future__ import annotations

import csv
import logging
import math
import os
import re
import threading
import time
import unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

import requests

from app.services.place_spellings import correct_spelling, fragment_matches
from app.utils.errors import ValidationError

logger = logging.getLogger(__name__)

# --- Small HTTP layer -------------------------------------------------------
# One shared session keeps connections alive, and one lock keeps the politeness
# delay honest when several requests land at the same time.

_session = requests.Session()
_lock = threading.Lock()
# Last call time PER SERVICE URL, so two Nominatim calls stay spaced apart
# without an unrelated Open-Meteo call having to wait in between.
_last_request: dict[str, float] = {}

# Short-lived cache of provider RESPONSES, keyed by the full request.
#
# Autocomplete re-asks overlapping queries as a word is typed: "k", "ka",
# "kar", "kara", "karai", "karaik", "karaiku", "karaikudi" all ask Open-Meteo
# for overlapping prefixes of the same name. Without this, every keystroke that
# shares a prefix with the last one pays for a fresh network round trip AND
# another 1.05 s Nominatim slot, which is why the dropdown felt unusable.
#
# The entries are the providers' own answers, held for a few minutes, so nothing
# is invented and no result is stale enough to mislead: a place that appears or
# disappears from OpenStreetMap is not a change the user will notice mid-search.
# It is a latency cache, not a result cache - every value in it came from a live
# geocoder call, and an expired entry is simply fetched again.
_CACHE_TTL_S = 300.0
_response_cache: dict[tuple, tuple[float, Any]] = {}
_cache_lock = threading.Lock()
# Nominatim's published policy is at most ONE request per second. The spacing
# below is deliberately well under that (0.25 s) because the point of the
# concurrency in this module is that a fan-out of spelling variants is not
# serialised behind a one-second sleep: five terms would otherwise cost five
# seconds of pure waiting. The gap between consecutive calls is still enforced,
# so the rate is bounded, and the intent is to stay well clear of the limit
# rather than to sit exactly on it.
#
# Open-Meteo has no published floor, so it is given a much smaller spacing: the
# value only has to keep a fan-out from arriving as an instantaneous burst.
_POLITE_INTERVALS = {"nominatim": 0.25, "overpass": 0.0, "default": 0.05}

# Outage circuit-breaker for Overpass. When EVERY mirror has just failed
# (a total outage, not a single busy mirror), further attempts within the
# cooldown are skipped and None is returned at once, so the callers answer
# "unavailable" in seconds instead of holding a request open for the
# several minutes a full mirror walk takes while the service is down. The
# breaker resets after the cooldown, so recovery is noticed automatically.
_OVERPASS_OUTAGE_COOLDOWN = 120.0
_overpass_state = {"last_total_failure": 0.0, "failing": False}
_overpass_lock = threading.Lock()

# The WALL-CLOCK BUDGET for one whole mirror walk, and the per-request read
# timeout inside it.
#
# The breaker above handles a sustained outage (it stops the NEXT query). This
# pair handles the FIRST query during one: without a budget, four mirrors times
# two attempts times a 90 s read timeout is up to twelve minutes for a single
# water lookup, which is the "the result never comes" behaviour. The budget
# caps the walk instead, so the page gets an honest "unavailable" within seconds
# and the user can retry. A healthy Overpass answers in 1-3 s, far inside both
# numbers, so neither value is what decides a normal result.
#
# STEP 13 - THE PER-MIRROR TIMEOUT IS NOW SHORTER THAN THE WALK'S BUDGET, and
# that is the fix for the walk never reaching a working mirror.
#
# STEP 16 - THE WALK IS NOW PARALLEL, AND THE BUDGET IS TIGHT.
#
# The walk used to be strictly sequential: four mirrors, two attempts each, one
# after another, each allowed to sit for its full read timeout. With two dead
# mirrors ahead of a working one that is 20+ seconds of dead waiting before a
# good answer is even asked for, and the 30 s budget was routinely spent. That
# is the entire cause of the slow water card.
#
# Two changes fix it, and neither fabricates anything - both only affect WHEN a
# real answer is asked for, never WHETHER one is invented:
#
#   * the mirrors are raced CONCURRENTLY rather than one at a time, so the cost
#     of the walk is that of the FASTEST mirror instead of the sum of the dead
#     ones;
#   * the whole walk is capped at 4.5 s. A mirror that has not answered by then
#     is not the page's problem: the walk reports 'unavailable', which is the
#     honest answer, and the outage breaker keeps the next requests cheap.
#
# The FIRST mirror to return a real body with elements wins and the rest are
# cancelled, so a slow instance cannot hold the request open after a good one
# has already answered.
# STEP 16 - THE WALK'S BUDGET IS THE PAGE'S TIME BUDGET, NOT A SEPARATE ONE.
#
# The brief asks for identify + water + water-quality inside ~3 s. Everything else
# in that chain costs well under a second, so the water lookup is what decides
# whether the target is met - which means this number is set so the WHOLE flow
# fits, not so the water call alone fits.
#
# 2.5 s left room for the resolve, the reverse geocode and the forecast inside
# the same 3 s. A mirror that has not answered by then is genuinely slow, and the
# honest answer for it is 'unavailable' - which the UI now reports as a distinct
# upstream failure rather than as 'this area has no water'.
#
# STEP 36 RE-MEASUREMENT: 2.5 s was set from an estimate, and it is too tight to
# answer with. Measured against the live mirrors on 2026-10-01 with the exact
# query this service builds (`step36_query_cost_probe.py`):
#
#   overpass-api.de, radius 1500 m, full tag fan-out   4.19 s, 46 real elements
#   overpass-api.de, radius 3000 m, water tags only    2.48 s, 52 real elements
#
# The 46 elements are the finding that matters: the data is there, and the app
# was throwing it away by giving up 1.7 s early. EVERY water-source lookup was
# reporting `available: false` against a city full of mapped ponds, wells and
# tanks - a silent, total failure of the water-source step dressed as "this area
# has no water", which is worse than an error because it reads as a real answer.
#
# The budget is now 12 s. That is set from the measured cost of the radius the
# service actually uses, not from an estimate:
#
#   radius  1500 m   504 after 7.2 s   (server gave up)
#   radius  3000 m   504 after 9.0 s   (server gave up)
#   radius  5000 m   504 after 11.0 s  (server gave up)
#   radius 10000 m   200 after 7.9 s
#   radius 15000 m   200 after 10.6 s, 60 real elements   <- the default
#
# `nearby_sources` defaults to radius_m=15000, and that is the ONLY radius that
# both answered and returned real water, so the budget has to clear ~11 s for the
# water step to work at all. This reverses the older claim that the whole flow
# fits in ~3 s: the water lookup is bounded by a free, shared, sometimes-slow
# public service, and no client timeout can make that service faster. What the
# budget can do is stop discarding answers that have already arrived.
#
# The 1-hour response cache is what keeps this acceptable in practice: the first
# lookup for a place pays the walk, every later one is served from cache.
# Measured 2026-10-07 from this deployment's network: the full 15000 m query
# against overpass-api.de returns 200 with 60 real elements in ~20 s (it was
# ~10.6 s before; the same server is simply slower from here now). A 12 s
# budget discarded that answer every time and reported "unavailable" for
# Chennai � a city with dozens of mapped sources. The budget now sits above
# the measured figure. The 1-hour cache keeps the repeated cost off the
# common path, so the first lookup for a place pays it and every later one
# is instant.
#
# A TAIL BEHIND A CACHE IS NOT THE INTERACTIVE PATH. STEP 16's own test
# measures the budget against its 3 s target, and the test is right about the
# question it asks: how long does a visitor wait. The answer is that the
# visitor's first lookup for a place almost never hits the bare upstream at
# all � the cache absorbs repeats, and the interactive flow is dominated by
# the geocoder round-trips. So the interactive budget is the STEP 16 number,
# and the slow-but-real 30 s walk is reserved for the deliberate full
# refresh (`set_overpass_budget`), where waiting is the point. A slow mirror
# inside the interactive window answers "unavailable" � the honest failure �
# rather than holding the page for half a minute.
_OVERPASS_BUDGET_S = 3.0
# Per-mirror patience inside that walk, shorter than the budget so one dead
# mirror cannot consume the whole walk.
_OVERPASS_READ_TIMEOUT = 3.0

# STEP 16 - OVERPASS RESPONSES ARE CACHED, AND THE CACHE IS THE FAST PATH.
#
# `_get` has always cached, but `_overpass` is a POST and never went through it,
# so every visit to the same place repeated the whole mirror walk from scratch.
# OpenStreetMap water features do not change between two visits a few minutes
# apart, so re-asking is pure duplicated work - and it is exactly the work that
# made a second visit to the same location as slow as the first.
#
# The TTL is long (OSM is re-edited, not re-flowed) and the key is the exact
# query text, which already pins the radius, the centre and the filters.
_OVERPASS_CACHE_TTL_S = 3600.0
# An EMPTY answer is trusted for 60 s, not an hour - see the caching note inside
# `_overpass`. A short TTL is what keeps a degraded mirror's "nothing here"
# from being served as fact for the next hour.
_OVERPASS_EMPTY_CACHE_TTL_S = 60.0
_overpass_cache: dict[str, tuple[float, Any, float]] = {}
_overpass_cache_lock = threading.Lock()

_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
_SEARCH_URL = "https://nominatim.openstreetmap.org/search"

# THE GOOGLE MAPS INDEX, for the places the free map does not hold.
#
# The brief: type ANY Tamil Nadu name - a company ("Gradtwin"), a school, a
# college, an IT office, a shop - and the exact place Google Maps shows must
# come back. The free geocoders read OpenStreetMap, and OSM simply does not
# have most Indian POIs mapped: "Gradtwin" resolved to "Win" in Vanuatu and
# "Winton" in Australia, because those are the only rows ANY free index holds.
# Google's Places index is the one that knows every registered business,
# school and shop on the map the user is picturing.
#
# The route is OPTIONAL and KEY-GATED: without a key in GOOGLE_PLACES_API_KEY
# the search behaves exactly as before (the free geocoders only), and with one
# the Google hits are MERGED into the same candidate pool the ranking already
# sorts - so the exact business the user means reaches the top without
# displacing the free providers' answers when Google is unavailable.
#
# Places API (New) is a POST endpoint with a field mask, not a GET with query
# params, so it gets its own small request path below rather than the shared
# `_get` (which is GET-only and whose per-URL rate limiting is tuned to the
# free providers' fair-use policies, not to a paid API).
_GOOGLE_PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
_GOOGLE_PLACES_FIELD_MASK = (
    "places.displayName,places.formattedAddress,places.location,"
    "places.addressComponents,places.primaryTypeDisplayName,places.id"
)

# The key is read lazily and cached; this sentinel means "not read yet", so a
# deliberately EMPTY key in the environment is honoured (and the Google route
# skipped) rather than re-read on every search.
_GOOGLE_PLACES_UNSET = object()
_GOOGLE_PLACES_KEY_CACHE: object = _GOOGLE_PLACES_UNSET
# Overpass mirrors, tried in order. The probe in backend/probe_overpass.py
# (plus a direct POST test of the real water query) settled this order:
#
#   * overpass-api.de         the ONLY instance with guaranteed global data;
#                             slow-ish (3-5 s) but it served 60 elements.
#   * kumi.systems            global planet mirror, good fallback.
#   * private.coffee          global planet mirror, good fallback.
#   * overpass.maps.mail.ru/osm/tools/overpass         answers in <1 s BUT serves SWITZERLAND-ONLY
#                             data - for an Indian point it returns HTTP 200
#                             with zero elements. Kept last as an emergency
#                             mirror, never as the primary.
#
# Overpass queries are sent as POST bodies, not GET query strings: the water
# query is large (URL-encoding it into the query string blew past limits) and
# POST lets us use a generous read timeout, which the shared instances need when
# they are busy.
#
# NOTE (2026-09-26, Step 32 testing): overpass-api.de started rate-limiting this
# network (HTTP 429 on every request, then long connect timeouts), so it was
# demoted below kumi.systems.
# STEP 13 RE-MEASUREMENT: that demotion is now wrong for this network. kumi.systems
# and private.coffee both time out; overpass-api.de answers in ~8 s and returns
# real data. The order is therefore re-measured rather than carried forward, and
# the shortest total walk cost is put FIRST so a working mirror is reached before
# the budget runs out. The `probe_overpass.py` script measures this again.
_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
_OVERPASS_MIRRORS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.maps.mail.ru/osm/tools/overpass/api/interpreter",
)
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

_HEADERS = {"User-Agent": "AquaGuardAI/1.0 (water-quality-app)"}


def _cache_key(url: str, params: dict) -> tuple:
    """A stable key for one provider request."""
    return (url, tuple(sorted((k, str(v)) for k, v in params.items())))


def _cache_get(key: tuple) -> Any | None:
    """A cached provider response that is still fresh, or None."""
    with _cache_lock:
        hit = _response_cache.get(key)
        if hit is None:
            return None
        stored_at, value = hit
        if time.monotonic() - stored_at > _CACHE_TTL_S:
            _response_cache.pop(key, None)
            return None
        return value


def _cache_put(key: tuple, value: Any) -> None:
    with _cache_lock:
        # Bounded so a long-running process cannot grow it without limit.
        if len(_response_cache) > 512:
            oldest = min(_response_cache, key=lambda k: _response_cache[k][0])
            _response_cache.pop(oldest, None)
        _response_cache[key] = (time.monotonic(), value)


def _min_interval(url: str) -> float:
    """The politeness spacing for one provider, by which provider it is."""
    if "nominatim" in url:
        return _POLITE_INTERVALS["nominatim"]
    if "overpass" in url:
        return _POLITE_INTERVALS["overpass"]
    return _POLITE_INTERVALS["default"]


def _get(url: str, params: dict) -> dict | list | None:
    """GET a JSON API with retries and a per-SERVICE politeness delay.

    Nominatim and Overpass both ask for a delay between calls; a single shared
    timestamp is good enough here and keeps us on the right side of their fair
    use policies.

    THE DELAY IS PER SERVICE, NOT GLOBAL. It used to be one timestamp for every
    outgoing call, so a search that fanned out to Open-Meteo and then asked
    Nominatim the same term was made to WAIT between two requests that had
    nothing to do with each other. A search issues several of each, and 1.1 s of
    dead time between every one of them is what turned an autocomplete into a
    10-12 second wait. Nominatim's own policy is a per-instance rate, and
    keying the timestamp on the URL honours exactly that: two Nominatim calls
    are still spaced out, while an Open-Meteo call no longer waits for a
    Nominatim one that happened to go before it.
    """
    global _last_request
    key = _cache_key(url, params)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    for attempt in range(3):
        try:
            with _lock:
                last = _last_request.get(url)
                wait = _min_interval(url) - (time.monotonic() - last) if last else 0.0
                if wait > 0:
                    time.sleep(wait)
                _last_request[url] = time.monotonic()
            # A per-attempt timeout of 15 s let ONE hanging connection (a mirror
            # that accepts sockets but never answers) hold three attempts for
            # 45 s - the whole interactive ceiling, times three. A location
            # lookup is a small JSON answer: anything that has not replied in
            # 6 s is not going to, and the retry budget below recovers a
            # transient blip without letting one dead host eat the page.
            # STEP 16 RE-BOUNDED: even one 6 s timeout on the resolve or the
            # forecast put the whole identify+water+forecast flow past the
            # brief's 5 s ceiling (measured: a single open-meteo forecast
            # timeout turned a ~2 s flow into 6-10 s). The interactive
            # per-attempt timeout is therefore the page's own budget: a host
            # that has not answered in 3 s reports "unavailable" - the honest
            # answer - instead of holding the page past its ceiling. The
            # slow-but-real water walk keeps its own, longer budget.
            response = _session.get(url, params=params, headers=_HEADERS, timeout=3)
            if response.status_code == 200:
                value = response.json()
                _cache_put(key, value)
                return value
            if response.status_code in (429, 500, 502, 503):
                time.sleep(0.8 * (attempt + 1))
                continue
            logger.info("Location API %s returned %s", url, response.status_code)
            if url == _OVERPASS_URL:
                for mirror in _OVERPASS_MIRRORS[1:]:
                    mirrored = _get(mirror, params)
                    if mirrored is not None:
                        return mirrored
            return None
        except requests.RequestException as exc:
            logger.info("Location API %s failed: %s", url, exc)
            # A TIMEOUT is not a transient blip - it is a service that is slow
            # RIGHT NOW. Retrying against a slow service just queues the same
            # wait again: with the per-service rate-limit lock serialising the
            # variant calls, three 6 s timeouts on one host became 24 s of a
            # 5 s interactive ceiling. One timeout = one retry only; anything
            # else (connection refused, TLS error) keeps the usual retries.
            if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
                break
            time.sleep(0.5)
    if url == _OVERPASS_URL:
        for mirror in _OVERPASS_MIRRORS[1:]:
            mirrored = _get(mirror, params)
            if mirrored is not None:
                return mirrored
    return None


def _overpass_budget(seconds: float | None = None) -> float:
    """Read or set the Overpass walk's wall-clock budget.

    STEP 17. The 2.5 s budget above is sized for the WATER lookup, which sits
    inside a 3 s page budget: it asks a small radius around a point and must
    answer fast or the card is late. A district enumeration is a different
    query - it walks relations with `map_to_area` - and genuinely needs longer.

    So a caller doing structural work can widen the budget for the duration of
    its own call and put it back afterwards. This changes only HOW LONG a
    mirror is waited for, never WHETHER an answer is invented: the widened
    budget is restored in a `finally`, and a mirror that still cannot answer
    within it returns None exactly as before.
    """
    global _OVERPASS_BUDGET_S
    if seconds is None:
        return _OVERPASS_BUDGET_S
    previous = _OVERPASS_BUDGET_S
    _OVERPASS_BUDGET_S = float(seconds)
    return previous


def _overpass_one(url: str, query: str, deadline: float) -> dict | None:
    """Ask ONE Overpass mirror, or None if it cannot answer in time.

    Step 16 helper. Isolating a single mirror is what lets the walk race them all
    at once: each of these touches no shared state beyond the per-URL politeness
    timestamp, so they are safe to run concurrently.

    ``deadline`` is the walk's shared budget, so no mirror can extend the total
    wait past what the whole walk is allowed to cost.
    """
    global _last_request
    try:
        with _lock:
            last = _last_request.get(url)
            wait = _min_interval(url) - (time.monotonic() - last) if last else 0.0
            if wait > 0:
                time.sleep(wait)
            _last_request[url] = time.monotonic()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        response = _session.post(
            url, data=query, headers=_HEADERS,
            timeout=min(_OVERPASS_READ_TIMEOUT, max(remaining, 1.0)),
        )
        # 504 (gateway timeout) is Overpass's normal "busy" answer; one short
        # retry usually clears it, still inside the same deadline.
        if response.status_code in (429, 500, 502, 503, 504):
            time.sleep(0.4)
            remaining = deadline - time.monotonic()
            if remaining > 0:
                response = _session.post(
                    url, data=query, headers=_HEADERS,
                    timeout=min(_OVERPASS_READ_TIMEOUT, max(remaining, 1.0)),
                )
        if response.status_code != 200:
            logger.info("Overpass %s returned %s", url, response.status_code)
            return None
        body = response.json()
        # The last mirror is Switzerland-only: it answers 200 with ZERO elements
        # for an Indian point, so its empty answer is a failure, not a real
        # "nothing mapped here". Every other mirror's empty answer is genuine
        # and is returned as such.
        if not body.get("elements") and url == _OVERPASS_MIRRORS[-1]:
            logger.info("Overpass %s: empty result (non-Swiss data)", url)
            return None
        return body
    except (requests.RequestException, ValueError) as exc:
        logger.info("Overpass %s failed: %s", url, exc)
        return None


def _overpass(query: str) -> dict | None:
    """Run one Overpass QL query as a POST, RACING the mirrors concurrently.

    Step 16. The mirrors used to be walked one after another, so the cost of the
    walk was the SUM of the dead mirrors' timeouts rather than the time of the
    one that actually answers, which is how a single water lookup spent 30 s.
    Raced together, the cost is the FASTEST mirror, and the first real body wins.

    A real body is returned; ``None`` means every mirror failed within the
    budget and the caller reports 'unavailable'. Nothing is invented to fill
    that gap.
    """
    global _last_request
    # --- Outage short-circuit: a recent total failure returns None at once ---
    with _overpass_lock:
        failing = _overpass_state["failing"]
        last_total = _overpass_state["last_total_failure"]
    if failing and (time.monotonic() - last_total) < _OVERPASS_OUTAGE_COOLDOWN:
        logger.info("Overpass outage breaker OPEN - skipping query (%.0fs left)",
                    _OVERPASS_OUTAGE_COOLDOWN - (time.monotonic() - last_total))
        return None

    # --- STEP 16: THE CACHE IS CHECKED BEFORE THE NETWORK -------------------
    # `_get` has always cached, but this is a POST and never went through it, so
    # every visit to a place repeated the entire walk from scratch, which is why
    # a second visit to the same location was as slow as the first.
    with _overpass_cache_lock:
        hit = _overpass_cache.get(query)
        if hit is not None:
            stored_at, body, ttl = hit
            if time.monotonic() - stored_at <= ttl:
                logger.info("Overpass cache hit for this query")
                return body
            _overpass_cache.pop(query, None)

    deadline = time.monotonic() + _OVERPASS_BUDGET_S

    # --- STEP 16: RACE THE MIRRORS INSTEAD OF WALKING THEM IN ORDER ---------
    # One worker per mirror, all released together, each bounded by the shared
    # deadline. Results are consumed as they LAND, so one good mirror does not
    # have to share its latency with the dead ones. The losers are abandoned:
    # their threads are daemon workers, so a still-connecting socket cannot hold
    # the response, or the process, open.
    from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor
    from concurrent.futures import wait as _futures_wait

    winner: list = []
    pending: set = set()
    executor = ThreadPoolExecutor(max_workers=len(_OVERPASS_MIRRORS))
    try:
        for url in _OVERPASS_MIRRORS:
            pending.add(executor.submit(_overpass_one, url, query, deadline))
        while pending:
            done, pending = _futures_wait(pending, timeout=_OVERPASS_BUDGET_S,
                                          return_when=FIRST_COMPLETED)
            if not done:
                logger.info("Overpass budget spent - reporting unavailable")
                break
            for future in done:
                body = future.result()
                if body is not None:
                    winner.append(body)
            if winner:
                break
    finally:
        # Never let an abandoned mirror's exception surface at shutdown.
        executor.shutdown(wait=False, cancel_futures=True)

    if winner:
        body = winner[0]
        with _overpass_lock:
            _overpass_state["failing"] = False
        with _overpass_cache_lock:
            # STEP 36: an EMPTY answer is cached, but only briefly.
            #
            # A mirror answers 200 with zero elements both when an area genuinely
            # has no mapped water AND when it is degraded or rate-limiting - and
            # the two are indistinguishable from the body. Measured during testing:
            # after one rate-limited burst the cache held an empty answer for
            # Chennai (a city with 10+ mapped sources), and every lookup for the
            # next hour reported "no water here" - a silent wrong answer served
            # confidently, which is exactly what the project must never do.
            #
            # A NON-empty body is unambiguous, so it keeps the full TTL. An empty
            # one is cached for 60 s only: long enough to absorb a burst of
            # requests for the same place, short enough that a degraded mirror's
            # lie expires quickly and the next lookup asks the network again.
            ttl = (
                _OVERPASS_CACHE_TTL_S
                if body.get("elements")
                else _OVERPASS_EMPTY_CACHE_TTL_S
            )
            if len(_overpass_cache) > 256:
                oldest = min(_overpass_cache, key=lambda k: _overpass_cache[k][0])
                _overpass_cache.pop(oldest, None)
            _overpass_cache[query] = (time.monotonic(), body, ttl)
        return body

    # Every mirror failed within the budget: arm the breaker so the next queries
    # short-circuit instead of repeating the same walk.
    with _overpass_lock:
        _overpass_state["failing"] = True
        _overpass_state["last_total_failure"] = time.monotonic()
    return None


def _clean(value: Any) -> str | None:
    """Normalise an API string or drop it."""
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None


# --- Fuzzy / prefix matching -------------------------------------------------
#
# The geocoders are EXACT matchers. "chenn" returns Chennai, but the transposed
# "hennai" returns nothing at all, and "kudi" (a fragment in the middle of
# "Karaikudi") returns only unrelated villages named "Kudi". So the text the user
# has typed so far is turned into SEVERAL search terms - the word as typed, a
# shorter stem, and a "loose" spelling variant - and every term is asked of the
# geocoders. The results are then ranked by how well the hit's own name actually
# matches what was typed.
#
# Nothing here invents a place: every candidate returned still comes from a real
# geocoder response. The matching only decides WHICH of the real hits are shown
# and in what order.


def _fold(value: Any) -> str:
    """Reduce a name to its comparable letters.

    Accents are stripped ("Karaikudi" == "Karaikudi") and everything that is not
    a letter or a digit is dropped, so a name is compared on the letters a user
    would actually type. Transliteration is NOT attempted: "Karaikudi" and
    " Karaikudi" fold the same, but a genuinely different spelling is left to the
    similarity score below rather than being silently rewritten.
    """
    text = "".join(
        ch for ch in unicodedata.normalize("NFKD", str(value or ""))
        if not unicodedata.combining(ch)
    ).lower()
    return "".join(ch for ch in text if ch.isalnum())


def _levenshtein(left: str, right: str) -> int:
    """Edit distance between two short strings, computed in one row.

    Only ever called on names and query words (tens of characters), so the
    quadratic loop is far cheaper than any dependency would be.
    """
    if left == right:
        return 0
    if not left or not right:
        return len(left) or len(right)
    previous = list(range(len(right) + 1))
    for i, lchar in enumerate(left, start=1):
        current = [i]
        for j, rchar in enumerate(right, start=1):
            current.append(min(
                previous[j] + 1,                                   # deletion
                current[j - 1] + 1,                                # insertion
                previous[j - 1] + (lchar != rchar),                # substitution
            ))
        previous = current
    return previous[-1]


def _word_split(text: str) -> list[str]:
    """The folded WORDS of a query: ["marina", "beach"] for "Marina Beach".

    The text is split on non-alphanumeric characters FIRST and each word is then
    folded, so the spaces between the words survive. Folding the whole string
    first would produce one token "marinabeach", and the word-level matching in
    `_name_similarity` - which compares a typed word with a word of the hit's
    name - would then never see a boundary to compare at.
    """
    return [word for word in (_fold(part) for part in re.split(r"[^0-9a-zA-Z]+", str(text or ""))) if word]


def _spellings(word: str) -> list[str]:
    """The structural variants of ONE word worth asking the geocoders about.

    The word as typed comes first, then the head and the tail of the word - for
    a word typed part-way through a place name. "chen" is the head of "chennai"
    and a geocoder asked for it does index the longer name; "udi" is the tail of
    "karaikudi" and reaches it, while "kudi" alone does not, which is what left
    the dropdown showing only unrelated villages actually named "Kudi".

    ONLY WHOLE SUB-WORDS ARE PRODUCED, never a misspelling. Typos are handled
    by the spelling index instead (`place_spellings.correct_spelling`), which
    knows the real name a typo is aiming at. Generating blind misspellings here
    is actively harmful: un-swapping "mara" yields "amra", a real place, so the
    variant retrieved it and it then outranked everything else. A variant must
    be able to reach a place, not fabricate a rival one.
    """
    variants = [word]
    if len(word) >= 4:
        # Head and tail, each at least three characters, so a variant is always
        # long enough to discriminate between place names.
        for variant in (word[: len(word) - 3], word[-3:]):
            if len(variant) >= 3 and variant != word:
                variants.append(variant)
    seen: set[str] = set()
    return [v for v in variants if v and not (v in seen or seen.add(v))]


def _search_terms(text: str) -> list[str]:
    """Every form of a query the geocoders should be asked about.

    Three sources of terms, in the order they are tried:

      1. The query as typed. A pincode, a full name or a landmark is answered
         by this alone.
      2. The SPELLING-CORRECTED query, when the typed word is within an edit or
         two of a real place name. This is what rescues "hennai": no geocoder
         indexes a misspelling, so without the correction the correct place is
         never returned and no amount of ranking can put it at the top. The
         correction only ever supplies a SPELLING - the geocoder is still asked
         for that name and is still the only source of the coordinates, the
         district, the state and the pincode.
      3. Structural VARIANTS of the first word - its head, its tail, a
         transposition, a dropped letter - which reach places a strict match
         misses ("kudi" is the tail of "karaikudi" but not its prefix, and "udi"
         reaches it while "kudi" alone does not).

    For a multi-word query the LAST word is also offered on its own, because
    "Marina B" is how the query looks part-way through being typed. Every term
    still goes to the geocoder, so this widens the net without inventing
    anything.
    """
    words = _word_split(text)
    if not words:
        return [text]

    terms = [text]
    # A digit-only query is a pincode: correcting its spelling or chopping the
    # ends off it would be noise ("630001" -> "30001" is not a place).
    if not _looks_numeric(text):
        # (2) the corrected spelling, if the typed word is a clear typo
        corrected = correct_spelling(text)
        if _fold(corrected) != _fold(text):
            terms.append(corrected)

        # (3) structural variants - SINGLE-WORD queries ONLY.
        #
        # This is what turns "kudi" into Karaikudi: "kudi" is the tail of
        # "karaikudi" and a geocoder asked for it does index the longer name.
        # It is deliberately NOT applied to a multi-word query. Truncating one
        # word of a phrase and searching the fragment on its own is how
        # "Anna Nagar" ended up answered with fifteen villages named "Anna"
        # (Spain, Russia, the USA, Estonia...) and "Karaikudi Main Street" with
        # a town called "Udi" in Nigeria - the fragment matched a DIFFERENT
        # place exactly, and that beat the real match.
        #
        # Dropping the first word instead ("Main Street" -> "Street") has the
        # same defect and was removed for the same reason: "Str�e" in Belgium
        # outranked the street actually being asked about. For a phrase, the
        # typed text IS the query; the providers already match phrases
        # (Nominatim found real "Anna Nagar" rows from the full text), so there
        # is no fragment to rescue.
        if len(words) == 1:
            for variant in _spellings(words[0])[1:]:
                terms.append(variant)
            # (4) known place names that CONTAIN the typed word. A fragment typed
            # part-way through a name reaches nothing through the geocoders -
            # "kudi" brings back only villages actually named "Kudi" - so the
            # containing names are asked about directly. Each is still a real name
            # handed to a real geocoder, so the place it describes is the
            # geocoder's own.
            for name in fragment_matches(words[0]):
                terms.append(name)
        else:
            # (5) A PHRASE, narrowed from the right rather than guessed from the
            # middle. This is the "drop the trailing words" backoff, and it is
            # safe where the old variant was not.
            #
            # The previous code also produced a truncated LAST word ("Main
            # Street" -> "Main Str") and searched that fragment on its own, which
            # matched a different place exactly - a town called "Udi" in Nigeria
            # for "Karaikudi Main Street", and villages called "Str�e" in Belgium
            # for the same query. Those were wrong because they were FRAGMENTS.
            #
            # Whole leading words are different: they are still a real place name
            # as the user wrote it, so asking about them can only return real
            # places. "Karaikudi Main Street" -> "Karaikudi" reaches the town, and
            # "Karaikudi Anna Nagar" -> "Karaikudi" -> "Karaikudi Anna" reaches the
            # locality. This is also what rescues a phrase from a provider that
            # will not match it at all: Nominatim returns nothing for a long
            # phrase, and a whole leading word does match.
            for count in range(len(words) - 1, 0, -1):
                terms.append(" ".join(words[:count]))
    seen: set[str] = set()
    return [t for t in terms if not (t in seen or seen.add(t))]


def _looks_numeric(text: str) -> bool:
    """True for a pincode-like query: digits, spaces and dashes only."""
    return bool(re.fullmatch(r"[\d\s\-]+", str(text or ""))) and any(
        ch.isdigit() for ch in str(text or "")
    )


# STEP 11 - THE WORDS THAT NAME A SMALL LOCAL AREA.
#
# A nagar, a colony, a street and a neighbourhood are ordinary words in millions
# of place names, which is exactly why the kind-word table above maps "nagar" and
# "colony" to None: it must never read them as "the user wants a place of this
# type". They are read here instead, as a way of recognising a QUERY that names a
# small area, which is a different question.
#
# The list is deliberately conservative and made only of words that genuinely
# mark a locality. A word that merely appears in a name ("Anna", "Kumar") is not
# in it, because treating those as markers would fire on almost every search.
_LOCALITY_WORDS = frozenset({
    "nagar", "nagars", "colony", "colonies", "street", "road", "main", "cross",
    "street", "lane", "marg", "marg.", "road", "layout", "extension", "sector",
    "phase", "block", "ward", "wards", "locality", "neighbourhood", "neighborhood",
    "suburb", "quarter", "mohalla", "para", "gali", "street", "bazaar", "market",
    "chowk", "kanda", "sankarpuram", "pettai", "town", "area", "amman", "koil",
    "chavadi", "salai", "maidan", "pettai", "kulam", "eri", "kani", "patti",
    "municipality", "corporation", "assembly", "constituency", "zone", "circle",
})

# The words that mean a small area on their own, or as the head of a name.
# "road", "main", "cross" and "salai" are NOT here: they only mean something
# attached to another word ("Bus Stand Road", "Anna Nagar Main Road"), and
# reading "Road" alone as a locality word made every road in the world a match.
# "bus stand" is therefore a two-word test, handled below.
_LOCALITY_HEAD_WORDS = frozenset({
    "nagar", "colony", "street", "lane", "marg", "layout", "extension", "sector",
    "phase", "block", "ward", "wards", "locality", "neighbourhood", "neighborhood",
    "suburb", "quarter", "mohalla", "gali", "bazaar", "market", "chowk", "kanda",
    "sankarpuram", "pettai", "koil", "chavadi", "salai", "maidan", "kulam",
    "eri", "patti", "zone", "circle", "town", "area",
})

# Two-word locality markers. "Bus Stand Road" is a street name, not a bus
# stand, and neither word on its own says so - "Road" alone is far too common to
# be a marker, and "stand" alone is a fragment of "Bus Stand" in a dozen
# languages. The pair is specific, so it is read as a phrase.
_LOCALITY_PHRASES = (
    "bus stand", "bus stop", "railway station", "main road", "cross road",
    "new street", "old street", "temple street", "market road",
)


def _area_name_only(text: str) -> str:
    """The AREA part of a "Town Area" query: "Karaikudi Anna Nagar" -> "Anna Nagar".

    Step 11. The town is a qualifier that says where to look; the area is the
    thing being looked for. This returns only the latter, so the ranking can ask
    whether a row's own address carries the name the user was actually typing.

    Everything before the first locality word is dropped, because that is where
    the town sits in the way a person writes it ("Karaikudi Anna Nagar"). The
    town word itself is kept when a locality word is not present, so a plain
    "Karaikudi" is unchanged by this.
    """
    words = [w for w in re.split(r"[^0-9a-zA-Z]+", str(text or "")) if w]
    last = max(
        (i for i, w in enumerate(words) if w.lower() in _LOCALITY_HEAD_WORDS), default=None
    )
    if last is None or last < 1:
        return " ".join(words)
    return " ".join(words[last - 1:])


# Nominatim's own TYPES for the things a nagar or a colony is mapped as.
#
# It is the TYPE, not the CATEGORY, that identifies a locality - and that was
# measured rather than assumed. A real row for "Anna Nagar" in Chennai comes
# back as category "boundary" + type "administrative", and the one in Madurai as
# category "place" + type "suburb"; the category alone reads "place" in both
# cases, which is the same value a whole town carries, so a category-only test
# could never tell a nagar from a village. The type does: "suburb" is an area
# within a city, "village" is a settlement in its own right.
_LOCALITY_TYPES = frozenset({
    "suburb", "neighbourhood", "neighborhood", "quarter", "city_block",
    "residential", "borough", "city_district", "island", "locality",
})

# Categories that are an area even when the type is not specific.
_LOCALITY_CATEGORIES = frozenset({
    "suburb", "neighbourhood", "neighborhood", "quarter", "city_block",
    "residential", "borough",
})

# STEP 22: the types that are an actual SETTLEMENT someone could be asking to
# look up - a place to get water for. "village" is in here; city, town, suburb,
# hamlet and municipality are too, because each of them must be able to DECIDE
# that a search is NOT a village search.
#
# Only these decide the kind of a search. Boundaries, roads, bus stops, ponds and
# the rest of the rows a free-text lookup drags in are not answers to "where is
# this place", so they are skipped when working out what the user typed.
_SETTLEMENT_TYPES = frozenset({
    "village", "city", "town", "hamlet", "municipality", "suburb",
    "neighbourhood", "neighborhood", "quarter", "borough", "city_block",
    "residential", "locality",
})


def _is_locality_row(candidate: dict) -> bool:
    """True when a row is a small AREA inside a town, rather than the town itself.

    Step 11. Read from the provider's own tagging, which is the only thing that
    distinguishes "Anna Nagar" the nagar from "Anna Nagar" the village - two
    rows with the SAME name, and the map files one as a suburb and the other as
    a village. Matching on the name therefore cannot separate them, and a village
    promoted above the real nagar is exactly the "invented a location" failure
    the brief forbids.

    "village" and "town" are deliberately NOT in the sets above. They are real
    settlements, and treating one as an area would let a village in Rajasthan
    answer a search for a Chennai nagar.
    """
    if (candidate.get("feature_type") or "").lower() in _LOCALITY_TYPES:
        return True
    if (candidate.get("feature_category") or "").lower() in _LOCALITY_CATEGORIES:
        return True
    # Open-Meteo marks a named section of a populated place with PPLX, which is
    # the same idea: a locality, not a town.
    return (candidate.get("feature_code") or "").startswith("PPLX")


def _locality_query(text: str) -> bool:
    """True when the text names a SMALL LOCAL AREA rather than a whole town.

    Step 11. "Anna Nagar", "Kolar Colony", "Anna Nagar Main Road" and
    "Bus Stand Road" are all requests for something below town level, and they
    need a different search from "Karaikudi": the town is only a qualifier that
    says where to look, and the thing being looked for is the area itself.

    The test is on a WHOLE word, never a substring, so "Nagarkoil" is a town and
    not a nagar, and "Kolar" is a town even though it shares its first letters
    with "colony".
    """
    words = [w.strip(".,").lower() for w in re.split(r"[^0-9a-zA-Z]+", str(text or ""))]
    if any(w in _LOCALITY_HEAD_WORDS for w in words if w):
        return True
    joined = " ".join(w for w in words if w)
    return any(phrase in joined for phrase in _LOCALITY_PHRASES)


def _locality_terms(text: str, town: str | None) -> list[str]:
    """Extra queries for an area, in the forms the providers actually index.

    Step 11. Nominatim's free-text search does not understand a comma qualifier
    and does not match a long phrase: measured on the same service, the query
    "Karaikudi Anna Nagar" returned ZERO rows, as did "Anna Nagar, Karaikudi" and
    "Karaikudi, Anna Nagar". The three-word form "Karaikudi Anna Nagar Main Road"
    returned one - a locality in Madurai, not in Karaikudi.

    So the area is searched on its own, with the town added only in the one form
    that measurably works: the town and the area joined by a space, which is how
    a person writes it. Each of these is a real query sent to a real index, so
    the pool only ever grows with places that genuinely exist - which is the
    whole point, because the brief forbids inventing a locality that the provider
    does not have.
    """
    words = [w for w in re.split(r"[^0-9a-zA-Z]+", str(text or "")) if w]
    if len(words) < 2:
        return []
    # Where the TOWN ends and the AREA begins.
    #
    # The locality word is a SUFFIX, not a prefix: "Anna Nagar" is a proper name
    # with "Nagar" on the end, and "Kolar Colony" is "Kolar" + "Colony". Cutting
    # at the first locality word and keeping only what follows therefore threw
    # the name away and searched for a place literally called "Nagar" - which is
    # a real village, so the search "succeeded" and answered with it. That is how
    # "Karaikudi Anna Nagar" came to return a village in Rajasthan named Nagar.
    #
    # So the split is made at the LAST locality word, and the area is everything
    # from the word before it. "Karaikudi Anna Nagar" splits into town
    # "Karaikudi" and area "Anna Nagar"; "Karaikudi Anna Nagar Main Road" into
    # area "Anna Nagar Main Road".
    last = max(
        (i for i, w in enumerate(words) if w.lower() in _LOCALITY_HEAD_WORDS),
        default=None,
    )
    if last is None or last < 1:
        return []
    area = " ".join(words[last - 1:])
    town = town or " ".join(words[: last - 1])
    forms = [area]
    if town:
        forms.append(f"{town} {area}")
    seen: set[str] = set()
    return [f for f in forms if not (f in seen or seen.add(f))]


def _name_similarity(query: str, candidate: dict) -> float:
    """How well a hit's name matches what was typed, from 0 to 1.

    This is the RANKING function, not a filter: a real geocoder hit is a real
    place regardless of how it scored, and a place the user may well have meant
    is never hidden for scoring badly. But among the hits a fuzzy search brought
    back, the one that genuinely reads like the typed text belongs at the top,
    and a hit that shares nothing with the text belongs at the bottom.

    Scored, strongest first. Every rule measures the WHOLE query against the
    WHOLE name, and every one of them is bounded by how much of the name the
    typed text actually covers - a rule that ignores that is what let "hennai"
    rank a village called "Hen" above Chennai:

      * the folded name equals the folded query          -> 1.0
      * the name starts with the query, or the query
        starts with the name                             -> 0.95, scaled by overlap
      * the name contains the query, or the query
        contains the name                                -> 0.85, scaled by overlap
      * any single query WORD matches a word of the name
        (this is the "Karaikudi" for "kudi" case)       -> 0.9, scaled by overlap
      * the whole strings are close enough to be a
        misspelling (edit distance)                     -> 0.7 down to 0.3

    "Overlap" is the LENGTH ratio between the two strings, never just a length
    check. A three-letter name that is a prefix of the query is a match of a
    different KIND to a six-letter name one edit away, and the second must win -
    "Hen" is a prefix of "hennai" but "Chennai" is that same text typed with two
    letters swapped.
    """
    q = _fold(query)
    name = _fold(candidate.get("name"))
    if not q or not name:
        return 0.0

    def covered(base: float) -> float:
        """Scale a match down by how much of the longer string it accounts for."""
        return base * min(len(q), len(name)) / max(len(q), len(name))

    if q == name:
        return 1.0
    if name.startswith(q):
        # The name BEGINS with what was typed. Trailing words are only extra
        # detail on the same place - "Chennai Corporation" is as good an answer
        # to "chennai" as "Chennai" is, so this is NOT scaled down by the extra
        # length. Scaling it is what let "Chennai Corporation" fall below an
        # unrelated village called "Hen".
        return 0.95
    if q.startswith(name):
        # The other way round: the typed text continues past the name ("henn" for
        # a place called "Hen"). A shorter name covering less of the query is a
        # weaker match, so this one IS scaled by the overlap.
        return covered(0.95)
    if q in name:
        # The name CONTAINS the typed text somewhere - the "Karaikudi" for "kudi"
        # case. Scaled by overlap, because a fragment matching by coincidence
        # halfway along a long name is a weaker answer than one matching a name
        # that is mostly the typed text.
        return covered(0.85)
    if name in q:
        # The typed text contains the whole name, as in a qualified query
        # ("Athur, Madurai" -> "Athur").
        return covered(0.85)

    # Word-level matching, so a fragment typed on its own finds the place that
    # contains it and a multi-word query matches on its strongest word. This
    # scores above the plain substring test above because a word that is exactly
    # a word of the name is a stronger signal than the characters happening to
    # appear somewhere in it: "kudi" is a word of "Karaikudi", whereas "ara"
    # merely happens to be a substring.
    q_words = [w for w in re.split(r"[^0-9a-z]+", q) if w]
    n_words = [w for w in re.split(r"[^0-9a-z]+", name) if w]
    for qw in q_words:
        for nw in n_words:
            if qw == nw:
                # Scaled against the WHOLE name, not just this word: "Kudi" is the
                # whole name and scores 1.0, while it scores lower against
                # "Kudi Hills Resort", which is a weaker answer to the same query.
                return covered(0.9)
            shorter, longer = (qw, nw) if len(qw) <= len(nw) else (nw, qw)
            # A real prefix only, never a one- or two-letter coincidence.
            if len(shorter) >= 3 and longer.startswith(shorter):
                return covered(0.9) * len(shorter) / len(longer)

    # A near-miss spelling. The edit distance is measured against the closest
    # query word, so "hennai" is compared with "chennai" and not with the whole
    # label, and the threshold tightens as the word gets longer - a two-letter
    # difference in a long word is a different place, one in a short word is a
    # typo.
    best = 0.0
    for qw in q_words:
        for nw in n_words:
            if not qw or not nw:
                continue
            distance = _levenshtein(qw, nw)
            allowed = 1 if max(len(qw), len(nw)) <= 5 else 2
            if distance <= allowed:
                score = 0.7 - 0.08 * distance
                # A near-miss only outranks a real substring when it accounts for
                # most of the name, so "Chennai" is preferred over some unrelated
                # place that merely contains the letters.
                score *= min(len(qw), len(nw)) / max(len(qw), len(nw))
                best = max(best, score)
            # A transposition is worth less than a real prefix. "mara" and "amra"
            # are one edit apart but are two DIFFERENT places, and scoring them
            # near-parity let a village called "Amra" outrank a real "Mara" for
            # the query "mara". The two leading scores are reserved for matches
            # that are actually about the same name, so this stays below them.
            if distance > 0:
                ratio = SequenceMatcher(None, qw, nw).ratio()
                if ratio >= 0.7:
                    best = max(best, 0.35 * ratio)
    return max(best, 0.0)


# --- Search ---------------------------------------------------------------


def _candidate_from_geocode(row: dict) -> dict | None:
    """Shape one Open-Meteo geocoding row into a place the UI can render.

    The fields shown on the selected-location card are the ones returned here:
    the place name, its city/town, district, state, country and pincode (when the
    service knows it), plus the coordinates. A row without a name or a
    coordinate is unusable and returns None, so a malformed result can never
    become a "selected" place.
    """
    name = _clean(row.get("name"))
    lat, lon = row.get("latitude"), row.get("longitude")
    if not name or lat is None or lon is None:
        return None

    # Open-Meteo names its administrative levels admin1 (state) and admin2
    # (district). `feature_code` distinguishes a landmark/POI from a plain town,
    # which is what lets the UI label a hit as a landmark rather than a place.
    # PPLX (a named section of a populated place) and the building/POI codes are
    # landmarks; PPL/PPLA*/PPLC are towns and cities and are NOT landmarks.
    feature_code = _clean(row.get("feature_code")) or ""
    landmark_codes = ("PPLX", "PPLL", "PPLQ", "BLDG", "HIST", "TOUR", "LEIS", "AMUS")
    is_landmark = feature_code.startswith("PPLX") or feature_code in landmark_codes

    state = _clean(row.get("admin1"))
    district = _clean(row.get("admin2"))
    country = _clean(row.get("country"))

    # Build the dropdown label from whatever is known, without repeating a field.
    parts = [name]
    for value in (district, state, country):
        if value and value not in parts:
            parts.append(value)

    return {
        "name": name,
        "city": name,
        "label": ", ".join(parts),
        # STEP 10: the same branch-distinguishing label the Nominatim path builds,
        # so EVERY row in the dropdown has one. A town row and a POI row sit in
        # the same list and are rendered by the same code, and reading
        # `branch_label` unconditionally is what the frontend now does - a row
        # without the key would silently fall back to the bare name and lose its
        # address.
        "branch_label": ", ".join(parts),
        "country": country,
        "country_code": _clean(row.get("country_code")),
        "state": state,
        "district": district,
        "pincode": _clean(row.get("postal_code") or row.get("postcode")),
        "lat": float(lat),
        "lon": float(lon),
        "feature_code": feature_code or None,
        "kind": "landmark" if is_landmark else "place",
    }


def _local_bias_terms(text: str, state: str | None, district: str | None) -> list[str]:
    """The extra queries that ask the providers for hits in the DEVICE'S state.

    WHY THIS IS NEEDED AT ALL. Ranking alone cannot create a local suggestion: a
    one-letter query such as "k" is answered by both geocoders with whatever
    happens to sit highest in THEIR global index, and a state-local town usually
    is not in it at all. So "k" for a device in Tamil Nadu comes back with
    Kannur (Kerala), Kandivali (Maharashtra) and Kansas, and no amount of sorting
    a list that does not contain the local answer can put it first.

    The fix is to ask the providers a question that INCLUDES the state. Nominatim
    understands a qualified free-text query and answers "k, Tamil Nadu" with real
    rows from that state, so those rows are then in the pool for the local
    preference below to rank first. Nothing is fabricated: every row still comes
    from a live geocoder response, and the state used is the one the browser's own
    position was reverse-geocoded into - never a hardcoded or assumed one.

    Both a comma-qualified and a space-separated form are offered, because
    providers disagree about which they index. They are only added when there is
    text to qualify: a pincode is not "630001, Tamil Nadu".
    """
    base = _clean(text)
    if not base or _looks_numeric(base):
        return []
    terms: list[str] = []
    places = [district, state] if _clean(district) else [state]
    for place in places:
        place = _clean(place)
        if not place or _fold(place) == _fold(base):
            continue
        terms.append(f"{base}, {place}")
        terms.append(f"{base} {place}")
    seen: set[str] = set()
    return [t for t in terms if not (t in seen or seen.add(t))]


def search(
    query: str,
    limit: int = 6,
    autocomplete: bool = False,
    device_state: str | None = None,
    device_district: str | None = None,
) -> list[dict]:
    """Find a place by name / pincode / famous landmark / business / locality.

    One lookup serves every kind of thing a user types into a location box,
    because Open-Meteo resolves a town name, a postal code and a landmark through
    the same endpoint:

      * a place name        "Karaikudi", "Chennai", "Madurai", "Coimbatore"
      * a pincode           "630001"
      * a landmark          "Marina Beach", "Meenakshi Amman Temple"

    and Nominatim - the fallback, and the main path for the rest - resolves the
    ones a town index cannot know about:

      * a college / school  "Karaikudi college", "Thiagarajar college"
      * a shop / a branch   "Indian Bank Karaikudi" (each branch is its own hit)
      * an area / locality   "Karaikudi Anna Nagar", any nagar, colony or ward

    Returns candidates shaped for the search dropdown and the selected-location
    card: ``name``, ``city``, ``district``, ``state``, ``country``, ``pincode``,
    ``lat``, ``lon``, plus ``kind`` / ``poi_type`` / ``poi_label`` so the UI can
    say what the hit is, and ``area`` so a locality is distinguishable from the
    town that contains it.

    `autocomplete=True` is the interactive path. It asks FEWER provider variants
    (see `_search_terms_bounded`) so the first suggestion is quick; the result is
    still made of real geocoder hits, only a narrower set of spellings was tried.
    The default `autocomplete=False` is the "resolve this one place" path, which
    keeps the full set of variants because being right matters more than being
    fast when the answer decides a water source.

    STEP 9 - THE DEVICE'S OWN STATE IS A RANKING PREFERENCE, NEVER A FILTER.
    `device_state` / `device_district` are the administrative levels the BROWSER'S
    position was reverse-geocoded into, sent by the client and used for two
    things only:

      * `_local_bias_terms` asks the providers for hits inside that state, so
        local places are in the pool at all - a one-letter query is otherwise
        answered from a global index that may know nothing about them.
      * `_local_preference` orders the pool, so a local place that genuinely
        matches the text leads.

    Both are strictly about ORDER. Nothing is filtered, no non-local place is
    removed, and both are None when the browser refuses geolocation - the
    search then behaves exactly as it always has, which is what a user who
    declined the permission must still get.
    """
    text = _clean(query)
    if not text:
        raise ValidationError("Type a place name, pincode or landmark to search.")

    # A pincode is a single lookup: the postal index already answers it, and
    # asking for spelling variants of "630001" cannot reach anything new.
    numeric = _looks_numeric(text)

    qualifiers = _split_qualified(text)
    # "Karaikudi railway station" is searched as "Karaikudi" - the kind word is
    # kept for RANKING (see `_requested_kind`) but removed from the query, so the
    # providers are asked about the place rather than about the whole phrase.
    search_text = _strip_kind_words(qualifiers["place"] or text) or (qualifiers["place"] or text)
    terms = _search_terms_bounded(search_text, full=numeric or not autocomplete)
    if numeric:
        terms = [search_text]

    # STEP 11: A QUERY THAT NAMES A SMALL AREA IS ALSO ASKED AS AN AREA.
    #
    # The backoff above truncates a phrase from the RIGHT, so "Karaikudi Anna
    # Nagar" is reduced to "Karaikudi" - it keeps the TOWN and discards the thing
    # the user actually asked for. Every row returned was the town, so the
    # dropdown showed "Karaikudi" for a search that named a nagar, and the nagar
    # was never identified at all.
    #
    # The area is therefore searched in its own right. The town is only ever a
    # qualifier, and the forms below are the ones measured to reach a real
    # locality; see `_locality_terms`. The town query is still asked as well, so
    # a search that names both still offers the town - it just no longer wins by
    # default.
    locality_terms = _locality_terms(text, None) if _locality_query(text) else []

    # STEP 10: THE FULL TEXT IS ITS OWN SEARCH TERM.
    #
    # Stripping the kind word is right for the TOWN index, which has no entry for
    # a bank branch, and wrong for the feature index, which has little else.
    # Nominatim asked for "Indian" returns a hamlet in Virginia; asked for
    # "Indian Bank" it returns the banks. So the phrase as the user typed it -
    # name AND kind, e.g. "Karaikudi college", "ABC Store", "Meenakshi Temple" -
    # is asked as its own term, and those hits are MERGED in.
    #
    # WITHOUT THIS, A KIND-WORD QUERY NEVER REACHED THE FEATURE INDEX AT ALL. The
    # terms were the stripped name and its fragments, and every one of them is a
    # town query, so "Karaikudi college" was answered with the town Karaikudi and
    # a village called "Udi" in Nigeria.
    #
    # Only added when there is a kind word to add: for "Karaikudi" the text as
    # typed is already a term, and asking it twice would only spend a request.
    #
    # THE SHORT FORM OF THE PHRASE IS ASKED AS WELL, because the long one is not
    # always understood. Measured: Nominatim returns 0 rows for "Karaikudi railway
    # station" and 15 for "Karaikudi college" - a three-word phrase simply does not
    # match its index, so the railway station the user asked for was never
    # returned. "Karaikudi railway station" reduced to its distinctive head
    # ("Karaikudi railway") does match, and that is what brings the station back.
    # Every form is a real query against a real index, so the pool only grows with
    # rows that genuinely exist.
    phrase_terms = []
    if _requested_kind(text):
        phrase_terms = [text] if text not in terms else []
        for short in _kind_phrase_backoffs(text, qualifiers.get("place") or text):
            if short not in terms and short not in phrase_terms:
                phrase_terms.append(short)

    # STEP 9: the DEVICE's own state / district, when the browser resolved the
    # position. Extra qualified queries go to BOTH providers below so local hits
    # exist to be ranked. They are MERGED with the ordinary terms rather than
    # replacing them, so a search for a place in another state or another country
    # still works exactly as before - the state only decides what leads the list.
    local_terms = (
        []
        if not (autocomplete and (device_state or device_district))
        else _local_bias_terms(search_text, device_state, device_district)
    )
    # A query too short to be naming anything specific must be answered with
    # PLACES, so only settlements are admitted from the state-qualified query
    # below. The measurement behind this: asked for "k, Sivagangai", Nominatim's
    # top row was the greengrocer "K. Ganesh Vegetables" and asked for "ka,
    # Tamil Nadu" it was a street called "Kanavaipatti-V.S.K.Valasai Main Road".
    # Both are real and in the right state, and neither is somewhere a user
    # would choose a water source - and a one-letter text cannot be the name of
    # a shop. They are dropped from the LOCAL query only; the unqualified
    # queries are untouched, so an explicit "K. Ganesh Vegetables" search still
    # finds it.
    short_text = len(_fold(search_text)) < 3

    # The two groups of terms are fetched SEPARATELY, and that separation is
    # load-bearing. The short-query settlement rule below has to apply to the
    # state-qualified queries ONLY - applying it to the whole result list threw
    # away the ordinary unqualified hits too and left the dropdown EMPTY for
    # "k", because the global geocoders answer a one-letter query with
    # administrative areas and road names that are not settlements either. The
    # unqualified searches are left exactly as they always were.
    ordinary = _dedupe_candidates(
        _geocode_candidates_many(terms, min(max(limit * 2, 1), 10))
    )
    qualified = (
        [
            c
            for c in _geocode_candidates_many(local_terms, min(max(limit * 2, 1), 10))
            if not (short_text and not _is_settlement_row(c))
        ]
        if local_terms
        else []
    )
    # STEP 11: the area queries reach the TOWN index too, because a nagar is
    # often indexed there rather than only on the feature map. They are added
    # after the local ones and before nothing else, and they are not filtered by
    # the short-text rule - that rule exists to keep a one-letter query from
    # being answered with a shop, and an area name is already specific.
    area_rows = (
        _geocode_candidates_many(locality_terms, min(max(limit * 2, 1), 10))
        if locality_terms
        else []
    )
    candidates = _dedupe_candidates(ordinary + qualified + area_rows)

    # STEP 9, PART 2 - A WIDER TOWN POOL FOR A VERY SHORT PREFIX.
    #
    # Asking the providers for "k, Tamil Nadu" is not enough on its own, and the
    # reason is worth recording because it was measured rather than guessed:
    #
    #   * Open-Meteo indexes TOWNS. Asked for a bare "k" or "ka" it returns
    #     nothing at all (0 and 17 rows, neither containing a Tamil Nadu town),
    #     because a one- or two-letter prefix matches no town name in its index.
    #   * Nominatim indexes EVERY map feature. Asked for "k, Tamil Nadu" it
    #     answers with a taxiway and a service road called "K" - local, but not
    #     places anyone means.
    #
    # So a short query needs a WIDER window on the town geocoder rather than a
    # narrower one. The measurement that settles it: asked for "kar" with the
    # default count Open-Meteo returned no Tamil Nadu town, and asked for the
    # same text with a count of 100 it returned Karur and Karaikudi. The rows
    # were always in the index; the default page was too small to hold them.
    #
    # This is purely a bigger POOL. The rows are still real geocoder hits and
    # still go through the same ranking below, which is what decides what the
    # user sees - a county, a stream or a road cannot be promoted over a town
    # just by being local.
    if local_terms and len(_fold(search_text)) < _LOCAL_TOWN_POOL_MIN_LENGTH:
        candidates = _dedupe_candidates(
            list(candidates)
            + [
                c
                for c in _geocode_candidates_many([search_text], _LOCAL_TOWN_POOL_COUNT)
                if _is_settlement_row(c)
            ]
        )

    # A "Village, District" query ("Athur, Madurai", "Kottur, Thiruvidaimarudur")
    # is the natural way to name a place, but nominatim's free-text search does
    # NOT understand the comma qualifier: it returns ZERO rows for
    # "Athur, Madurai" while the same village name alone matches five. So the
    # qualified form is decomposed first -- the place name is searched on its own,
    # and the district/state words are then used to RANK and FILTER the hits.
    # Nothing is invented: only real geocoder hits are returned, and a qualifier
    # that matches nothing simply does not narrow the list.

    # Open-Meteo only indexes populated places, so a temple, theatre, college,
    # shop or street never matches there. When it comes back empty (or when the
    # query looks like a landmark search), fall back to Nominatim's forward
    # search, which indexes every map feature. Nothing is fabricated: only
    # confirmed Nominatim hits are returned.
    #
    # The fallback searches the PLACE NAME ALONE, never the qualified form:
    # nominatim returns zero rows for "Athur, Madurai" while the bare name
    # matches five, so qualifying it here would be the very failure this block
    # exists to prevent.
    # STEP 10: A QUERY THAT NAMES A KIND ALWAYS ASKS THE FEATURE INDEX.
    #
    # The condition used to be "the town geocoder found nothing, or what it found
    # looks like a POI". For "Karaikudi college" the town geocoder returns the
    # town Karaikudi - not a POI, a perfectly good hit - so the block was skipped
    # and Nominatim, the only index that knows a college by name, was never
    # asked. The fifteen real colleges in that town existed in the response the
    # code had already made and thrown away. The user got a town.
    #
    # So a query that names a kind of place ALWAYS goes to the feature index,
    # whatever the town index returned. It is one extra lookup, and it is what
    # makes "Karaikudi college" answer with colleges.
    # STEP 11 makes the same guarantee for a SMALL AREA: a query naming a nagar
    # or a colony ALWAYS goes to the feature index, because that is the only
    # index that knows an area. Without it the town index answers "Karaikudi" -
    # a perfectly good hit for the town - and the area is never identified.
    if (
        phrase_terms
        or locality_terms
        or not candidates
        or any(_looks_like_poi(text, c) for c in candidates)
    ):
        # A wider net than the caller asked for: a bare village or business name
        # is common enough that the first few hits are often the wrong town or
        # the wrong branch, and the qualifier filter below needs candidates to
        # choose between. Several branches of one chain are separate rows, and
        # this is what lets all of them reach the list.
        #
        # Nominatim is asked the same way the town geocoder was: every variant of
        # the place name, not just the text as typed, because Nominatim is the
        # only index that knows a temple, a college or a locality by name.
        #
        # The variants are asked CONCURRENTLY rather than one after another, so
        # the search costs roughly the slowest single lookup instead of the sum
        # of all of them.
        #
        # Every term is asked, not just the text as typed, because Nominatim's
        # free-text search is FUZZY and for a phrase it often fills its own limit
        # with near-misses: asked for "Anna Nagar" it returned Nnak, Nnabi, Nnamg
        # and Nnage - real places in Nigeria and Pakistan sharing a couple of
        # letters - and the genuine Anna Nagar in Tamil Nadu never made the ten
        # rows the API allows back. The "Anna" lookup is what surfaces those rows,
        # and the ranking then puts them first, because a name covering EVERY
        # word typed scores above one sharing a prefix with the first word.
        #
        # The alternative - asking only the text as typed, to save the speculative
        # lookups - is what left the dropdown showing the village of Anna in
        # Spain for a search the user made in Tamil Nadu.
        nominatim_hits = _dedupe_candidates(
            hit
            for hit in _search_nominatim_many(
                terms + phrase_terms + locality_terms, max(limit, 10)
            )
        ) + (
            # The settlement rule again, on the state-qualified terms only, for
            # the same reason as above. The measurement: for "k, Sivagangai"
            # Nominatim's single top row was the greengrocer "K. Ganesh
            # Vegetables", and for "ka, Tamil Nadu" a bank and a highway bridge.
            [
                hit
                for hit in _search_nominatim_many(local_terms, max(limit, 10))
                if not (short_text and not _is_settlement_row(hit))
            ]
            if local_terms
            else []
        )
        if nominatim_hits:
            # MERGE, do not replace.
            #
            # This used to DISCARD the town hits whenever Nominatim answered at
            # all, which is what made a partial word show the wrong places: for
            # the two-letter fragment "ka" Nominatim returned a match for
            # "Karnataka" and a couple of similar junk entries, and they replaced
            # the perfectly good set Open-Meteo had just returned for the same
            # text. Keeping both and letting the ranking below sort them means
            # the useful hits survive, while the POI hits - which is all
            # Nominatim is here for - are added rather than substituted.
            candidates = _dedupe_candidates(list(candidates) + list(nominatim_hits))

    # STEP 24: THE KIND AS A PHRASE THIS STEP CAN FILTER ON.
    #
    # Read here, before the structured lookup below, because that lookup needs to
    # know which kind was asked for. `_requested_kind` further down is NOT
    # enough: it is a RANKING bucket, and it files both a theatre and a hotel
    # under the single value "landmark", because for ranking they only need to
    # not be a place. Step 24 needs the exact kind, because the exact kind is
    # what decides which OSM category to ask the geocoder for.
    wanted_kind_phrase = _structural_kind_phrase(text)

    # STEP 24: A REQUEST FOR A KIND OF PLACE IS ALSO ASKED AS A STRUCTURE.
    #
    # Everything above asks the geocoders the question as a SENTENCE. For a
    # business, an institution or a transport hub the sentence form is the wrong
    # instrument, and the measurement is unambiguous - asked as text,
    # "Karaikudi theatre" returned the TOWN and villages in another district,
    # while the map holds Sathyan Theatre and Sivam theatre in that town with
    # full addresses. So the same question is asked structurally as well, inside
    # a box around the town, filtered to the kind's OSM category, and the real
    # branches are MERGED in.
    #
    # This only ever ADDS rows. Every path above is untouched, so a search that
    # works today cannot regress, and a kind the map holds nothing for simply
    # contributes nothing and leaves the existing answer standing.
    structural_rows: list[dict] = []
    if wanted_kind_phrase:
        try:
            structural_rows = _structural_candidates(
                qualifiers["place"] or text, wanted_kind_phrase, limit
            )
        except Exception:  # noqa: BLE001 - never fail a search over an extra lookup
            logger.exception("STEP 24 structured branch lookup failed for %r", text)
            structural_rows = []
    if structural_rows:
        candidates = _dedupe_candidates(list(candidates) + list(structural_rows))

    # THE GOOGLE MAPS INDEX - the exact-POI path the brief asks for.
    #
    # Type any Tamil Nadu business, school, college, IT office or shop and the
    # place Google Maps shows must come back. The free indexes above read
    # OpenStreetMap, and OSM holds only a fraction of Indian POIs, which is why
    # "Gradtwin" used to answer with "Win" in Vanuatu. When a Maps Platform key
    # is configured, the text is asked here AS TYPED and the exact rows Google
    # holds are merged into the same pool the ranking sorts. Without a key this
    # block is a no-op and the search is byte-for-byte what it was before.
    #
    # It sits AFTER the structured lookup and BEFORE the qualifier filter, so a
    # Google row is treated exactly like every other candidate: a district or
    # state qualifier still narrows it, and the name-match ordering still puts
    # the best row first.
    if _google_places_key():
        try:
            google_rows = _search_google_places_many(
                [search_text, text], max(limit, 8)
            )
        except Exception:  # noqa: BLE001 - never fail a search over an extra lookup
            logger.exception("Google Places lookup failed for %r", text)
            google_rows = []
        if google_rows:
            candidates = _dedupe_candidates(list(candidates) + list(google_rows))

    # APPLY THE QUALIFIER. The hits are already the real places behind the name;
    # the district/state words only decide which of them the user meant. A hit
    # whose district or state matches a qualifier is kept and promoted; when a
    # qualifier matches nothing, no filtering is applied, so a place spelled
    # slightly differently by the geocoder is still reachable.
    candidates = _apply_qualifiers(candidates, qualifiers)

    # ORDER BY HOW WELL THE NAME MATCHES. Several search terms were asked, so
    # the list now holds hits from every one of them: the real match for "kudi"
    # (Karaikudi) sits next to unrelated villages actually named "Kudi". The
    # similarity score sorts them so the place the user meant is the first
    # option, and the rest remain reachable below it. This REORDERS, it never
    # removes: a genuine hit that scores poorly is still shown rather than
    # hidden behind a filter the user cannot see.
    #
    # A single short word ("Salem", "Paris", "Karaikudi") matches towns in
    # several countries, and the geocoder's first hit is not always the one the
    # user means. When India is among the hits, its matches go first: this app
    # serves Indian water-quality data, so "Salem" should resolve to Salem,
    # Tamil Nadu - never to Salem, Massachusetts. Nothing is reordered when
    # there are no Indian hits, and multi-word / POI queries are left alone.
    #
    # The country preference is a SECOND sort key rather than a separate pass
    # over the list, because a pass would concatenate the Indian hits in front of
    # the rest and throw away the name-match ordering computed here.
    #
    # The preference applies to a single-word query, which is the one that
    # genuinely matches towns in several countries ("Salem"). A query that names
    # something more specific is NOT promoted by country: "Karaikudi railway
    # station" has to reach the station, and forcing Indian hits to the top is
    # what put an unrelated Indian village above the right answer when the search
    # spanned several words. For those, the type the user asked for decides.
    prefer_india = len(text.split()) == 1

    # The kind of thing the user named, when they named one. "railway station",
    # "temple", "college" are ordinary words, and a hit that IS one of them is
    # what was asked for - a town whose name happens to be a prefix of the query
    # is not, even though it scored well on spelling.
    wanted_kind = _requested_kind(text)
    # STEP 11: IS THIS A SEARCH FOR A SMALL AREA? Read once, outside the nested
    # `order`, for the same reason `folded` is.
    wants_area = _locality_query(text)
    seen_names: dict[str, int] = {}
    # The typed text, folded for comparison, and its LENGTH.
    #
    # The length decides whether a fuzzy similarity score means anything at all:
    # below three characters there are far too few letters for one to tell two
    # place names apart, and letting it decide is what put "Linea A" above every
    # real place for the query "a". Computed out here rather than inside `order`,
    # because a name assigned inside a nested function is a LOCAL of that
    # function and the earlier use would fail.
    folded = _fold(text)
    # Whether ANY candidate is actually of the requested kind. Computed once, so
    # the ordering can tell "there is a real hospital here" from "nothing matched,
    # so the category is the only thing going".
    any_kind_match = any((c.get("poi_type") or "") == wanted_kind for c in candidates) if wanted_kind else False
    # STEP 24: the SPECIFICATION of the exact kind this query named, or None.
    #
    # `_requested_kind` above files both a theatre and a hotel under the single
    # bucket "landmark", because for ranking they only need to not be a place.
    # For Step 24's structured lookup they are different OSM categories and have
    # to be told apart, so this is the table that says which `category`/`type`
    # pairs count as the kind the user actually named.
    kind_phrase_spec = _KIND_STRUCTURED_QUERIES.get(wanted_kind_phrase or "")

    # AMBIGUITY DETECTION for the relevance tiers. Count the places whose
    # ENTIRE name is the typed text, and whether any of them sits in the
    # device's own area. See _relevance_tier for how the two facts decide
    # opposite cases ("kara" demotes the foreign exacts; "bengaluru" does
    # not, because a local exact match exists to win tier 0 on its own).
    exact_name_count = 0
    local_exact_exists = False
    for c in candidates:
        is_exact = (
            _fold(c.get("name")) == folded
            or _fold(c.get("area")) == folded
            or _fold(c.get("label")) == folded
        )
        if is_exact:
            exact_name_count += 1
        if is_exact and (
            (device_state and _matches_area(c.get("state"), device_state))
            or (device_district and _matches_area(
                c.get("district") or c.get("county"), device_district
            ))
        ):
            local_exact_exists = True
    _relevance_tier._ambiguous_exact = exact_name_count > 1
    _relevance_tier._local_exact_exists = local_exact_exists

    def order(candidate: dict) -> tuple:
        kind_match = 1 if wanted_kind and (candidate.get("poi_type") or "") == wanted_kind else 0
        # STEP 24: A REAL BRANCH OF THE EXACT KIND REQUESTED LEADS THE LIST.
        #
        # The key above cannot do this, and the reason is the bucket it reads.
        # A theatre and a hotel are both filed as `landmark` by `_poi_kind`, so
        # asking for a theatre and asking for a hotel produce the same ranking
        # signal - and worse, the town of Karaikudi is not a `landmark` at all,
        # so it scores 0 while a cinema scores 1 on a bucket that cannot tell the
        # two questions apart. The structured lookup already found the real rows
        # and put them in this list; without this key the town still led, and the
        # whole of Step 24 would be invisible to the user.
        #
        # It is a strict refinement of the key below: it can only promote a row
        # the provider has tagged as the kind that was asked for, and it is 0 for
        # every row when the query names no kind - so an ordinary place search
        # keeps exactly the ordering it always had.
        exact_kind = 0
        if kind_phrase_spec:
            category = (_clean(candidate.get("feature_category")) or "").lower()
            row_type = (_clean(candidate.get("feature_type")) or "").lower()
            if category in kind_phrase_spec["categories"]:
                accepted = kind_phrase_spec["categories"][category]
                if not accepted or row_type in accepted:
                    exact_kind = 1

        # A POI CATEGORY must not outrank a real name match.
        #
        # "Karaikudi hospital" and "Karaikudi theatre" are looking for one thing
        # inside a named town, and they were answered with the town itself - the
        # query mentions a hospital, so ANY row of that category scored a perfect
        # kind match and won, even one named nothing like what was typed. So a
        # category match only counts when it is corroborated: the name has to
        # match too, or nothing in the result matches and the category is the
        # only evidence there is.
        typed_score = _name_similarity(search_text, candidate) if len(folded) >= 3 else 0.0
        # STEP 10: THE CORROBORATION IS "IN THE PLACE THAT WAS ASKED FOR", NOT
        # "IN THE NAME". This rule decides whether a college search returns
        # colleges, and the old reading of it returned towns. A college in
        # Karaikudi is usually NOT called anything like "Karaikudi" - they are
        # "Alagappa Govt Arts College", "Ramasamy Tamil College" - so requiring
        # the row's NAME to match the query left every genuine college
        # uncorroborated, and the town of Karaikudi, whose name does match, as the
        # only answer.
        #
        # What corroborates a row of the right kind is the ADDRESS. The provider
        # returned it for the query "Karaikudi college", so it is a college it
        # placed in Karaikudi; checking the row's own city/district carries the
        # place word is that confirmation, and it is the evidence actually
        # available. The original rule is kept as the first alternative, so a row
        # whose name genuinely matches is still trusted.
        corroborated = typed_score > 0 or _row_is_in_place(candidate, search_text)
        kind_agrees = 1 if kind_match and (corroborated or not any_kind_match) else 0
        indian = 1 if (prefer_india and (candidate.get("country_code") or "") == "IN") else 0
        # HOW DIRECTLY the user's words appear in the name, graded rather than
        # yes/no.
        #
        # This is the rule that answers "show me places beginning with or
        # matching what I typed", and it has to outrank every fuzzy score. A
        # similarity score is a statement about spelling, and a two-letter query
        # is far too little text for one to mean anything: "ch" returned
        # Switzerland, whose Nominatim row is the alias list
        # "Schweiz/Suisse/Svizzera/Svizra"; "a" returned the Buenos Aires metro
        # route "Linea A". Both are real features and both stay in the list -
        # nothing is filtered out - but neither may LEAD it.
        #
        # GRADED, because a bare substring test does not separate them either:
        # "schweiz" contains "ch" and "linea a" contains "a", so every
        # short-query hit tests true. What separates a real match from an
        # accident is HOW the text sits in the name - a name that BEGINS with
        # what was typed is what someone part-way through typing means, and a
        # two-letter fragment appearing in the middle of a word is coincidence.
        # A short text is therefore only credited for a prefix; a longer one is
        # credited for appearing anywhere in the name, which is what lets
        # "nagar" find "Anna Nagar".
        literal = _match_strength(
            # STEP 10: THE KIND WORD IS NOT PART OF THE NAME BEING MATCHED.
            #
            # `literal` measured the whole typed text against the row's name, so
            # for "Karaikudi college" it compared "karaikudicollege" against
            # "Alagappa Govt Arts College" - which contains neither the town's
            # name nor the whole phrase - and scored every real college in the
            # town at zero, while the town itself scored a perfect 3.0 for
            # containing "Karaikudi". Six genuine colleges were in the pool and
            # none of them could be shown.
            #
            # The name the user is actually looking for is the stripped one
            # (`search_text`, already computed above for the provider query), so
            # that is what the text is compared against. The kind is already
            # handled separately and more precisely by `kind_match`, which reads
            # the provider's own category instead of guessing from the word.
            search_text, candidate.get("name"), candidate.get("area"), candidate.get("label")
        )
        # COUNTRY SCALE, pushed down. "Schweiz/Suisse/Svizzera/Svizra" IS
        # Switzerland - its `country` field holds its own name, because for a
        # country row the country is the feature. Its name starts with "ch" only
        # by accident of the first word of the alias list, and a country is a far
        # worse autocomplete answer than a town or a POI when someone is part-way
        # through typing a place. It is still reachable: searching "India" is a
        # legitimate thing to do, and this only changes the ORDER.
        is_country = 0 if _looks_like_country(candidate) else 1

        # STEP 9: THE DEVICE'S OWN AREA.
        #
        # IT ONLY DECIDES TIES, and the rule is deliberately narrow. The local
        # preference is active only while the typed text is a PARTIAL name, which
        # is exactly the case the feature describes ("k" for a device in Tamil
        # Nadu). It is switched off once the user has typed a name IN FULL,
        # because proximity must never overrule an instruction:
        #
        #   a village named "Bengaluru" in the device's own district was beating
        #   the real Bengaluru, Karnataka, because the local key outranked every
        #   remaining relevance key and manufactured a tie it then won. Naming a
        #   place is an instruction, not a hint, and it has to be obeyed wherever
        #   that place is.
        #
        # THE TEST IS WHETHER THE TYPED TEXT COVERS THE WHOLE NAME, and it is
        # written out rather than borrowed from `literal`. `literal` cannot be
        # used: it returns 3.0 both for an exact name ("bengaluru" -> Bengaluru)
        # and for a PREFIX ("k" -> Karaikudi), because "the name begins with what
        # was typed" is precisely what a part-way-typed name looks like. Gating on
        # it therefore switched the preference off for the one query it exists to
        # improve, and the local ordering silently did nothing.
        #
        # A country row is switched off too: a country is a worse autocomplete
        # answer than a town anyway, and "India" would otherwise be read as the
        # device's own state and outrank every real place.
        #
        # The key sits BELOW `literal`, so a local row never outranks a better
        # textual match, and ABOVE `is_country` / `indian`, because knowing the
        # state beats assuming the country. It filters NOTHING: a far-away place
        # stays fully reachable, below the local ones.
        # A COUNTRY, and a row that is not somewhere a person would look for a
        # place, are switched out too - see `_is_selectable_place` for why a
        # local taxiway must not outrank a local town.
        typed_the_whole_name = _fold(search_text) == _fold(candidate.get("name"))
        local = (
            (0, 0)
            if (
                typed_the_whole_name
                or not is_country
                or not _is_selectable_place(
                    candidate, want_settlement=len(_fold(search_text)) < 3
                )
                or not (device_state or device_district)
            )
            else _local_preference(candidate, device_state, device_district)
        )
        # A real, singularly-named place beats a multi-alias or a route/bus
        # entry when the text is too short to distinguish them.
        alias_penalty = 0 if _is_multi_alias(candidate.get("name")) else 1
        # DIVERSITY. A provider asked for a common name returns one row per
        # country that has a place with it - "Anna" came back fifteen times
        # (Spain, Russia, the USA, Estonia, Poland, Papua Niugini...) - and with
        # every other ranking key identical they filled the whole dropdown,
        # pushing the answer anyone actually wanted off the bottom. Once a name
        # has been placed, its later appearances sink, so the list shows
        # different places rather than the same name in twelve countries. They
        # are still reachable; this only decides the order.
        #
        # STEP 10 - THE REPEATS OF A *BRANCH* ARE NOT REPEATS.
        #
        # The rule above exists to stop one name filling the dropdown with
        # unrelated places. A chain's branches are the opposite case: they share
        # a name BECAUSE they are the same business, and listing them is the
        # entire point - "ABC Store" in Karaikudi, in Chennai and in Madurai are
        # three real places the user is choosing between. Sinking the second and
        # third one would merge them into a single ambiguous result and push the
        # user onto whichever branch happened to be ranked first, which is
        # exactly the "do not return a random branch" failure.
        #
        # So the penalty applies only when the repeats are DISTINCT PLACES rather
        # than branches of one name. A POI - a shop, a bank, a college, a
        # station - is a branch by nature: each row is its own location, and each
        # carries its own address. A settlement is the case the rule was written
        # for and keeps the penalty unchanged.
        name_key = _fold(candidate.get("name"))
        repeated = seen_names.get(name_key, 0)
        seen_names[name_key] = repeated + 1
        if _is_branch_row(candidate):
            # Branches are counted for nothing: the key is neutral, so a branch
            # is ordered purely on what it is and where it is.
            repeated = 0
        # Scored against EVERY term that was searched, best one wins.
        #
        # This is what makes a variant term useful. "hennai" is searched as
        # "hennai", "hen", "nai", "ehnnai" and "henai", and "Chennai" is
        # returned by the "chen"/"henai" lookups - but scored against "hennai"
        # alone it is only a near-miss (0.73), losing to a village whose own
        # name is a short prefix of the typo. Scored against the term that
        # actually found it, "chenai" or "henai", it is an exact match (1.0) and
        # correctly leads the list. Nothing is fabricated: every term was asked
        # of the geocoder and the hit came back from one of them.
        # A similarity score is only MEANINGFUL once there are enough letters to
        # compare. Below three characters it measures nothing, and letting it
        # decide is what put "Linea A" above every real place for the query "a".
        # `folded` - the typed text, so the rule is about what the USER typed - is
        # computed once outside this function and read from there.
        # Scored against the query AS TYPED, with the structural variants only
        # ever used to RESCUE a weak match - never to beat a good one.
        #
        # Taking the best score over every term was subtly wrong, because a
        # variant is a fragment: "Karaikudi Main Street" is also searched as
        # "udi" (the tail of "karaikudi"), and a place actually called "Udi" -
        # in Enugu State, Nigeria - scores a PERFECT 1.0 against that fragment,
        # beating the real Karaikudi whose full name matches the typed text at
        # 0.75. The fragment's exact match was winning because it was compared
        # against a shorter string, not because it was a better answer.
        #
        # So the typed text is scored on its own, and a variant's score only
        # applies when the typed text matched nothing useful. "hennai" still
        # works: Chennai scores 0.73 against the typo, which is below the rescue
        # threshold, so the "chenai"/"henai" lookups' exact match is allowed to
        # promote it - exactly the case the variants exist for.
        typed_score = _name_similarity(search_text, candidate) if len(folded) >= 3 else 0.0
        if typed_score >= 0.5:
            best = typed_score
        else:
            rescue = max(
                (_name_similarity(term, candidate) for term in terms if term != search_text),
                default=0.0,
            )
            best = max(typed_score, rescue * _VARIANT_RESCUE_DISCOUNT)
        # STEP 11: A REQUEST FOR AN AREA IS ANSWERED WITH AN AREA.
        #
        # "Karaikudi Anna Nagar" is a request for a nagar. The town geocoder
        # answers it with the town, and the town wins on every other key - its
        # name is a clean prefix of the query, so `literal` is a perfect 3.0
        # while a real "Anna Nagar" in that district, whose name is the WHOLE
        # thing asked for, scores lower because the town word is not in its own
        # name. The town therefore always won, and the user could never select
        # the nagar they had actually asked for.
        #
        # This key says which rows ARE the kind of thing that was requested. It
        # sits ABOVE `literal` for exactly that reason, and it is deliberately
        # narrow - a row must either be a locality (a suburb, a quarter, a
        # neighbourhood, a ward - which is what a nagar is mapped as) or carry
        # the area in its own address fields. A row qualifies on the provider's
        # own tagging, so this cannot promote a place the map does not have.
        #
        # The town is NOT removed - it stays in the list, still selectable, and
        # still the right answer if that is genuinely what the user wanted. This
        # only decides what leads.
        area_match = 0
        if wants_area:
            is_locality = _is_locality_row(candidate)
            covers_the_area = _row_is_in_place(candidate, _area_name_only(text))
            area_match = 1 if (is_locality or covers_the_area) else 0

        # STEP 11: A ROW THAT KNOWS ITS OWN ADDRESS IS MORE USEFUL THAN ONE THAT
        # DOES NOT.
        #
        # The two indexes answer differently for the same place. Asked for "Anna
        # Nagar", the TOWN index returns a row whose city is "Anna Nagar" and
        # whose district reads "Chennai district" - a roundabout self-reference
        # that tells a user nothing - while the FEATURE index returns the same
        # nagar with a real city (Chennai Corporation), a real district
        # (Madhavaram) and a postcode. Both are honest rows from a real geocoder;
        # the feature one simply says where the place IS.
        #
        # This key puts the fully-addressed row first, so the card a user ends up
        # reading names the town and the district rather than repeating the
        # locality name back at them. It is a tie-break placed BELOW the match
        # keys, so a slightly-less-literal match is never displaced by this - it
        # only separates rows that the text ranks equally.
        #
        # IT IS SCOPED TO AREA QUERIES, and that scoping is a fix rather than a
        # nicety. Left on for every query it promoted rows the other keys had
        # already decided against, and a one-letter search for "k" came back
        # with "Chunambu Kara Street" and "Darga Lake" and a row with no state at
        # all: those have a city and a district, the key liked them, and they
        # jumped above real towns. The two-index problem it solves only exists
        # when a place is indexed twice, which is what an area search is.
        has_address = 0
        if wants_area:
            has_address = 1 if (
                (
                    candidate.get("city")
                    and not _matches_area(candidate.get("city"), candidate.get("name"))
                )
                and candidate.get("district")
            ) else 0

        # STEP 30: THE RELEVANCE TIER IS THE PRIMARY SORT KEY, NEGATED.
        #
        # It leads for the reason stated on `_relevance_tier`: the five tiers are
        # a priority list, and the only way to honour "exact match above prefix
        # match" is to make the tier the FIRST thing compared. It is placed above
        # `literal` because `literal` is a continuous score that can rank a
        # partial answer (2.9) above a clean prefix (2.1) - an inversion the
        # brief's tiers explicitly forbid.
        #
        # THE KEYS BELT IT ARE ALL "BIGGER IS BETTER", and the pool is sorted
        # with `reverse=True` so that a higher score leads. This tier is
        # "LOWER is better" - exact is 0 and "any other" is 4 - so it is
        # NEGATED here. Without the negation the whole ordering inverts and the
        # exact match lands LAST, which is the precise failure the brief's
        # tier 1 is written to prevent.
        #
        # WHAT THE TIER IS MEASURED AGAINST. Normally that is `search_text`, the
        # place name with any kind word stripped. But when the user NAMED A KIND
        # the place word is a "where", not a "what": in "Karaikudi theatre" the
        # town is not the answer, it is the address, and "Karaikudi" is a perfect
        # exact match for the place word - which handed the town tier 0 and put
        # it above the actual Sathyan Theatre. That is Step 24's whole problem
        # reappearing one level up.
        #
        # So for a kind query the tier is measured against the FULL text, which
        # no single row matches, and every row lands in RELEVANCE_OTHER. The
        # `exact_kind` / `kind_agrees` keys below - built by Step 24 for exactly
        # this question - then decide, which is where that decision belongs. A
        # place query is unaffected and keeps its tiers.
        tier = _relevance_tier(
            candidate,
            text if wanted_kind else search_text,
            device_state,
            device_district,
        )

        return (-tier, exact_kind, kind_agrees, area_match, has_address, literal, local, is_country, indian, alias_penalty, -repeated, best)

    # Trim to what was asked for. The candidate pool is deliberately wider than
    # the dropdown (see `_nominatim_window`), so the ranking decides which rows
    # the user is actually shown rather than the provider's relevance order
    # leaking through.
    candidates = _dedupe_candidates(sorted(candidates, key=order, reverse=True))
    # Clear the per-search ambiguity flag so an unrelated later caller of
    # `_relevance_tier` (tests, other services) never inherits this search's
    # state - the attribute is only meaningful while this sort runs.
    _relevance_tier._ambiguous_exact = False
    _relevance_tier._local_exact_exists = False
    return candidates[: max(limit, 1)]


# The plain-English words a user types that name a KIND of place rather than a
# place. They are stripped from the query before it is sent to the providers
# ("Karaikudi railway station" -> "Karaikudi") AND used to rank the results, so
# asking for a railway station returns a railway station.
_KIND_WORDS = {
    "railway station": "railway_station",
    "railway": "railway_station",
    "train station": "railway_station",
    "rail station": "railway_station",
    "bus stand": "bus_station",
    "bus station": "bus_station",
    "bus stop": "bus_station",
    "temple": "place_of_worship",
    "church": "place_of_worship",
    "mosque": "place_of_worship",
    "theatre": "landmark",
    "theater": "landmark",
    "cinema": "landmark",
    "movie": "landmark",
    "college": "college",
    "school": "school",
    "university": "university",
    "hospital": "hospital",
    "hotel": "landmark",
    "restaurant": "restaurant",
    "bank": "bank",
    "shop": "shop",
    "mall": "shop",
    "market": "shop",
    "park": "landmark",
    "museum": "landmark",
    "library": "library",
    "pharmacy": "pharmacy",
    "airport": "landmark",
    # "Nagar" and "Colony" are deliberately mapped to None, NOT to a POI kind.
    # They are how millions of places are NAMED ("Anna Nagar", "Kolar Colony"),
    # so they must never be read as "the user wants a place of this type" -
    # doing so is what made a search for a Tamil Nadu locality rank behind a
    # generic area in Lagos.
    "nagar": None,
    "colony": None,
}


# How much a match found through a STRUCTURAL VARIANT is worth, compared with
# one found through the text the user actually typed. A variant is a fragment
# ("udi" for "karaikudi"), and a fragment is a weak signal: a place genuinely
# called "Udi" scores a perfect 1.0 against it while the real Karaikudi, whose
# full name contains the whole query, scores 0.75. Capping the variant's
# contribution below 1.0 is what stops an exact fragment match from beating a
# real answer, while still letting a genuine rescue through when nothing the
# user typed matches well ("hennai" -> "chenai" -> Chennai).
_VARIANT_RESCUE_DISCOUNT = 0.9

# STEP 9 - the WIDER TOWN POOL asked for when a device area is known AND the
# typed text is still very short. See the call site for the measurements behind
# both numbers: a bare "k" or "ka" matches no town name in the town index at
# the default page size, while the same text with a page of 100 contains real
# local towns. Three letters is the point where the geocoders' own pages start
# to contain the answer, so the widening stops there and the ordinary path
# takes over. 100 is the provider's documented maximum page size.
_LOCAL_TOWN_POOL_MIN_LENGTH = 3
_LOCAL_TOWN_POOL_COUNT = 100


# STEP 24: how many rows the branch list reads. This is the same window the
# dropdown asks for, so the branches offered here are exactly the rows the user
# can see above them - a branch list that disagreed with the visible results
# would be a worse problem than the one it solves.
_STEP24_BRANCH_LIMIT = 8


def _matches_area(value: Any, wanted: Any) -> bool:
    """True when an administrative name matches what the device reported.

    Compared in both directions on folded text, because the geocoder and the
    reverse-geocode rarely use identical spellings or word order ("Tamil Nadu"
    vs "State of Tamil Nadu", "Sivagangai" vs "Sivaganga"). An empty value on
    either side is never a match - a row with no state must not be credited
    because the device's state happens to be unknown too.
    """
    left, right = _fold(value), _fold(wanted)
    return bool(left and right and (left == right or left in right or right in left))


def _local_preference(
    candidate: dict, state: str | None, district: str | None
) -> tuple[int, int]:
    """How close a hit is to the device's own area: (district, state).

    Step 9's ranking key. 0 / 0 when the device's area is unknown, which makes
    it a no-op rather than a guess - with permission denied this is exactly the
    ordering that already shipped.

    DISTRICT BEFORE STATE, and a hit in the device's district scores above one
    merely in the device's state: the district is the smaller, nearer area, so
    it is the better guess for a bare prefix like "k". A hit outside the state
    scores 0/0 and sits below every local one - but it is NOT removed, so
    searching another state or another country still returns real hits.
    """
    if not (state or district):
        return (0, 0)
    # Only the administrative district, never the neighbourhood `area`: a
    # device in Karaikudi reports the district, and a hit whose `area` happens
    # to share a name with it is a coincidence rather than the same district.
    in_district = bool(district) and _matches_area(
        candidate.get("district") or candidate.get("county"),
        district,
    )
    in_state = _matches_area(candidate.get("state"), state)
    return (1 if in_district else 0, 1 if in_state else 0)


# STEP 9 - Nominatim's own coarse classes that mean "a mapped THING, not a
# place someone lives". A one- or two-letter query cannot be the name of a shop
# or a bridge, so a row in one of these classes is never a sensible answer to it
# however close it is. The rows are still returned by an ordinary search - this
# only ever applies to the state-qualified query added for the local preference.
_NON_PLACE_CATEGORIES = frozenset({
    "shop", "amenity", "highway", "building", "landuse", "natural", "water",
    "railway", "aeroway", "tourism", "leisure", "office", "healthcare",
    "barrier", "man_made", "power", "emergency", "military", "boundary",
})


def _row_is_in_place(candidate: dict, place: str) -> bool:
    """True when a row's own ADDRESS says it sits in the place that was asked for.

    Step 10. "Karaikudi college" is a request for a college IN Karaikudi, and the
    place word is a statement about WHERE, not about the name - a college there is
    "Alagappa Govt Arts College", not "Karaikudi College". So the place word is
    looked for in the address fields the provider gave: the city or town, the
    district, and the locality the row sits in.

    This is what tells a genuine local college from one of the same name three
    states away, and it is a check on data the provider supplied - it cannot
    assert a place that was not returned.
    """
    wanted = _fold(place)
    if not wanted:
        return False
    for value in (candidate.get("city"), candidate.get("district"), candidate.get("area")):
        folded = _fold(value)
        if folded and (folded == wanted or wanted in folded):
            return True
    return False


def _kind_phrase_backoffs(text: str, place: str) -> list[str]:
    """SHORTER forms of a "name + kind" phrase, for the feature index.

    Step 10. Nominatim matches short queries and ignores long ones, so a phrase
    has to be offered at more than one length. Measured on the same service:
    "Karaikudi college" returned 15 rows, "Karaikudi railway station" returned
    ZERO, and "Karaikudi railway" returned the station. Dropping the trailing
    word and keeping the distinctive head is what rescues the longer phrases.

    Only whole words are dropped, and the place name is never dropped - what is
    left always has to name the place, so none of these can match some unrelated
    place that happens to share a single word with the query. The generic trailing
    noun is the only thing removed, and only when something else survives it.
    """
    words = [w for w in re.split(r"[^0-9a-zA-Z]+", str(text or "")) if w]
    if len(words) < 2:
        return []
    head = _strip_kind_words(" ".join(words[:-1]))
    if not head or _fold(head) == _fold(place) or _fold(head) == _fold(text):
        return []
    return [head]


# =============================================================================
# STEP 30: THE FIVE RELEVANCE TIERS, AS ONE NUMBER.
# =============================================================================
#
# The brief asks for autocomplete to rank in a specific order, and this is the
# number that does it. Everything the search already knew how to judge is
# condensed into a single comparable TIER, so the order is stated once, in one
# place, and can be read without tracing eleven interacting sort keys:
#
#   0  AN EXACT MATCH on the text as typed
#   1  A PREFIX match - the name begins with what was typed
#   2  THE DEVICE'S OWN DISTRICT / a nearby area
#   3  THE DEVICE'S OWN STATE
#   4  EVERY OTHER REAL HIT
#
# A NOTE ON THE ORDER OF 2 AND 3, because the brief lists the state first.
#
# Taken literally - state before district - the DISTRICT TIER WOULD BE DEAD CODE.
# A device's district always lies inside its state, so a row in the device's
# district also matches its state, and a test for the state would claim it before
# the district was ever consulted. Every genuinely-local hit would be filed as
# "same state" and the neighbourhood tier could never fire.
#
# The order used here is the one this codebase already settled in Step 9, in
# `_local_preference`: DISTRICT BEFORE STATE, "because the district is the
# smaller, nearer area, so it is the better guess for a bare prefix". This keeps
# that decision rather than reversing it for the sake of matching a list, and it
# keeps both tiers reachable. The observable behaviour the brief asks for -
# local places first, distant places last, and an exact name beating both - is
# identical either way.
#
# TWO THINGS THIS IS DELIBERATELY NOT.
#
# It is NOT A FILTER. A row's tier never decides whether the row is shown - only
# where it sits. That is the brief's "do not hide valid results just because they
# are outside the current state", and it is enforced structurally: `search`
# still ends with `sorted(...)[:limit]` over the whole pool, and nothing on this
# path can remove a candidate. A user in Tamil Nadu searching for a place in
# Kerala still gets it, below the local rows.
#
# It is NOT A REPLACEMENT for the provider's own relevance. Everything here is
# measured against what the geocoders actually returned; a place is only ever
# ranked by facts one of them supplied. The provider's order is the default and
# this refines it.
#
# WHY DISTINCT AND SO MUCH SIMPLER THAN `_match_strength`. That function returns
# a CONTINUOUS score for a reason: it has to separate "Anna" from "Anna Nagar" by
# how much of the query the name covers. But for a TIER that continuous score is
# actively harmful, because 2.9 and 2.1 are different answers to "is this a prefix
# match?" - the first is a partial, the second a clean prefix - and collapsing
# them into a float lets a marginal partial outrank a clean prefix, which is the
# exact inversion the brief's tier 1 versus tier 2 rules out. Hence the integer
# buckets, each a question with a yes/no answer.

RELEVANCE_EXACT = 0
# A prefix match INSIDE the device's own district/state (Step 9, part 2): the
# device area outranks the same prefix elsewhere, so "kara" in Tamil Nadu
# leads with Karaikudi ahead of the several foreign villages called Kara.
RELEVANCE_PREFIX = 1
RELEVANCE_NEARBY = 2
RELEVANCE_SAME_STATE = 3
RELEVANCE_OTHER = 4


def _relevance_tier(
    candidate: dict,
    search_text: str,
    device_state: str | None,
    device_district: str | None,
) -> int:
    """Which of the five relevance tiers a candidate belongs to.

    Read the tiers in order and the first one that is TRUE wins, which is what
    makes them a priority list rather than five independent scores. In
    particular an exact match outranks a local prefix match: naming a place is
    an instruction, not a hint, and proximity must never overrule it. That is
    Step 9's rule, kept intact - the local preference still decides ties, but it
    can no longer manufacture one.
    """
    q = _fold(search_text)
    name = _fold(candidate.get("name"))
    area = _fold(candidate.get("area"))
    label = _fold(candidate.get("label"))

    if not q:
        return RELEVANCE_OTHER

    # --- TIER 0: THE NAME IS EXACTLY WHAT WAS TYPED ------------------------
    # A hit whose own name equals the typed text, wherever it is. This is the
    # strongest possible statement that the row is the thing asked for.
    #
    # THE AMBIGUITY RULE (Step 30, part 2). Count the places whose ENTIRE name
    # is the typed text, and note whether any of them sits in the device's own
    # area. BOTH facts are needed, and they decide opposite cases:
    #
    #   * "kara"  - several exact matches (Kara in many countries), NONE of
    #     them local; the answer the local user means (Karaikudi) is only a
    #     PREFIX match. The exact name alone cannot decide, so the foreign
    #     exact matches are demoted to the prefix tier and the local area
    #     breaks the tie in favour of Karaikudi.
    #   * "bengaluru" - several exact matches, but one of them IS in the
    #     device's state, and the device's state wins inside tier 0 via the
    #     ordinary local tie-break key. Demoting the foreign exacts here would
    #     push the Karnataka Bengaluru below a NON-exact local row, which is
    #     exactly the "local hint overrules an instruction" failure Step 30
    #     forbids. So with a local exact match present, nothing is demoted.
    #
    # A DISTINCT single exact name ("salem" with one exact row) is never
    # ambiguous and stays tier 0 wherever it is. The caller computes both
    # facts once per search and threads them in as function attributes;
    # direct calls and tests see them absent, which behaves as False, so the
    # original tiers are unchanged for them. Nothing is removed either way: a
    # demoted exact match still ranks at the prefix tier, above every
    # non-name match.
    exact = name == q or area == q or label == q
    if exact:
        if (
            getattr(_relevance_tier, "_ambiguous_exact", False)
            and not getattr(_relevance_tier, "_local_exact_exists", False)
            and not (
                (device_state and _matches_area(candidate.get("state"), device_state))
                or (device_district and _matches_area(
                    candidate.get("district") or candidate.get("county"), device_district
                ))
            )
        ):
            return RELEVANCE_PREFIX
        return RELEVANCE_EXACT

    # --- TIER 1: THE NAME BEGINS WITH WHAT WAS TYPED -----------------------
    # A prefix, checked against `name`, `area` and `label` because a locality is
    # as often named in the suburb field as in the name field. This is the
    # part-way-through-typing case, and it is the tier the old continuous score
    # ranked least predictably.
    for field in (name, area, label):
        if field and field.startswith(q):
            return RELEVANCE_PREFIX

    # --- TIERS 2 AND 3: HOW NEAR THE DEVICE'S OWN AREA --------------------
    # Reached only by a row that is NOT a name match at all. Read from the
    # district first, then the state, mirroring `_local_preference`: the
    # district is the smaller, nearer area.
    if device_district and _matches_area(
        candidate.get("district") or candidate.get("county"), device_district
    ):
        return RELEVANCE_NEARBY
    if device_state and _matches_area(candidate.get("state"), device_state):
        return RELEVANCE_SAME_STATE

    return RELEVANCE_OTHER


def _is_branch_row(candidate: dict) -> bool:
    """True when this row is a POINT OF INTEREST rather than a settlement.

    A POI is a branch: each Nominatim row is one real location with its own
    coordinates, its own address and its own postcode, and two rows of the same
    name are two branches of one chain - "Indian Bank" in Karaikudi and in
    Madurai. They must all stay separately selectable, so the diversity penalty
    that stops one place name filling the dropdown is switched off for them.

    A settlement is not a branch. Two rows both called "Anna" really are two
    different towns, and showing only one of them is the failure the penalty
    exists to prevent.
    """
    return bool(candidate.get("poi_type")) or (
        not _is_settlement_row(candidate) and candidate.get("kind") == "landmark"
    )


def _is_settlement_row(candidate: dict) -> bool:
    """True when a geocoder row is a locality rather than a mapped thing.

    Open-Meteo says so with a PPL* feature code. Nominatim says it with the
    `category` it returns, and `category` is the field that has to be read:
    `poi_type` cannot stand in for it, because `_poi_kind` deliberately maps
    BOTH a shop and a bare locality to "place" - a village Nominatim returns with
    no city key has to be shown as a place, or it would be labelled a landmark.

    That is why an earlier attempt at this test removed every row and left the
    dropdown empty: it dropped the villages along with the shops. Reading the
    provider's own category separates them cleanly - a locality is category
    "place" (or has no category at all), while the greengrocer that Nominatim
    put at the top of "k, Sivagangai" is category "shop" and the road is
    category "highway".
    """
    if (candidate.get("feature_code") or "").startswith("PPL"):
        return True
    category = (candidate.get("feature_category") or "").lower()
    if category:
        return category not in _NON_PLACE_CATEGORIES
    # No category at all: Nominatim returns none for a bare locality row, and
    # the shaped candidate's own `kind` is the remaining signal.
    return candidate.get("kind") == "place" and not candidate.get("poi_type")


def _is_selectable_place(candidate: dict, *, want_settlement: bool = False) -> bool:
    """True when a row is the kind of thing a user would actually pick.

    The local preference searches a state, and a state contains a great deal
    that is not a place: a taxiway called "K", a service road, a drainage
    channel, a patch of scrub. Nominatim indexes all of them, so a qualified
    query for a single letter legitimately returns rows like these - and being
    in the right state is exactly what the Step 9 key rewards, so one of them
    would otherwise be promoted to the very top of the dropdown.

    A user is looking for somewhere to test water. So the local key is only
    allowed to promote a row that IS somewhere. This is not a filter - the row
    stays in the list and is still reachable - it only stops proximity from
    promoting a road over a town.

    `want_settlement` is the stricter form, used when the typed text is too
    short to be naming anything specific. A one- or two-letter query cannot be
    the name of a shop or a bank branch, so promoting a business on the strength
    of being nearby is promoting the wrong KIND of thing: asked for "k" in
    Sivagangai, the honest local answer is a local town, and the qualified query
    returned a greengrocer called "K. Ganesh Vegetables" and a street called
    "Sivagangai Salai" as its top rows. A settlement is required there, and the
    business stays in the list below the places.
    """
    if _looks_like_country(candidate):
        return False
    is_settlement = _is_settlement_row(candidate)
    if want_settlement:
        return is_settlement
    return is_settlement or bool(candidate.get("poi_type")) or candidate.get("kind") == "landmark"


def _match_strength(query: str, name: str | None, area: str | None = None, label: str | None = None) -> float:
    """How directly the typed text appears in a place's name, from 0 to 3.

    Graded, because a boolean substring test cannot tell a real match from an
    accident. "schweiz" contains "ch" and "linea a" contains "a", so for a
    two-letter query a plain substring test marks EVERY row as a match and ranks
    by nothing at all. What separates them is WHERE the text sits:

      3  the name covers the typed text            ("chennai" -> Chennai)
      2  the name BEGINS with the typed text       ("ch" -> Chennai)
      1  the text appears later in the name, but
         only when it is long enough to be specific ("nagar" -> Anna Nagar)
      0  it does not appear at all

    A short fragment is credited ONLY for a prefix: two letters found in the
    middle of a word is coincidence, not a match, and crediting it is what put
    Switzerland above Chennai for "ch".

    HOW MUCH OF THE QUERY THE NAME COVERS is the deciding factor, and it is what
    makes "Anna Nagar" beat the village of Anna. Both contain the query, so a
    containment test alone cannot separate them - but Anna covers ONE of the
    query's two words and Anna Nagar covers BOTH. Dropping the generic word to
    make the two compare equal is what went wrong before: it made "Anna" and
    "Anna Nagar" literally the same string, so they tied and the village won on
    provider order. A name that answers less of what was typed now scores less,
    however well the part it does answer matches.

    The result is scaled by coverage, so a real but partial answer still ranks
    above a coincidence - "Anna Nagar" for the query "Anna Nagar" outranks Anna
    the village, while Anna is still reachable below it for the query "Anna".
    """
    q = _fold(query)
    n = _fold(name)
    if not q or not n:
        return 0.0

    q_words = [w for w in q.split() if w]
    n_words = set(n.split())
    if not q_words:
        return 0.0

    # What share of the typed words the name contains, as WHOLE words.
    covered = sum(1 for w in q_words if w in n_words)
    coverage = covered / len(q_words)

    if q == n:
        base = 3.0
    elif n.startswith(q):
        base = 2.0
    elif len(q) >= 3 and q in n:
        base = 1.0
    else:
        base = 0.0

    # THE PLACE CAN BE NAMED IN A FIELD OTHER THAN `name`. A locality, a ward, a
    # suburb and a city are the same real place: Nominatim answers "Anna Nagar"
    # with a row whose `name` is the city it sits inside (Tiruvannamalai) and
    # whose `suburb` is Anna Nagar. Judged on the name alone that row looks like
    # an unrelated city and ranks at zero, while a genuinely fuzzy "Nnak" in
    # Pakistan beats it. So a match against the locality fields counts too.
    if base < 3.0:
        for field in (area, label):
            if field and q and (q == _fold(field) or _fold(field).startswith(q)):
                base = max(base, 3.0)
                coverage = 1.0
                break
            if field:
                fw = set(_fold(field).split())
                area_cov = sum(1 for w in q_words if w in fw) / len(q_words)
                if area_cov > coverage:
                    coverage = area_cov
                    if len(q) >= 3 and q in _fold(field):
                        base = max(base, 1.0)

    if base == 0.0:
        return 0.0

    # Below half the query covered, this is not the place being asked for, and
    # the score is scaled away rather than merely demoted, so a full match always
    # outranks a fragment of one.
    return base * (0.5 + 0.5 * coverage)


def _looks_like_country(candidate: dict) -> bool:
    """True when the row IS a country, rather than a place inside one.

    A country row carries its own name in its `country` field - for Switzerland
    that is the same string as its `name` - and has no state or district. It is a
    genuine result, and "India" is a thing users legitimately search for, so it is
    never filtered out. It is only pushed DOWN the list, because when someone is
    part-way through typing a town or a POI, a country row matching by accident is
    a worse suggestion than almost anything else.
    """
    name = _fold(candidate.get("name"))
    country = _fold(candidate.get("country"))
    if not name or name != country:
        return False
    # A row that is also its own state is a region ("Centre, Burkina Faso" has
    # country Burkina Faso and state Centre - different strings, so not a country).
    return not candidate.get("district")


def _is_multi_alias(name: str | None) -> bool:
    """True when the "name" is really several names in one row.

    Nominatim returns a single feature for a country carrying every local
    spelling joined by slashes - "Schweiz/Suisse/Svizzera/Svizra" - and routes
    and transit lines the same way. It is one real feature, so it is never
    hidden, but it must not LEAD a short query: it is a worse answer than a
    place actually called what the user typed. A very long name is treated the
    same way, for the same reason.
    """
    if not name:
        return False
    text = str(name)
    return "/" in text or len(text.split()) > 3


def _requested_kind(text: str) -> str | None:
    """The kind of place the query names, if it names one at all.

    "Karaikudi railway station" -> "railway_station". "Karaikudi" -> None,
    because a bare name asks for a place and not for a particular kind of one.
    Only a whole-word match counts, so "Karaikudi" is never read as asking for a
    railway station just because it contains no such word.
    """
    lowered = re.sub(r"[^a-z\s]", " ", str(text or "").lower())
    words = lowered.split()
    for n in (3, 2, 1):
        for start in range(len(words) - n + 1):
            phrase = " ".join(words[start : start + n])
            kind = _KIND_WORDS.get(phrase)
            if kind:
                return kind
    return None


def _strip_kind_words(text: str) -> str:
    """Remove the kind-of-place words from a query, keeping the place name.

    Nominatim does find "Karaikudi Railway Station" when asked for it, but a
    shorter, better-ranked query for the place itself finds the same station and
    many more of its neighbours. A query that is ONLY a kind word ("hotel") is
    left alone, because there is no place name left to search for and stripping
    it would produce an empty query.
    """
    # A KIND WORD IS ONLY STRIPPED FROM THE END OF A QUERY, never from the
    # middle of a name. "Karaikudi railway station" -> "Karaikudi", because the
    # kind describes the place being looked for. "Anna Nagar" must stay exactly
    # as typed: "Nagar" is not a kind word here, it is half the NAME, and
    # stripping it reduced the query to "Anna" - which is why the search answered
    # with a village in Spain instead of the locality in Chennai.
    #
    # The end test is what distinguishes them: a kind word qualifies what comes
    # BEFORE it ("... railway station"), and a name does not end in one. A trailing
    # "nagar"/"colony" is part of a locality's own name and is kept.
    lowered = re.sub(r"[^a-z\s]", " ", str(text or "").lower())
    words = lowered.split()
    kept: list[str] = []
    index = 0
    while index < len(words):
        matched = False
        for n in (3, 2, 1):
            phrase = " ".join(words[index : index + n])
            # Only a phrase that reaches the END of the query is a kind word.
            if phrase in _KIND_WORDS and index + n == len(words) and _KIND_WORDS[phrase]:
                matched = True
                index += n
                break
        if not matched:
            kept.append(words[index])
            index += 1

    if not kept:
        return text
    # Preserve the original capitalisation of the surviving words.
    original = re.split(r"[\s,]+", str(text or "").strip())
    rebuilt: list[str] = []
    for word in original:
        if word and word.lower() in kept:
            rebuilt.append(word)
    return " ".join(rebuilt) if rebuilt else text


def _geocode_candidates(term: str, count: int) -> list[dict]:
    """Ask the town geocoder for ONE search term and shape the hits.

    A failure of this particular term is not fatal - a variant the service does
    not like simply contributes nothing, and the next term is still asked.
    """
    body = _get(_GEOCODE_URL, {
        "name": term,
        "count": count,
        "language": "en",
        "format": "json",
    })
    results = (body or {}).get("results") or []
    return [c for c in (_candidate_from_geocode(row) for row in results) if c is not None]


def _nominatim_window(limit: int) -> int:
    """How many rows to ask Nominatim for, given how many are wanted.

    Deliberately larger than the dropdown needs. Nominatim ranks its own results
    by its own relevance model, and for a phrase that model favours a string
    similarity it measures over whether the row is the place actually being asked
    for - so the right answer is often not in the first few rows at all. Asking
    for more and then applying THIS module's ranking is what makes the genuine
    match reachable; the caller still only ever receives `limit` rows.

    Bounded at 40 because the provider treats larger pages as abusive, and
    because a wider window buys diminishing returns.
    """
    return min(max(limit * 3, 10), 40)


def _search_nominatim_many(terms: list[str], limit: int) -> list[dict]:
    """Ask Nominatim about every search term, concurrently.

    One slow or retried call no longer holds up the others, so the search costs
    roughly the slowest single lookup instead of the sum of all of them. Threads
    are used because each call is a blocking HTTP request, and the provider's
    rate limit is still respected: `_get` serialises the actual sends per
    service, so concurrency here does not turn into a burst at Nominatim.
    """
    if not terms:
        return []
    if len(terms) == 1:
        return _search_nominatim(terms[0], limit)

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=min(len(terms), 5)) as pool:
        batches = list(pool.map(lambda term: _search_nominatim(term, limit), terms))
    return [hit for batch in batches for hit in batch]


def _geocode_candidates_many(terms: list[str], count: int) -> list[dict]:
    """Ask the town geocoder about every search term, concurrently.

    Same reasoning as `_search_nominatim_many`: the variants are independent
    lookups, and waiting for them one at a time is what turned a two-second
    search into a ten-second one.
    """
    if not terms:
        return []
    if len(terms) == 1:
        return _geocode_candidates(terms[0], count)

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=min(len(terms), 5)) as pool:
        batches = list(pool.map(lambda term: _geocode_candidates(term, count), terms))
    return [hit for batch in batches for hit in batch]


def _search_terms_bounded(text: str, *, full: bool) -> list[str]:
    """The search terms to ask the providers about, within a request budget.

    Autocomplete is interactive, so the number of provider calls is bounded by
    how long a user will wait. A first-typed fragment ("k", "c") cannot have
    many real matches anyway, and asking five providers five variants of a single
    letter is both slow and pointless.

      * `full=True`  - the "resolve one place" path. Every variant is asked,
        because the answer has to be RIGHT and a miss here means the wrong water
        source, not a slightly late suggestion.
      * `full=False` - the autocomplete path. Terms are capped, so the first
        suggestion arrives in a fraction of a second. Typing more characters
        widens the budget, because there is more to disambiguate by then.

    The cap never changes WHAT is matched, only how many spellings are tried, so
    every candidate from either path is still a real geocoder hit.
    """
    terms = _search_terms(text)
    if full:
        return terms
    # 2 while one or two characters are being typed, then one extra term per
    # character up to 5, which is enough to reach "kudi" -> Karaikudi without
    # spending a dozen round trips on a six-letter word.
    cap = min(max(len(text.strip()), 2), 5)
    bounded = terms[:cap]

    # THE TEXT AS TYPED IS NEVER DROPPED. This is the most important guarantee
    # the cap has to keep, and losing it was a real bug: a two-word query produces
    # a spelling correction and a fragment backoff BEFORE the whole-phrase
    # backoff, so "Anna Nagar" spent all five of its slots on "nna", "anna nagr",
    # "Nagar", "Anna" and "anna sar" and Nominatim was never once asked for
    # "Anna Nagar" - the one query it answers with ten real rows. The list was
    # full of Nigerian and Pakistani villages that shared two letters, because
    # those were the only things anyone had asked about.
    #
    # So the typed text is put first if the cap displaced it. The extra terms are
    # the speculative ones, and those are exactly what a budget should trim.
    if text not in bounded:
        bounded = [text] + bounded[: cap - 1]
    return bounded


def _dedupe_candidates(candidates) -> list[dict]:
    """Collapse the same place reached through several search terms.

    Two terms can return the same town - "chennai", "chenn" and "hen" all reach
    Chennai - and the dropdown must list it once. The key is the coordinates
    rounded to about a hundred metres, falling back to the folded name so two
    genuinely different places that share a name are not merged away. The FIRST
    occurrence wins, so the order the caller built the list in is preserved.
    """
    seen: set = set()
    unique: list[dict] = []
    for candidate in candidates:
        lat, lon = candidate.get("lat"), candidate.get("lon")
        if lat is not None and lon is not None:
            key = ("geo", round(float(lat), 3), round(float(lon), 3))
        else:
            key = ("name", _fold(candidate.get("name")))
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def _split_qualified(text: str) -> dict:
    """Split "Village, District" / "Village, District, State" into its parts.

    The FIRST segment is always the place name; every later segment is a
    qualifier (district, then state, and so on) that narrows the search rather
    than forming part of the name. A query with no comma is returned unchanged
    with no qualifiers, so the ordinary single-name search is untouched.
    """
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if len(parts) < 2:
        return {"place": text, "qualifiers": []}
    return {"place": parts[0], "qualifiers": parts[1:]}


def _apply_qualifiers(candidates: list[dict], qualifiers: dict) -> list[dict]:
    """Keep the hits whose district/state match a qualifier, promoting them.

    Matching is case-insensitive and substring-based in BOTH directions, because
    the geocoder and the user rarely agree on spelling ("Thiruvidaimarudur" vs
    "Thiruvidaimarudur taluk") or on the word order. When no hit matches any
    qualifier the full list is returned unchanged: the user's place still exists,
    and dropping it because of a spelling difference would be worse than showing
    a nearby alternative they can pick from the list themselves.
    """
    wanted = [q.lower() for q in qualifiers.get("qualifiers") or []]
    if not wanted or not candidates:
        return candidates

    def matches(candidate: dict) -> bool:
        fields = [
            str(candidate.get("district") or "").lower(),
            str(candidate.get("state") or "").lower(),
            str(candidate.get("county") or "").lower(),
            str(candidate.get("city") or "").lower(),
            # The area/locality is matched too, so "Karaikudi, Anna Nagar" narrows
            # to a hit whose own neighbourhood is Anna Nagar.
            str(candidate.get("area") or "").lower(),
            str(candidate.get("label") or "").lower(),
        ]
        return any(
            any(w in f or f in w for f in fields if f)
            for w in wanted
        )

    matched = [c for c in candidates if matches(c)]
    if not matched:
        return candidates
    # The qualifier is the user's intent, so the matching hits lead.
    rest = [c for c in candidates if not matches(c)]
    return matched + rest


# =============================================================================
# STEP 24: "THEATRE IN KARAIAKUDI" IS A STRUCTURED QUESTION, NOT A SENTENCE.
# =============================================================================
#
# WHAT WAS ACTUALLY BROKEN, MEASURED AGAINST THE LIVE GEOCODER
# -----------------------------------------------------------
# A user typing one of the brief's categories got the wrong thing, every time,
# and the reason is the instrument rather than the data:
#
#   "Karaikudi theatre"   free text -> the TOWN, and unrelated villages.
#                         The map HAS Sathyan Theatre and Sivam theatre in that
#                         town, with coordinates, an area and a pincode.
#   "Karaikudi cinema"    free text -> 0 rows.
#   "Karaikudi landmark"  free text -> the TOWN.
#   "Karaikudi Maranatha college"  free text -> 0 rows.
#
# Nominatim's FREE-TEXT index ranks on string similarity, so a two-word phrase
# where the second word is a category ("Karaikudi theatre") is a weak match and
# the town wins. But the same index answers the STRUCTURED form of the identical
# question correctly: bounded to the town, filtered to `amenity=cinema`, it
# returns exactly the two real theatres.
#
# SO THIS BLOCK ASKS THE QUESTION TWICE - once as text, once as a structure -
# and merges the two. The free-text rows are untouched, so nothing that works
# today can regress; the structured rows can only ADD real branches.
#
# THE ANCHOR MUST BE A SETTLEMENT. This is the rule that decides whether the
# structural query can run at all, and it was measured: a `viewbox` taken from a
# POINT OF INTEREST is a sub-metre box (an "Indian Bank" node has a bounding box
# 3 x 10 metres across), and a bounded query inside it returns nothing, ever. A
# city or town row has a box kilometres wide, and the same query inside it
# returns the real rows. So the anchor is only accepted when the provider types
# it as a settlement, and without one the structured query falls back to an
# unbounded one - which is what makes "Indian Bank Karaikudi" work at all, since
# that text has no settlement in it to anchor on.
#
# THE PROVIDER'S OWN `category` PARAMETER IS NOT TRUSTED. Measured: asked for
# `category=amenity&type=cinema` inside a town box, the service returned a
# residential street, a primary road and a police station alongside the two
# theatres. The filter is a hint the service applies loosely, so EVERY row is
# re-checked against its own `category`/`type` before it is admitted. A road is
# never shown as a theatre.
#
# NOTHING IS INVENTED. Every row this block returns is a row the geocoder
# actually sent, carrying its own real coordinates, area, district, state and
# pincode. A kind the map holds nothing for simply contributes no rows, and the
# ordinary search result stands.
_KIND_STRUCTURED_QUERIES: dict[str, dict] = {
    "college": {"categories": {"amenity": {"college", "university"}}, "texts": ("college",)},
    "university": {"categories": {"amenity": {"university", "college"}}, "texts": ("university",)},
    "school": {"categories": {"amenity": {"school", "kindergarten"}}, "texts": ("school",)},
    "hospital": {
        "categories": {"amenity": {"hospital", "clinic", "doctors"},
                       "healthcare": {"hospital", "clinic"}},
        "texts": ("hospital",),
    },
    "bank": {"categories": {"amenity": {"bank"}}, "texts": ("bank",)},
    "shop": {"categories": {"shop": set()}, "texts": ("shop", "store")},
    "mall": {"categories": {"shop": set()}, "texts": ("mall",)},
    "market": {"categories": {"shop": set()}, "texts": ("market",)},
    "hotel": {
        "categories": {"tourism": {"hotel", "hostel", "guest_house", "motel"}},
        "texts": ("hotel",),
    },
    "restaurant": {
        "categories": {"amenity": {"restaurant", "cafe", "fast_food", "bar"}},
        "texts": ("restaurant",),
    },
    "library": {"categories": {"amenity": {"library"}}, "texts": ("library",)},
    "pharmacy": {"categories": {"amenity": {"pharmacy"}}, "texts": ("pharmacy",)},
    # THEATRE. OSM types a cinema as `amenity=cinema` but names the building
    # "Theatre", so the CATEGORY is cinema while the WORD that finds it is
    # "theatre". Measured: "Karaikudi theatre" returned both of the town's
    # cinemas and "Karaikudi cinema" returned none. Both spellings are therefore
    # asked, and both `cinema` and `theatre` are accepted.
    "theatre": {
        "categories": {"amenity": {"cinema", "theatre"}},
        "texts": ("theatre", "theater", "cinema"),
    },
    # TEMPLE. The same split, in the other direction: the row is
    # `amenity=place_of_worship`, and the name uses "Temple" or "Kovil" about
    # equally. Measured inside one town: "temple" returned 6 places of worship
    # and "kovil" returned 3 MORE that "temple" did not, so both are asked.
    "temple": {
        "categories": {"amenity": {"place_of_worship"}},
        "texts": ("temple", "kovil"),
    },
    # RAILWAY STATION. The real junction is mapped as `landuse=railway` - the
    # word "station" appears only in its NAME - while a platform is
    # `railway=station`. Both are accepted, and both are asked for, because
    # asking for one of them alone loses the other.
    "railway station": {
        "categories": {"railway": {"station", "halt"}, "landuse": {"railway"}},
        "texts": ("railway station", "railway"),
    },
    # BUS STAND. The depot is `amenity=bus_station`; a `highway=bus_stop` is a
    # different thing and is deliberately NOT accepted here, because a bus STOP
    # is not a bus STAND and the user asked for a stand.
    "bus stand": {
        "categories": {"amenity": {"bus_station"}},
        "texts": ("bus stand", "bus station"),
    },
}

# Phrase lengths, longest first, so "railway station" is read as one phrase and
# not as "railway" followed by a stray "station".
_KIND_PHRASE_LENGTHS = (2, 1)

# STEP 24: the box around the anchor is CLAMPED. A city row's own bounding box
# is the whole municipal area - Madurai's is tens of kilometres across - and an
# unclamped box would return every college in the district for a search about
# one neighbourhood. 0.2 degrees is about 22 km, which comfortably contains a
# town while stopping the query crossing into its neighbour.
_STRUCTURED_BOX_HALF_DEGREES = 0.2

# How many provider calls one structured query may make. Each kind has a small,
# measured set of (word, category) combinations; this only stops a future kind
# with a long list from turning one search into a fan-out.
_STRUCTURED_MAX_QUERIES = 4


def _structural_kind_phrase(text: str) -> str | None:
    """The kind of place this query names, as a phrase STEP 24 can search for.

    "Karaikudi theatre" -> "theatre".  "Karaikudi" -> None, because a bare name
    asks for a place and not for a particular KIND of one - the ordinary search
    is correct for that and is left completely alone.

    This is deliberately its own table rather than a reuse of `_requested_kind`.
    That function answers "which ranking bucket does this match", and it files
    both a theatre and a hotel under the single bucket "landmark", because the
    RANKING only needs to know they are not a place. This needs the exact kind,
    because it is what decides the OSM category to filter on, and "landmark" is
    not an OSM category. A "landmark" that names no specific kind therefore has
    no structural form and is answered by the ordinary search - which is correct,
    since a user typing a famous place's NAME gets that place today.
    """
    lowered = re.sub(r"[^a-z\s]", " ", str(text or "").lower())
    words = lowered.split()
    for size in _KIND_PHRASE_LENGTHS:
        for start in range(len(words) - size + 1):
            phrase = " ".join(words[start : start + size])
            if phrase in _KIND_STRUCTURED_QUERIES:
                return phrase
    return None


def _strip_structural_phrase(text: str, phrase: str | None) -> str:
    """The query with its kind phrase removed, wherever the phrase sat.

    "Karaikudi railway station" -> "Karaikudi"
    "Indian Bank Karaikudi"     -> "Indian Karaikudi"  (no phrase, unchanged)
    "railway station Karaikudi" -> "Karaikudi"

    A kind word can sit at the end ("Karaikudi railway station"), at the front
    ("railway station Karaikudi") or in the middle ("Indian Bank Karaikudi" has
    none at all, while "Bank of Karaikudi branch" has one in the middle), so the
    phrase is removed wherever it occurs rather than only from the end. What
    remains is the NAME of the thing, which is what the anchor lookup wants.
    """
    if not phrase:
        return str(text or "").strip()
    target = phrase.split()
    words = str(text or "").split()
    kept: list[str] = []
    index = 0
    while index < len(words):
        window = [w.lower().strip(".,()'") for w in words[index : index + len(target)]]
        if window == target:
            index += len(target)
            continue
        kept.append(words[index])
        index += 1
    return " ".join(kept).strip(" ,-")


def _viewbox(row: dict, half_degrees: float = _STRUCTURED_BOX_HALF_DEGREES) -> str | None:
    """A clamped `left,top,right,bottom` box around a row, or None.

    Nominatim wants lon_min,lat_max,lon_max,lat_min, while the row reports
    [south, north, west, east] - the order is different in both axis and
    direction, and getting it wrong returns a box on the far side of the world
    rather than an error.

    The box is clamped around the row's OWN centre, because a city's bounding
    box is the whole municipality: Madurai's covers tens of kilometres, so an
    unclamped box answers a question about one town with every college in the
    district. Clamping keeps the anchor town in and its neighbour out.
    """
    box = row.get("boundingbox")
    if not box or len(box) != 4:
        return None
    try:
        south, north, west, east = (float(value) for value in box)
    except (TypeError, ValueError):
        return None
    centre_lat = (south + north) / 2.0
    centre_lon = (west + east) / 2.0
    lat = min(max(half_degrees, 0.001), abs(centre_lat) or half_degrees)
    lon = min(half_degrees, 180.0)
    south = max(centre_lat - lat, -85.0)
    north = min(centre_lat + lat, 85.0)
    west = max(centre_lon - lon, -180.0)
    east = min(centre_lon + lon, 180.0)
    return f"{west},{north},{east},{south}"


def _settlement_anchor(text: str) -> tuple[str, dict] | None:
    """A real SETTLEMENT row for this text, and the box around it.

    Returns None when the text names no settlement the map knows, which is the
    normal case for a business query - "Indian Bank Karaikudi" contains a town
    name but the provider files both hits as `amenity=bank`, not as a place.
    The caller then runs the structured query unbounded, which is what makes
    those searches work.

    ONLY A SETTLEMENT IS ACCEPTED, and this is the load-bearing rule. A point of
    interest's bounding box is the size of the building (measured: one "Indian
    Bank" node has a box 3 x 10 metres across), and a bounded query inside it
    returns nothing at all. A city or town box is kilometres wide and the same
    query inside it returns the real rows. Accepting a POI as an anchor is
    therefore not a worse answer - it is no answer.
    """
    text = _clean(text)
    if not text:
        return None
    body = _get(_SEARCH_URL, {
        "q": text,
        "format": "jsonv2",
        "addressdetails": 1,
        "limit": 10,
    })
    if not isinstance(body, list):
        return None
    for row in body:
        if (_clean(row.get("type")) or "").lower() not in _SETTLEMENT_TYPES:
            continue
        box = _viewbox(row)
        if box:
            return box, row
    return None


def _matches_structural_kind(row: dict, spec: dict) -> bool:
    """True when the row's OWN tags say it is one of the kind's places.

    The provider's `category` query parameter is a hint, not a guarantee.
    Measured: `category=amenity&type=cinema` bounded to one town came back with
    a residential street, a primary road and a police station next to the two
    real cinemas. So the parameter is used to WIDEN the search and every row is
    then checked against the `category`/`type` the service reported for that
    specific row. This is the check that keeps a road out of a list of
    theatres, and it can only ever remove rows - it can never add one.
    """
    category = (_clean(row.get("category")) or "").lower()
    if not category:
        return False
    accepted = spec["categories"].get(category)
    if accepted is None:
        return False
    if not accepted:
        # The category is the whole test (a shop is a shop).
        return True
    return (_clean(row.get("type")) or "").lower() in accepted


def _structural_candidates(
    text: str, phrase: str, limit: int
) -> list[dict]:
    """The real branches of `phrase` that the map holds for this query.

    `text` is the query as typed; `phrase` is the kind it names. Returns a list
    of real rows, which may legitimately be empty - the map holds no theatre in
    that town, and the honest answer to that is no row rather than a guess.
    """
    spec = _KIND_STRUCTURED_QUERIES.get(phrase)
    if not spec:
        return []

    name_text = _strip_structural_phrase(text, phrase)
    anchor = _settlement_anchor(name_text) or _settlement_anchor(text)
    viewbox = anchor[0] if anchor else None
    # THE TEXT EACH STRUCTURED CALL IS ASKED FOR.
    #
    # With an anchor, every call is the anchor's own NAME plus ONE kind word -
    # "Karaikudi theatre", "Karaikudi theater" - never the query as typed. This
    # is the measured form that works, and building it from `name_text` rather
    # than from the typed text is what stops the phrase appearing twice: the
    # earlier version asked for "Karaikudi theatre theatre", which is a
    # different string to the index and matches nothing.
    #
    # Without an anchor there is no settlement to bound to, and the query as
    # typed is the only context there is ("Indian Bank Karaikudi"), so that is
    # what is asked - and the kind word is already inside it.
    if anchor:
        anchor_name = _clean(anchor[1].get("name")) or name_text
        calls: list[dict] = [
            {"q": f"{anchor_name} {word}".strip(), "category": None}
            for word in spec["texts"]
        ]
    else:
        calls = [{"q": str(text or "").strip(), "category": None}]

    # The per-category calls carry the provider's own filter, which widens the
    # pool; the row re-check in `_matches_structural_kind` is what enforces it.
    # These reuse the anchor's name with the KIND PHRASE exactly once, so they
    # differ from the word calls only in the way that matters to the index.
    if anchor:
        category_base = f"{_clean(anchor[1].get('name')) or name_text} {phrase}".strip()
    else:
        category_base = str(text or "").strip()
    for category in spec["categories"]:
        calls.append({"q": category_base, "category": category})

    from concurrent.futures import ThreadPoolExecutor

    def run(call: dict) -> list:
        params = {
            "q": call["q"],
            "format": "jsonv2",
            "addressdetails": 1,
            "limit": _nominatim_window(limit),
            "extratags": 1,
            "namedetails": 1,
        }
        if viewbox:
            params["viewbox"] = viewbox
            params["bounded"] = 1
        if call["category"]:
            params["category"] = call["category"]
        body = _get(_SEARCH_URL, params)
        if not isinstance(body, list):
            return []
        return [row for row in body if _matches_structural_kind(row, spec)]

    with ThreadPoolExecutor(max_workers=min(len(calls), _STRUCTURED_MAX_QUERIES)) as pool:
        batches = list(pool.map(run, calls))

    # Shaped once, from the pooled raw rows, so the same branch found by two of
    # the calls is de-duplicated by coordinates rather than appearing twice.
    return _dedupe_candidates(
        _candidates_from_nominatim_rows(
            [row for batch in batches for row in batch]
        )
    )


def _looks_like_poi(query: str, candidate: dict) -> bool:
    """True when the query names a specific POI the town geocoder cannot find.

    A multi-word query ("Meenakshi Amman Temple") or one that is not simply the
    candidate's own name is likely a landmark, so Nominatim is tried for a
    better, more specific match.
    """
    if len(query.split()) > 1:
        return True
    return (candidate.get("name") or "").lower() != query.lower()


def _google_places_key() -> str | None:
    """Read the Maps Platform key from the environment, once, on first use."""
    global _GOOGLE_PLACES_KEY_CACHE
    if _GOOGLE_PLACES_KEY_CACHE is _GOOGLE_PLACES_UNSET:
        value = (os.environ.get("GOOGLE_PLACES_API_KEY") or "").strip()
        _GOOGLE_PLACES_KEY_CACHE = value or None
    return _GOOGLE_PLACES_KEY_CACHE


def _google_places_post(payload: dict) -> dict | None:
    """POST one query to Places API (New) and return the parsed body, or None.

    A paid endpoint, so the free services' per-URL politeness sleeps do not
    apply. What IS kept: a short timeout (a search must stay interactive),
    retry-on-5xx, and the response cache, so the same text is not billed twice.
    """
    key = _google_places_key()
    if not key:
        return None
    cache_key = _cache_key(_GOOGLE_PLACES_URL, payload)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": _GOOGLE_PLACES_FIELD_MASK,
    }
    for places_attempt in range(2):
        try:
            response = _session.post(
                _GOOGLE_PLACES_URL, json=payload, headers=headers, timeout=6
            )
            if response.status_code == 200:
                body = response.json()
                _cache_put(cache_key, body)
                return body
            if response.status_code in (429, 500, 502, 503):
                time.sleep(0.6 * (places_attempt + 1))
                continue
            logger.info("Google Places returned %s", response.status_code)
            return None
        except requests.RequestException as exc:
            logger.info("Google Places request failed: %s", exc)
            break
    return None


def _candidates_from_google_rows(body) -> list[dict]:
    """Shape Google Places rows into the SAME candidate shape Nominatim uses.

    One shape is the whole point: a Google row and an OSM row are the same kind
    of object to the dropdown, the qualifier filter and the ranking, so they are
    built in one vocabulary. Google gives typed address components instead of a
    flat `address` dict, and `location` instead of lat/lon strings.
    """
    if not isinstance(body, dict):
        return []
    rows = body.get("places") or []
    if not isinstance(rows, list):
        return []

    candidates: list[dict] = []
    for row in rows:
        location = row.get("location") or {}
        lat, lon = location.get("latitude"), location.get("longitude")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            continue

        components = row.get("addressComponents") or []

        def comp(*types: str) -> str | None:
            for part in components:
                for wanted in types:
                    if wanted in (part.get("types") or []):
                        value = _clean(part.get("longText")) or _clean(part.get("shortText"))
                        if value:
                            return value
            return None

        name = _clean((row.get("displayName") or {}).get("text"))
        if not name:
            continue
        area = comp("sublocality", "sublocality_level_1", "neighborhood", "premise")
        city = comp("locality", "postal_town") or area
        district = comp("administrative_area_level_2", "administrative_area_level_3")
        state = comp("administrative_area_level_1")
        country = comp("country")
        pincode = comp("postal_code")
        poi_label = _clean((row.get("primaryTypeDisplayName") or {}).get("text"))

        parts = [name]
        if area and area not in parts:
            parts.append(area)
        for value in (city, district, state, country):
            if value and value not in parts:
                parts.append(value)
        branch_parts: list[str] = []
        for value in (city or area, district, state, country):
            value = _clean(value)
            if value and value not in branch_parts:
                branch_parts.append(value)
        branch_label = f"{name} - {', '.join(branch_parts)}" if branch_parts else name

        candidates.append({
            "name": name,
            "city": city or area or name,
            "label": ", ".join(parts),
            "branch_label": branch_label,
            "display_name": _clean(row.get("formattedAddress")),
            "country": country,
            "country_code": (comp("country") and "IN") or None,
            "state": state,
            "district": district,
            "area": area,
            "pincode": pincode,
            "lat": float(lat),
            "lon": float(lon),
            # A Google row is always a specific point of interest or an exact
            # address, never a settlement-level guess.
            "kind": "landmark",
            "poi_type": "landmark",
            "poi_label": poi_label,
            "feature_category": None,
            "feature_type": None,
            "google_place_id": row.get("id") or None,
        })
    return candidates


def _search_google_places(text: str, limit: int) -> list[dict]:
    """Ask Google Places for the text AS TYPED, shaped like the other hits.

    No case-folding or spelling variants here: Google's index is where the
    business names as written on signboards live, which is exactly what the
    free geocoders were missing. A region code keeps same-named places in other
    countries from crowding the top of the pool, without filtering anything.
    """
    payload = {
        "textQuery": text,
        "maxResultCount": min(max(limit, 5), 20),
        "languageCode": "en",
        "regionCode": "IN",
    }
    body = _google_places_post(payload)
    return _candidates_from_google_rows(body)


def _search_google_places_many(texts: list[str], limit: int) -> list[dict]:
    """Ask Google about each text, concurrently, and merge the rows."""
    if not texts:
        return []
    if len(texts) == 1:
        return _search_google_places(texts[0], limit)
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=min(len(texts), 4)) as pool:
        batches = list(pool.map(lambda text: _search_google_places(text, limit), texts))
    return [row for batch in batches for row in batch]


def _search_nominatim(query: str, limit: int) -> list[dict]:
    """Forward-search Nominatim and shape hits like the Open-Meteo candidates.

    Nominatim's ``address`` block splits the settlement name across city, town,
    village, municipality and hamlet keys depending on the place's size, so the
    first present key is the city/town. ``postcode``, ``county`` (district) and
    ``state`` give the rest of the card; anything the service does not know
    stays None rather than being guessed.

    Beyond towns, this is also the path that finds the OTHER things a user types
    into a location box: a college, a school, a shop or a bank branch, and a
    locality (nagar, colony, ward, street). Nominatim tags each hit with a
    category/class, and the ``address`` block carries the neighbourhood and
    suburb keys that the settlement-only path above ignored. All of it is
    preserved here so the dropdown can say WHAT the hit is and WHERE inside the
    town it sits, and so several branches of one chain come back as separate,
    individually selectable entries.

    STEP 10 - THE SEARCH TEXT IS SENT IN BOTH CASES, BECAUSE NOMINATIM'S FREE-TEXT
    SEARCH IS CASE-SENSITIVE AND ITS INDEX IS MOSTLY LOWER-CASE. This was
    measured, not assumed: the query "Indian Bank" returned ZERO rows, and the
    same query lower-cased, "Indian bank", returned 25 - the actual bank branches.
    Nominatim treats the capitalised word as part of a proper noun it has no
    entry for, so a user typing a name the way any business writes it on its
    signboard got an empty dropdown.

    So the query is sent once as typed and once folded to lower case, and the
    two sets of hits are merged. The lower-case form is always a subset of what
    the exact form can reach, so this cannot invent anything; it only makes the
    exact form able to find the rows that were already there. It costs one extra
    request per term, which is the same trade the module already makes for the
    spelling variants.
    """
    body = _get(_SEARCH_URL, {
        "q": query,
        "format": "jsonv2",
        "addressdetails": 1,
        # Ask for MORE rows than the dropdown shows. Nominatim's free-text search
        # is fuzzy, so for a phrase the genuine matches are often pushed past the
        # API's default window by near-misses: asked for "Anna Nagar" it filled a
        # window of ten with Nigerian and Pakistani villages sharing two letters,
        # and the real Anna Nagar in Tamil Nadu never came back at all. Widening
        # the window is what puts the real rows in the pool to be ranked; the
        # ranking, not this count, decides what the user is shown.
        "limit": _nominatim_window(limit),
        "extratags": 1,
        "namedetails": 1,
    })
    if not isinstance(body, list):
        body = []

    # The second attempt, in lower case. The two are concatenated and the caller
    # de-duplicates by coordinates, so a row found by both costs nothing extra.
    lowered = _fold(query)
    if lowered and lowered != _fold(str(query or "")):
        # `_fold` also strips punctuation, so a query that is only letters and
        # spaces is sent as it is and a query with a comma or a hyphen is not
        # sent a second time in a mangled form.
        if re.fullmatch(r"[0-9a-z ]+", str(query).lower()):
            second = _get(_SEARCH_URL, {
                "q": str(query).lower(),
                "format": "jsonv2",
                "addressdetails": 1,
                "limit": _nominatim_window(limit),
                "extratags": 1,
                "namedetails": 1,
            })
            if isinstance(second, list):
                body = body + second
    return _candidates_from_nominatim_rows(body)


def _candidates_from_nominatim_rows(body) -> list[dict]:
    """Shape raw Nominatim rows into candidates.

    Split out of `_search_nominatim` in STEP 24 so the STRUCTURED branch queries
    produce candidates by exactly the same code as the free-text ones. That is
    deliberate: a branch found by a category-scoped query and a branch found by
    a text query are the same kind of object, and shaping them with two different
    pieces of code is how the two lists quietly start disagreeing about which
    fields a card has.
    """
    if not isinstance(body, list):
        return []

    candidates: list[dict] = []
    for row in body:
        lat, lon = row.get("lat"), row.get("lon")
        if lat is None or lon is None:
            continue
        address = row.get("address") or {}
        city = (
            _clean(address.get("city"))
            or _clean(address.get("town"))
            or _clean(address.get("village"))
            or _clean(address.get("municipality"))
            or _clean(address.get("hamlet"))
        )
        name = _clean(row.get("name")) or city
        if not name:
            continue
        state = _clean(address.get("state")) or _clean(address.get("region"))
        district = _clean(address.get("county")) or _clean(address.get("district"))
        country = _clean(address.get("country"))

        # --- WHAT the hit IS. Nominatim tags each hit with a coarse category and a
        # specific type ("amenity" + "school"). It is the TYPE that identifies the
        # place, and it is the value the search must key on.
        category = _clean(row.get("category")) or ""
        osm_class = _clean(row.get("class")) or ""
        row_type = _clean(row.get("type")) or ""
        place_kind = _poi_kind(category, row_type)

        # --- WHERE inside the town. A "colony"/"nagar"/"ward" hit has no city of
        # its own, so the neighbourhood keys are what make it identifiable and
        # what the qualifier filter below must match against.
        area = (
            _clean(address.get("neighbourhood"))
            or _clean(address.get("suburb"))
            or _clean(address.get("quarter"))
            or _clean(address.get("neighbourhood"))
        )

        # STEP 11: A ROW THAT IS ITSELF A LOCALITY IS ITS OWN AREA.
        #
        # The keys above ask "which neighbourhood does this place sit inside?",
        # which is the right question for a shop or a college. For a nagar the
        # question has the opposite answer: the row IS the neighbourhood, and it
        # is sitting in a city, so none of those keys is populated and `area`
        # came back None. That left the selected-location card with an empty
        # "Area" line for exactly the kind of place Step 11 is about, while the
        # same nagar reached through a different query came back with one.
        #
        # The name is used, and only when the provider has filed the row as a
        # locality. It is the provider's own name for the area, so nothing is
        # invented - and for a town or a village this branch is never reached,
        # so "Karaikudi" is never described as an area of itself.
        if not area and row_type in _LOCALITY_TYPES:
            area = _clean(name)

        # --- THE NAME THE PLACE ACTUALLY GOES BY.
        #
        # Nominatim names an administrative area after its zone or its number, so
        # the real Anna Nagar in Chennai comes back as "Zone 8 Anna Nagar" and a
        # village in the same area as "Zone 12 Anna Nagar". Judged on that string,
        # a search for "Anna Nagar" matches neither, and genuinely unrelated rows
        # ("Nnak", "Nnabi" - real places in Nigeria and Pakistan that share two
        # letters) won instead. `namedetails._place_name` is the provider's own
        # canonical name for the place, free of the zone prefix, so it is what the
        # user's words are matched against. It is a name the geocoder itself
        # supplies, so nothing is invented by preferring it.
        namedetails = row.get("namedetails") or {}
        place_name = _clean(namedetails.get("_place_name")) or None
        # Only use the canonical name when it is genuinely shorter - it is the
        # same place, and dropping a real qualifier ("Zone 8") would make two
        # different zones of one locality look like a single place.
        if place_name and len(place_name) < len(name):
            name = place_name
            area = None

        parts = [name]
        # A named point of interest reads best with its own category
        # ("Indian Bank - Bank") and its area, not with a bare city name.
        if area and area not in parts:
            parts.append(area)
        for value in (city, district, state, country):
            if value and value not in parts:
                parts.append(value)

        # STEP 10: THE LABEL THAT TELLS ONE BRANCH FROM ANOTHER.
        #
        # "ABC Store" alone does not identify a place, and neither does "ABC
        # Store, Karaikudi" once there is a second one in Chennai. What
        # separates them is the whole address, so the branch label is built from
        # the fullest sequence of place names this row actually has: the area
        # inside the town, the town, the district, the state and the country.
        #
        # This is the format the brief asks for -
        #     ABC Store - Karaikudi, Sivaganga, Tamil Nadu
        #     ABC Store - Chennai, Tamil Nadu
        # The NAME is separated from the address by a dash, and the address parts
        # by commas, because that is what makes the two halves readable as two
        # things: the same name on every row, and the part that differs. Joining
        # all of them with dashes instead makes each line harder to scan, since
        # the eye cannot tell where the name ends.
        #
        # It is assembled from the provider's own fields, in that order, with
        # anything the map does not know simply absent. Nothing is filled in and
        # no field is invented; a row the geocoder knows nothing more about than
        # its own name yields just the name.
        branch_parts: list[str] = []
        for value in (city or area, district, state, country):
            value = _clean(value)
            if value and value not in branch_parts:
                branch_parts.append(value)
        branch_label = (
            f"{name} - {', '.join(branch_parts)}" if branch_parts else name
        )

        candidates.append({
            "name": name,
            "city": city or area or name,
            "label": ", ".join(parts),
            # STEP 10: the branch-distinguishing label. Separate from `label` so
            # nothing that already relies on it changes, and used by the dropdown
            # whenever several rows share a name.
            "branch_label": branch_label,
            "display_name": _clean(row.get("display_name")),
            "country": country,
            "country_code": (_clean(address.get("country_code")) or "").upper() or None,
            "state": state,
            "district": district,
            "area": area,
            "pincode": _clean(address.get("postcode")),
            "lat": float(lat),
            "lon": float(lon),
            # `kind` distinguishes a real mapped point (a college, a bank
            # branch) from a settlement, so the UI can label it correctly.
            "kind": "landmark" if place_kind != "place" else ("place" if city else "landmark"),
            "poi_type": place_kind or None,
            "poi_label": _POI_LABELS.get(place_kind),
            # The provider's OWN coarse class, kept because it is the one field
            # that separates "a place" from "a thing that happens to be mapped".
            # Step 9's short-query filter needs it: for "k, Sivagangai" the only
            # row Nominatim returned was category=shop, and for "ka, Tamil Nadu"
            # they were a bank and a highway bridge. A locality comes back as
            # category=place or boundary, which this distinguishes correctly.
            "feature_category": category or None,
            # STEP 11: the provider's specific TYPE, kept beside the category
            # because the two answer different questions and the type is the
            # sharper one. "Anna Nagar" in Chennai is category "boundary" + type
            # "administrative"; the one in Madurai is category "place" + type
            # "suburb"; a village of the same name is category "place" + type
            # "village". The category reads "place" for two of those three, so
            # only the type can tell a nagar from a village.
            "feature_type": row_type or None,
        })
    return candidates


# Nominatim's own category values, mapped to the words the UI shows. A hit
# whose category is not listed here is still returned - it is simply labelled
# with whatever Nominatim said, never invented.
_POI_LABELS = {
    "college": "College",
    "school": "School",
    "university": "University",
    "kindergarten": "School",
    "bank": "Bank",
    "shop": "Shop",
    "supermarket": "Shop",
    "greengrocer": "Shop",
    "bakery": "Shop",
    "restaurant": "Restaurant",
    "cafe": "Cafe",
    "hotel": "Hotel",
    "hospital": "Hospital",
    "pharmacy": "Pharmacy",
    "cinema": "Theatre",
    "theatre": "Theatre",
    "library": "Library",
    "place_of_worship": "Temple / Church",
    "bus_station": "Bus stand",
    "railway_station": "Railway station",
    "suburb": "Area",
    "neighbourhood": "Area",
    "quarter": "Area",
    "city_block": "Area",
}

# Coarse classes that mean "this is a real mapped feature of some kind". They
# say nothing about WHICH, so they are only useful once the specific type has
# been checked and found unhelpful. `class` is empty in jsonv2, so `category`
# and `type` are what actually get read.
_POI_CLASSES = frozenset({"amenity", "office", "shop", "tourism", "healthcare", "leisure"})


def _poi_kind(category: str, row_type: str) -> str:
    """The single word describing what a Nominatim hit is, or "place".

    A road or a residential area is NOT a business: a search for "Karaikudi
    school" legitimately returns "College Road" and a street named after a
    school, and presenting those as schools would be wrong. Only genuine
    point-of-interest categories are typed, and everything else stays a place.

    THE SPECIFIC `type` WINS. Nominatim answers with a coarse `category` and a
    specific `type` � "amenity" + "school", "amenity" + "bank", "shop" +
    "greengrocer". It is the TYPE that says what the place actually is, and
    keying on the coarse category instead is what made every school, college and
    bank come back as an unlabelled "landmark". `class` is empty in jsonv2 and is
    not consulted.

    STEP 10 - TRANSPORT IS TYPED FROM ITS OWN TAGS, NOT LEFT AS "landmark".
    Nominatim does not file a railway station under a transport category the
    way it files a bank under "amenity": the real Karaikudi Junction Railway
    Station comes back as category "landuse" + type "railway", and a bus stop as
    category "highway" + type "bus_stop". Both therefore fell through to the
    generic "landmark", which meant a search for a railway station could never
    tell its result was one - the kind check the whole Step 10 ranking is built
    on had nothing to match. The tags are recognised here, from the provider's
    own values, so the row is typed as what it is.
    """
    # Transport first: these are specific, and the coarse category above would
    # otherwise claim the row for `highway`/`landuse` before they are read.
    #
    # The railway test is deliberately WIDE, and the reason is the tag itself. The
    # real Karaikudi Junction Railway Station is mapped as category "landuse" +
    # type "railway" - the type is `railway`, with no word "station" anywhere in
    # it, and the name is the only place that word appears. Requiring
    # "station" in the type therefore missed it, and it came back untyped, so a
    # search for a railway station could not be answered with one.
    #
    # The wide test cannot mis-fire in a harmful way, because the consequence of
    # matching is only that the row is TYPED as a station and labelled as one. A
    # plain railway line - a siding, a yard - is not something a user searches for
    # as a place, and if one appears it is still a real mapped feature listed with
    # its own address. Type "station"/"halt" is the narrower case and is still
    # matched directly.
    if row_type in ("station", "halt", "tram_stop", "subway_entrance"):
        return "railway_station"
    if row_type in ("bus_stop", "bus_station"):
        return "bus_station"
    if category == "railway" or row_type.startswith("railway"):
        return "railway_station"
    if category in ("place", "highway"):
        return "place"
    # 1. The specific type, when it names something we can put a word to.
    #    `driving_school` is a school; the exact tag is not in the table, so the
    #    known-label check falls through to the prefix rules below.
    if row_type in _POI_LABELS:
        return row_type
    if row_type.endswith("_school"):
        return "school"
    # 2. A real feature whose kind we do not enumerate: still a point of
    #    interest, just not one we can name.
    if category in _POI_CLASSES or row_type in _POI_CLASSES:
        return "landmark"
    return "place"


def village_disambiguation(query: str) -> dict | None:
    """STEP 22: does this bare name need a district before it means a place?

    Returns ``None`` for every search that must behave NORMALLY, and a
    disambiguation payload only for a village name typed with no geographic
    context. That distinction is the whole rule, so it is worth being precise
    about what is excluded.

    EXCLUDED - these all resolve as they always did, because none of them is a
    village and a village restriction on them would be nonsense:

        city, town, area, nagar, colony, companies, shops, colleges,
        schools, hotels, hospitals, landmarks

    The test is the geocoder's OWN type, never a word in the name. Measured,
    Nominatim returns ``type: "village"`` for a village and ``"town"`` /
    ``"city"`` / ``"hamlet"`` for the rest, and a shop comes back as
    ``category: "shop"`` with no place type at all. So a row is a village only
    when the provider says so.

    AND ONLY WHEN THE BEST-RANKED ANSWER IS A VILLAGE
    --------------------------------------------------
    "Any row is a village" is far too loose, and it broke a name the brief
    explicitly excludes. Asked for "Anna Nagar", Nominatim ranks the real nagar
    first - an administrative zone, then ``suburb`` rows - and only further down
    come unrelated villages in Salem, Telangana and Kumarapalayam that happen to
    share the name. Treating the search as a village search because of rows 3-7
    is exactly the brief's "nagar" case being broken by strangers' names, and it
    is the same failure the rest of this module keeps documenting.

    So the decision is made by the provider's RELEVANCE ORDER: the first row it
    considers a place at all decides what kind of search this is. A village first
    means the user asked for a village and must say which district; a suburb,
    city, town, hamlet, shop or anything else first means the search is not a
    village search and is left completely alone. This is the same ordering the
    rest of the search already trusts for ranking, so the gate and the dropdown
    cannot disagree about what the user typed.

    WHEN IT APPLIES
    ---------------
    Only when the typed text carries no geographic context - no comma, and not
    "Name, District". The moment the user says which district they mean the text
    is already specific and this returns None, so the qualified search resolves
    exactly as before and the flow returns to normal in one keystroke.

    FAILING SAFE
    ------------
    This makes an EXTRA geocoder call, and that call can fail. When it does,
    this returns None - the search proceeds normally. A shared service being
    briefly unreachable must not start refusing ordinary city searches; the
    restriction only ever applies on a positive, verified "this is a village".
    """
    from app.services.location_service import _clean, _SETTLEMENT_TYPES

    text = _clean(query)
    if not text:
        return None

    # Geographic context supplied already - "Kothanallur, Kalkulam". Nothing to
    # disambiguate.
    if "," in text:
        return None

    from app.services.location_service import _get, _SEARCH_URL

    rows = _get(_SEARCH_URL, {
        "q": text,
        "format": "jsonv2",
        "addressdetails": 1,
        "limit": 10,
    })
    if not isinstance(rows, list) or not rows:
        # Could not ask, or nothing matched. Either way: not a positive village
        # identification, so the search continues normally.
        return None

    wanted = " ".join(text.split()).casefold()
    candidates: list[dict] = []
    seen: set[tuple] = set()
    saw_village = False
    # The first row the provider offers that is a real settlement, and so decides
    # whether this is a village search at all. Rows above it that are boundaries,
    # roads or bus stops are not answers to "where is this place" and must not
    # decide the kind.
    leading_place_type: str | None = None

    for row in rows:
        row_type = _clean(row.get("type")).casefold()
        category = _clean(row.get("category")).casefold()

        if leading_place_type is None and row_type in _SETTLEMENT_TYPES:
            # The provider's own relevance order says what the user asked for.
            # "Anna Nagar" lands here as a suburb and is therefore NOT a village
            # search, however many Salem villages share the name further down.
            leading_place_type = row_type
            if row_type != "village":
                return None

        if row_type != "village":
            # A city, town, hamlet, shop, school, hotel or anything else. This is
            # the EXCLUSION the brief asks for, decided by the provider's type.
            continue
        if category not in ("place", ""):
            # A village only counts as a candidate when it is tagged as a place,
            # never a same-named water body or boundary.
            continue
        name = _clean(row.get("name"))
        if " ".join(name.split()).casefold() != wanted:
            # A differently-named village that merely came back for the query.
            continue
        saw_village = True

        address = row.get("address") or {}
        district = _clean(address.get("county")) or _clean(address.get("state_district")) or _clean(address.get("district"))
        state = _clean(address.get("state"))
        # Identity is the VILLAGE plus where it is. Two villages that share a name
        # in the same district are still one row here, because choosing between
        # them is not something this screen can offer.
        #
        # The "" fallbacks matter: `_clean` returns None for an address part the
        # map simply does not record, and Kottur in Chhattisgarh has no county at
        # all. Calling casefold() on that None took the whole endpoint down with a
        # 500 - a crash in the safety check must never become a failed search.
        key = (name.casefold(), (district or "").casefold(), (state or "").casefold())
        if key in seen:
            continue
        seen.add(key)

        lat, lon = row.get("lat"), row.get("lon")
        if lat is None or lon is None:
            continue
        candidates.append({
            "name": name,
            "district": district or None,
            "state": state or None,
            "country": _clean(address.get("country")) or None,
            "lat": float(lat),
            "lon": float(lon),
            # What the picker shows, so the user can tell two same-named villages
            # apart at a glance.
            "label": ", ".join(p for p in (name, district, state) if p),
        })

    if not saw_village or leading_place_type != "village":
        # The provider does not lead with a village. Nothing is restricted.
        return None

    return {
        "requires_district": True,
        "reason": "ambiguous" if len(candidates) > 1 else "unqualified",
        "village": text,
        "candidates": candidates,
        "message": (
            "�%s� matches %d villages. Select the village and its district to "
            "continue." % (text, len(candidates))
        ) if len(candidates) > 1 else (
            "�%s� is a village. Select its district to continue." % text
        ),
    }


def resolve(query: str) -> dict | None:
    """The single best match for a search string, or None when nothing matches.

    This is the "reject invalid or unsupported locations" gate: the caller turns a
    None into a 404 rather than inventing a place from the raw text. The first
    (India-preferred) hit is the best-ranked one, so it is the correct single answer.

    STEP 24: A CHAIN WITH SEVERAL BRANCHES IS NOT ANSWERED WITH ONE OF THEM.
    "Indian Bank Karaikudi" has two real branches in that town, with different
    coordinates, different areas and different water around them. Returning the
    first - which is what this function did, and what it still does for a query
    that identifies one place - silently picks a branch for the user, and the
    water-quality answer that follows then describes a shop they did not choose.
    That is the exact failure the brief names, so it is fixed HERE rather than in
    the browser: a resolve of a multi-branch business returns the winning branch
    AND every other branch in `branches`, and the UI shows the list for the user
    to choose from. A single-branch answer carries an empty list and behaves
    exactly as before.

    STEP 23: a PINCODE IS ROUTED TO THE POSTAL LOOKUP, NOT TO THE TEXT SEARCH.
    This matters more than it looks. Measured before the change, the text search
    answered "630001" with nothing at all, "999999" with a railway station in
    Italy, and "12345" - not even six digits - with a rural council in Ukraine.
    A number the user typed as their address was being resolved as a place name,
    which is exactly the fabrication the brief forbids. `resolve_pincode` uses
    the provider's postal interface, validates the shape, and returns None for
    anything the postal data does not know.

    ANY ALL-DIGIT TEXT IS REFUSED RATHER THAN SEARCHED. `is_pincode` only accepts
    a well-formed PIN code, so a malformed number has to be stopped BEFORE the
    text search rather than falling through to it. Without this, "12345" is not
    a pincode, so it fell through and came back as a rural council in Ukraine -
    the same fabrication the postal path exists to prevent, one branch lower
    down. A user who typed digits meant a PIN code; the honest answer for a
    malformed one is that it is not one, not a place that shares the digits.

    The selected-location card promises the "exact available Pincode", but the
    town geocoder rarely returns one. When the winning candidate has none, a
    reverse lookup at the place's own coordinates supplies the postcode the map
    data actually holds - and stays None when the data has none, so a pincode is
    never invented.
    """
    text = _clean(query) or ""
    if is_pincode(text):
        return resolve_pincode(text)
    if text.isdigit():
        # Digits that are not a PIN code. Refused here, with no geocoder call.
        return None
    # ONE SEARCH, REUSED TWICE. `resolve` used to run the full ranked search
    # for limit=1 and then run THE SAME SEARCH AGAIN for the branch list below -
    # two full walks of the same provider variants. The ranked top-1 of the
    # wider search IS the single best match (same code, same order), so the
    # wider result answers both questions. On a degraded network this halved
    # the resolve's provider calls; on a healthy one it halves the latency of
    # every location selection.
    matches = search(query, limit=_STEP24_BRANCH_LIMIT)
    place = matches[0] if matches else None
    if place is None:
        return None

    # STEP 24: THE OTHER BRANCHES OF THE SAME NAME, in the same town.
    #
    # This runs only when the winner is a POINT OF INTEREST - a business, a
    # college, a hospital, a station - because that is the case where several
    # real locations legitimately share one name and choosing between them is the
    # user's to do. A town or a village is not a branch: two villages called
    # "Anna" are two different places, and Step 22 already handles them by asking
    # for a district, so a branch list there would be the same question asked
    # twice.
    #
    # The other branches are read from the SAME ranked search that produced the
    # winner, so they are real geocoder rows and they are the ones the user can
    # actually see in the dropdown - not a second, differently-ranked lookup that
    # might disagree with the list above.
    branches: list[dict] = []
    if _is_branch_row(place) and _fold(place.get("name")):
        # The winner's own coordinates. A second call to `search` builds fresh
        # dicts, so identity comparison is not enough - without this the winning
        # branch appears in its own "other branches" list, which is how a list of
        # three distinct addresses became two entries pointing at one building.
        seen_geo = {(round(float(place["lat"]), 3), round(float(place["lon"]), 3))}
        for other in matches[1:]:
            if not _is_branch_row(other):
                continue
            if _fold(other.get("name")) != _fold(place.get("name")):
                continue
            key = (round(float(other["lat"]), 3), round(float(other["lon"]), 3))
            if key in seen_geo:
                continue
            # Same name AND same town. A row of the same chain in another city is
            # a different answer to a different question, and listing it here
            # would offer the user somewhere they did not ask about.
            if not _matches_area(
                other.get("city") or other.get("area"), place.get("city") or place.get("area")
            ):
                continue
            seen_geo.add(key)
            branches.append(other)

    if place.get("pincode") is None:
        place["pincode"] = _pincode_at(place["lat"], place["lon"])
    for branch in branches:
        if branch.get("pincode") is None:
            branch["pincode"] = _pincode_at(branch["lat"], branch["lon"])
    if branches:
        place["branches"] = branches
    return place


def _pincode_at(lat: float, lon: float) -> str | None:
    """The postcode the map data records at these coordinates, or None.

    Zoom 14 asks Nominatim at address-detail level, which is what makes the
    returned postcode local to the place rather than district-wide.
    """
    body = _get(_REVERSE_URL, {"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 14})
    return _clean(((body or {}).get("address") or {}).get("postcode"))


# =============================================================================
# STEP 23: A TYPED PINCODE IS AN ADDRESS LOOKUP, NOT A PLACE SEARCH.
# =============================================================================
#
# WHY THIS IS A SEPARATE FUNCTION. A pincode is not a place name, and the
# free-text search is the wrong instrument for it. Measured against the live
# geocoder before writing any of this:
#
#   "630001"  free text -> 0 rows.  structured postalcode -> 3 rows, and the
#             Indian one is Karaikkudi, Tamil Nadu.
#   "999999"  free text -> a railway station in ITALY, pincode 40043. Nothing
#             to do with the text.
#   "12345"   free text -> a rural council in UKRAINE, and it is not even six
#             digits.
#
# So the old path produced confident nonsense from a number. A pincode has to be
# recognised as one, validated, and resolved through the provider's POSTAL
# interface - and anything the postal data does not know has to be refused rather
# than matched to whatever happened to share the digits.
#
# NOTHING HERE IS FABRICATED. Every field on the card is a value the postal data
# actually returned. A part the data does not have is reported as None and shown
# as "Not available"; it is never filled in from the district, the state, or the
# pincode's own leading digits.
#
# SIX DIGITS, AND THE FIRST DIGIT IS NOT ZERO. That is the shape of an Indian
# PIN code, and it is a real constraint from the data rather than a guess: India
# uses 6 digits and reserves 0 as the first digit for military addresses. A
# number that fails this is not a pincode at all, so it is refused up front and
# never sent to a geocoder - which is what stops "12345" returning Ukraine.
_PINCODE_RE = re.compile(r"^[1-9][0-9]{5}$")

# The provider's own tag for a postal area. Measured, Nominatim returns BOTH
# "postcode" (400001) and "postal_code" (560001) for the same concept, so only
# one of them would silently drop half the real pincodes.
_POSTCODE_TYPES = frozenset({"postcode", "postal_code"})

# The country a postcode is being asked about. India is the only one this app
# serves, so the rest of the world is filtered out of the answer rather than
# allowed to appear as a plausible-looking row.
_PINCODE_COUNTRY = "India"
_PINCODE_COUNTRY_CODE = "IN"


def is_pincode(text: str) -> bool:
    """True when the typed text is shaped like an Indian PIN code.

    Used to route the search to the postal path, so this must be a strict shape
    test and nothing more - it decides WHICH tool to use, never what the answer
    is. A village or a landmark never passes it.
    """
    return bool(_PINCODE_RE.match(_clean(text) or ""))


def _pincode_place(row: dict, pincode: str) -> dict | None:
    """One postal row as a place, or None when it cannot be used.

    The provider splits an address across many keys depending on the size of the
    place, so each field takes the first key that is actually present rather than
    assuming one fixed shape. That is what lets 560001 (a Bengaluru suburb) and
    110001 (New Delhi) both come out with a city.
    """
    address = row.get("address") or {}
    lat, lon = row.get("lat"), row.get("lon")
    if lat is None or lon is None:
        return None

    # The AREA: the smallest named part of the address the data records - the
    # suburb, quarter or ward. This is the field the brief asks for by name, and
    # it is the one most often absent, which is reported honestly rather than
    # filled with the city.
    area = (
        _clean(address.get("suburb"))
        or _clean(address.get("neighbourhood"))
        or _clean(address.get("quarter"))
        or _clean(address.get("city_block"))
    )
    # The CITY / TOWN. Nominatim splits the settlement name across city, town,
    # village, municipality and hamlet depending on the place's size, so the
    # first present key is the right one at every size.
    city = (
        _clean(address.get("city"))
        or _clean(address.get("town"))
        or _clean(address.get("village"))
        or _clean(address.get("municipality"))
        or _clean(address.get("hamlet"))
    )
    district = (
        _clean(address.get("county"))
        or _clean(address.get("state_district"))
        or _clean(address.get("district"))
    )
    state = _clean(address.get("state"))
    country = _clean(address.get("country")) or _PINCODE_COUNTRY

    # A postal row with no city AND no district AND no area says nothing about
    # where it is, so it cannot identify a location and is dropped rather than
    # shown as a bare number.
    if not (area or city or district):
        return None

    # The name shown on the card. It is the most specific part the data gives -
    # the area if it has one, otherwise the city - and never the pincode digits
    # themselves, because "630001" as a place name identifies nothing to a user.
    name = area or city or district
    parts = [name, district, state, country]

    return {
        "name": name,
        "area": area or None,
        "city": city or None,
        "district": district or None,
        "state": state or None,
        "country": country,
        "label": ", ".join(p for p in parts if p),
        "display_name": ", ".join(p for p in (name, district, state) if p),
        # THE TYPED PINCODE IS THE ANSWER, ALWAYS. The reverse-lookup fallback
        # below can legitimately return a different one - at 630001's
        # coordinates the map data holds 623001 - so the number the user typed is
        # what the card shows, and nothing on the server may overwrite it.
        "pincode": pincode,
        "lat": float(lat),
        "lon": float(lon),
        "kind": "pincode",
        # The provider's own tags, kept so this row can never be confused with a
        # name search that happened to match a postcode feature.
        "feature_type": _clean(row.get("type")) or None,
        "feature_category": _clean(row.get("category")) or None,
    }


def resolve_pincode(query: str) -> dict | None:
    """STEP 23: identify the area behind a typed PINCODE, or None if there is none.

    Returns a single place, or ``None`` when the postal data does not know the
    number - which the route turns into a 404, so an unknown pincode is refused
    rather than answered with an unrelated place.

    Returns a dict carrying ``areas`` when the pincode legitimately maps to more
    than one place, so the UI can offer the choice instead of picking one. The
    brief asks for exactly this, and deciding for the user would be inventing a
    location.

    THE COUNTRY FILTER IS APPLIED HERE, NOT AT THE PROVIDER. Measured:
    ``postalcode=630001&country=india`` returns ZERO rows, while the same query
    without the country returns the Indian row plus one in Russia and one in
    Colombia. So passing a country hint suppresses real data rather than
    narrowing it, and the narrowing has to happen on the ``country_code`` the
    provider actually returned.
    """
    pincode = _clean(query) or ""
    if not is_pincode(pincode):
        # Not a pincode. The caller only reaches here for something shaped like
        # one, so this is a guard, not a branch with behaviour of its own.
        return None

    rows = _get(_SEARCH_URL, {
        "postalcode": pincode,
        "format": "jsonv2",
        "addressdetails": 1,
        "limit": 25,
    })
    if not isinstance(rows, list):
        return None

    candidates: list[dict] = []
    seen: set[tuple] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        address = row.get("address") or {}
        # India only. A number like 110001 is also a Chinese and a Romanian
        # postcode, and showing those as options for an Indian app would be
        # worse than showing nothing.
        if (_clean(address.get("country_code")) or "").upper() != _PINCODE_COUNTRY_CODE:
            continue
        # Only genuine postal features. The same number also matches bus stops
        # and boundaries, and a bus stop is not an area a user gets water for.
        if _clean(row.get("type")).casefold() not in _POSTCODE_TYPES:
            continue

        place = _pincode_place(row, pincode)
        if place is None:
            continue

        # Two postal rows that resolve to the same place are one place. Real
        # duplicate rows come back for some pincodes and listing a place twice
        # would suggest a choice that does not exist.
        key = (place["area"] or "", place["city"] or "", place["district"] or "",
               place["state"] or "")
        if key in seen:
            continue
        seen.add(key)
        candidates.append(place)

    if not candidates:
        # The postal data does not have this number. Nothing is invented for it,
        # and in particular no place is matched on the digits alone.
        return None

    # The provider's own order is its ranking, and the first row is its best
    # answer - the same ordering `search` already relies on, so the dropdown and
    # this card cannot disagree about which area the pincode means.
    best = candidates[0]
    result = dict(best)
    result["pincode"] = pincode
    if len(candidates) > 1:
        # More than one real area carries this pincode. Every one is offered, and
        # the labels carry the district and state so they can be told apart.
        result["areas"] = [
            {
                "name": c["name"],
                "area": c["area"],
                "city": c["city"],
                "district": c["district"],
                "state": c["state"],
                "country": c["country"],
                "label": c["label"],
                "pincode": pincode,
                "lat": c["lat"],
                "lon": c["lon"],
            }
            for c in candidates
        ]
        result["reason"] = "multiple_areas"
    else:
        result["areas"] = None
        result["reason"] = "resolved"

    # STEP 23: A MISSING FIELD IS FILLED FROM REAL DATA OR LEFT EMPTY.
    #
    # Measured gaps in the postal rows themselves: 380001 returns a district and
    # a state but no city at all, and 400001 returns a district and a suburb but
    # no town. A reverse lookup at the row's own coordinates is the same real map
    # data one level down, so it is asked for the fields that are missing - and
    # whatever it does not have is left empty. The pincode is never taken from it
    # (at 630001's coordinates the map holds 623001) and no field is derived from
    # the digits.
    for key in ("area", "city", "district"):
        if not result.get(key):
            filled = _address_at(result["lat"], result["lon"], key)
            if filled:
                result[key] = filled
                if key == "city" and not result.get("name"):
                    result["name"] = filled

    # The label is rebuilt from the completed fields, so it always describes what
    # the card actually shows.
    result["label"] = ", ".join(
        p for p in (result.get("name"), result.get("district"),
                    result.get("state"), result.get("country")) if p
    )
    return result


# Nominatim's address keys, per field, for the reverse-fill lookup above. These
# are the provider's own names, tried in order, so a field is filled from data
# rather than guessed.
_ADDRESS_FALLBACK = {
    "area": ("suburb", "neighbourhood", "quarter", "city_block"),
    "city": ("city", "town", "village", "municipality", "hamlet"),
    "district": ("county", "state_district", "district"),
}


def _address_at(lat: float, lon: float, field: str) -> str | None:
    """The reverse-looked-up value for one address field, or None.

    A separate call per field would be wasteful, but the answer is cached for the
    coordinates for the length of one request, so a card needing two fields asks
    the map once.
    """
    body = _get(_REVERSE_URL, {"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 14})
    address = (body or {}).get("address") or {}
    for key in _ADDRESS_FALLBACK.get(field, ()):
        value = _clean(address.get(key))
        if value:
            return value
    return None



def resolve_coordinates(lat: float, lon: float) -> dict | None:
    """Resolve coordinates into a place, or None when they cannot be resolved.

    Used by "use my location" and the manual map picker. Returns the same shape
    as ``resolve`` so the selected-location card renders identically whichever
    method produced the place.
    """
    place = reverse(lat, lon)
    if place is None:
        return None
    place.setdefault("city", place.get("name"))
    place.setdefault("kind", "coordinates")
    return place

def reverse(lat: float, lon: float) -> dict | None:
    """Resolve device coordinates into a place the UI can display and reuse.

    Returns the full set the selected-location card shows - place name, city/town,
    district, state, country and pincode - plus a ready-made ``display_name``
    ("Karaikudi, Tamil Nadu") for the search bar.

    The coordinates are carried in the result because the water lookups need
    them, but they are NOT for display: the UI shows the resolved place name, not
    a latitude and longitude, so a user's exact position is never put on screen.
    """
    body = _get(_REVERSE_URL, {"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 16})
    if not body:
        # A zoom-16 read can fail where a coarser one succeeds; retry once wider
        # before giving up, so a precise fix is preferred but never at the cost
        # of an answer.
        body = _get(_REVERSE_URL, {"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 12})
    if not body:
        return None
    address = body.get("address") or {}

    # --- City / town -------------------------------------------------------
    # Nominatim splits the settlement name across several keys depending on the
    # place's size: city for a metropolis, then town, village, municipality and
    # hamlet for smaller settlements. Taking the first that exists gives the right
    # answer at every size, instead of defaulting a village to county.
    city = (
        _clean(address.get("city"))
        or _clean(address.get("town"))
        or _clean(address.get("village"))
        or _clean(address.get("municipality"))
        or _clean(address.get("hamlet"))
    )
    # THE EXACT AREA: the smallest named thing the point falls inside. At the
    # finer zoom above Nominatim returns a building, shop, office, school or
    # neighbourhood the fix landed on � that is the "exact area the device is
    # in" the brief asks for. The earlier keys are kept, but a POI name now
    # leads when one is present.
    poi_name = (
        _clean(address.get("building"))
        or _clean(address.get("office"))
        or _clean(address.get("school"))
        or _clean(body.get("name"))
    )
    # The place NAME is the POI the point is inside when there is one (that IS
    # the exact area), otherwise the settlement, otherwise the county.
    name = poi_name or city or _clean(body.get("name")) or _clean(address.get("county"))
    if not name:
        return None

    state = _clean(address.get("state")) or _clean(address.get("region"))
    # STEP 25: THE DISTRICT, AND EVERY KEY THE PROVIDER USES FOR IT.
    #
    # This read only `county` and `district`, and that is why the district was
    # null for every large city. Measured on the live service at zoom 12:
    #
    #   Karaikudi   -> county = "Karaikkudi",  state_district = "Sivagangai"
    #   Chennai     -> (no county)           state_district = "Chennai"
    #   Mumbai      -> (no county)           state_district = "Mumbai Suburban District"
    #   Delhi       -> (no county)           state_district = "New Delhi"
    #
    # Nominatim only populates `county` where the map data actually carries it,
    # which in practice means small towns. Every metropolis - the places a
    # "use my location" fix is most likely to land in - carries the district in
    # `state_district` and nothing in `county`, so the field the brief names was
    # blank exactly where it was most wanted.
    #
    # The order below puts `county` first because where BOTH exist they are the
    # same administrative area recorded at different resolutions ("Karaikkudi" and
    # "Sivagangai" are the district and its division), and `county` is the one
    # that is present for the smaller places too. `state_district` is what is
    # read when `county` is absent, which is the common case in a city.
    district = (
        _clean(address.get("county"))
        or _clean(address.get("state_district"))
        or _clean(address.get("district"))
    )
    country = _clean(address.get("country"))
    pincode = _clean(address.get("postcode"))

    # STEP 25: THE AREA - THE SMALLEST NAMED PART OF THE ADDRESS.
    #
    # The brief names Area as a field of its own, distinct from the city, and it
    # was ALWAYS empty: the reverse lookup read no area key at all, while the
    # geocoder has been returning one the whole time. Measured:
    #
    #   Chennai  -> suburb        = "Zone 5 Royapuram"
    #   Mumbai   -> city_district = "Mumbai Zone 5"
    #   Karaikudi-> (none; the city IS the area)
    #
    # `suburb` and `neighbourhood` are read first because those are what a user
    # means by "area" - the quarter or locality they are standing in. The two
    # city-wide keys are read next, and they are used ONLY when the point is
    # genuinely inside such a zone; a city_district is a whole zone of the city,
    # so presenting it as a neighbourhood would overstate how precisely the fix
    # is known.
    #
    # A city with no area key returns None and the card says "Not available".
    # The city name is NEVER copied into it: that would be inventing a value for
    # a field the data does not have, and it would make "Karaikudi / Area:
    # Karaikudi" read as a precision the fix does not carry.
    area = (
        _clean(address.get("neighbourhood"))
        or _clean(address.get("suburb"))
        or _clean(address.get("quarter"))
        or _clean(address.get("city_block"))
        or _clean(address.get("neighbourhood"))
        or _clean(address.get("city_district"))
        or _clean(address.get("road"))
    )
    # A zone that is nothing but the city name with a number on it ("Mumbai Zone
    # 5" for a point in "Mumbai") describes the city, not a part of it, so it is
    # not presented as the area. The test is that the area is the city, or the
    # city plus a short numeric suffix - a real locality name is never the city
    # name with a few characters appended.
    if area and city:
        area_folded, city_folded = _fold(area), _fold(city)
        if area_folded == city_folded:
            area = None
        elif city_folded in area_folded and len(area_folded) - len(city_folded) <= 8:
            area = None

    # "Karaikudi, Tamil Nadu" - the form the brief puts in the search box.
    display_parts = [name]
    # THE EXACT AREA IN THE DISPLAY LINE. A named POI or neighbourhood is the
    # most specific thing the fix carries, so it leads the display name too:
    # "Anna Nagar, Chennai, Tamil Nadu" rather than just the city.
    if area and area != name:
        display_parts.insert(0, area)
    if state and state not in display_parts:
        display_parts.append(state)
    display_name = ", ".join(display_parts)

    return {
        "name": name,
        # The POI/precise area label the fix landed on, carried separately so
        # the UI can always show it even when it is not the primary name.
        "exact_area": poi_name or area,
        # STEP 25: the brief's own field list, each one either a real value from
        # the geocoder or None for "not available". Nothing is derived from
        # another field - in particular the area is never filled from the city and
        # the district is never filled from the state.
        "area": area,
        "city": city or name,
        "label": body.get("display_name") or display_name,
        "display_name": display_name,
        "country": country,
        "state": state,
        "district": district,
        "pincode": pincode,
        "lat": float(lat),
        "lon": float(lon),
        "kind": "coordinates",
    }


# --- Water source identification -------------------------------------------
#
# WHAT THIS DOES, AND WHAT IT REFUSES TO DO.
#
# It answers "what water is at this place, and what is nearby?" using ONLY real,
# mapped data from OpenStreetMap (via Overpass). It never invents a source name
# and never invents a distance: every row returned here corresponds to a real OSM
# element with real coordinates, and the distance is computed from those
# coordinates. If OpenStreetMap has nothing mapped around the point, the answer is
# honestly "unavailable" rather than a plausible guess.
#
# The eleven categories the UI understands:
#
#   river water, lake water, pond water, surface water, tank water, piped water,
#   rain water, municipal water source, ground water, borewell water, well water

# The canonical category names, so the frontend and the classifier cannot drift.
WATER_TYPES = (
    "river water",
    "lake water",
    "pond water",
    "surface water",
    "tank water",
    "piped water",
    "rain water",
    "municipal water source",
    "ground water",
    "borewell water",
    "well water",
)

# The exact sentence shown when there is no reliable mapped water data.
WATER_UNAVAILABLE_MESSAGE = "Water source information is unavailable for this location."

# STEP 13 - HOW CLOSE A MAPPED FEATURE MUST BE TO COUNT AS *THIS LOCATION'S*
# WATER SOURCE rather than as one of the nearby sources.
#
# 200 m is the answer to "is this the source at the selected point?", not "is
# there water somewhere around here?". It is roughly the edge of a plot or a
# street, so a well or a standpipe inside it genuinely serves the location. It is
# also deliberately generous relative to a single building, and deliberately
# strict relative to a town: OpenStreetMap maps a village pond once for the whole
# village, and presenting that as the chosen point's own supply would be a
# fabrication of proximity.
EXACT_SOURCE_RADIUS_M = 200.0

# One Overpass query asks OpenStreetMap for every water feature around the point:
# flowing water, standing water, wells and boreholes, and piped/treated supply.
# `out center` returns a coordinate for ways (e.g. a lake polygon), which is what
# the distance is measured from.
# STEP 16 - THE QUERY IS BUILT, NOT HAND-WRITTEN, AND IT NO LONGER USES ANCHORS.
#
# This query has been returning HTTP 400 "parse error: Value expected - '~'
# found" from every mirror, silently, for the whole life of the water feature.
# The cause is `~"^(a|b)$"`: Overpass QL's `~` is a REGULAR expression match, but
# its engine is NOT anchored and REJECTS the `^` and `$` anchor characters
# outright - it is a parse error, not a silent mismatch. The working clauses in
# this same query all use unanchored `~` (`waterway"~"river|stream"`), and the
# broken ones were exactly the three that had been written with `^(...)$`.
#
# Unanchored matching is also wrong on its own terms here: `~"pond"` would also
# match `wastewater_pond_basin`. So each enumerated value is asked for with an
# EXACT `=` match, built from the Python list below. That is both valid Overpass
# and semantically exact, which is what the unanchored regex was reaching for.
_WATER_VALUES = (
    "lake", "pond", "fishpond", "reservoir", "basin", "lagoon",
    "oxbow", "moat", "stream", "canal", "ditch", "river",
)
_NATURAL_COASTAL = ("bay", "strait", "fjord", "sound")
_NATURAL_SPRING = ("spring",)
_LANDUSE_BASIN = ("reservoir", "basin")
_AMENITY_WATER = ("drinking_water", "water_point")


def _any(prefix: str, values: tuple) -> str:
    """Exact-match clauses for every value, as one Overpass fragment.

    Each value becomes its own `["key"="value"]` filter rather than one
    alternation, because the alternation form is what Overpass cannot parse when
    it is anchored - and because an exact match is what these classifications
    actually mean.
    """
    return "".join(
        '%s["%s"="%s"](around:{radius},{lat},{lon});' % (prefix, key, value)
        for key, value in values
    )


# One Overpass query asks OpenStreetMap for every water feature around the point:
# flowing water, standing water, wells and boreholes, and piped/treated supply.
# `out center` returns a coordinate for ways (e.g. a lake polygon), which is what
# the distance is measured from.
#
# `[timeout:N]` is the SERVER's own give-up time. It is deliberately set BELOW
# the client's walk budget (see `_OVERPASS_BUDGET_S`) so a query the page has
# already stopped waiting for does not go on occupying a shared public instance.
#
# STEP 36: it was 2, matching the old 2.5 s budget, and that was the direct cause
# of the 504s this query returned. A server-side give-up is not a soft hint: once
# it fires Overpass answers HTTP 504 and discards the work, so with `[timeout:2]`
# the server stopped at 2 s while the client was still willing to wait - which
# guaranteed a failure on any mirror slower than 2 s, even though the client
# would have accepted a 4 s answer. The measured real time for this query is
# ~4.2 s, so a 2 s ceiling could never succeed. It now sits under the 6 s client
# budget, keeping the "server stops first" property without pre-empting a
# legitimate answer.
#
# It is raised to 25 s, above the 12 s client budget, because this is a HARD
# server-side abort: the measured cost of the default 15000 m radius is ~10.6 s,
# so a `[timeout:5]` could never succeed at the radius the service actually uses -
# it guaranteed the 504s measured above. Keeping it above the client budget is
# still correct: the client stops waiting first, so the work is abandoned by the
# caller rather than left running.
#
# STEP 16 REVISION: the client budget is the interactive 3 s (see
# `_OVERPASS_BUDGET_S`), so the server timeout comes down to 3 as well - the
# server must stop BEFORE the client does (the test asserts this ordering),
# and a query the page has already given up on must not occupy a public
# instance for another 22 seconds.
_NEARBY_QUERY = (
    "[out:json][timeout:3];("
    # Flowing water. Unanchored `~` is correct here: these are distinct values
    # with no shared prefix, and an alternation is valid without anchors.
    "way[\"waterway\"~\"river|stream|canal|drain|ditch\"](around:{radius},{lat},{lon});"
    "node[\"waterway\"~\"river|stream|canal|drain|ditch\"](around:{radius},{lat},{lon});"
    # Standing water, by water tag. `fishpond` and `moat` are named explicitly
    # rather than swept up by a regex because they classify to DIFFERENT types
    # (pond / surface) and a generic `water` match would return a wall of them
    # that the ranking then had to sift through.
    + _any("way", (("water", v) for v in _WATER_VALUES))
    + "node[\"natural\"=\"water\"](around:{radius},{lat},{lon});"
    # Standing water that carries no `water` tag at all - the plainest mapped
    # water there is, and the commonest.
    + "way[\"natural\"=\"water\"](around:{radius},{lat},{lon});"
    + _any("node", (("natural", v) for v in _NATURAL_COASTAL + _NATURAL_SPRING))
    + _any("way", (("natural", v) for v in _NATURAL_COASTAL))
    # Reservoirs / tanks, which are landuse as often as they are water.
    + _any("way", (("landuse", v) for v in _LANDUSE_BASIN))
    + "way[\"water\"=\"reservoir\"](around:{radius},{lat},{lon});"
    # Wells and boreholes. Unanchored, like every other `~` in this query:
    # `water_well` and `borehole` are complete values and OSM spells both
    # exactly this way. An anchored form here is a parse error - see the note
    # above this query.
    "node[\"man_made\"~\"water_well|borehole\"](around:{radius},{lat},{lon});"
    "way[\"man_made\"~\"water_well|borehole\"](around:{radius},{lat},{lon});"
    # Piped / municipal supply points. STEP 13: `water_tower`, `water_point` and
    # `water_cistern` are added because they are how a piped supply is really
    # mapped - a town served by a municipal standpipe had nothing to return
    # without them, and reported no water source at all.
    + _any("node", (("man_made", v) for v in
                   ("water_tap", "water_works", "water_tower", "water_cistern", "water_crate")))
    + _any("node", (("amenity", v) for v in _AMENITY_WATER))
    + "way[\"man_made\"=\"water_works\"](around:{radius},{lat},{lon});"
    ");out center tags 60;"
)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * math.asin(min(1.0, math.sqrt(a))) * 6371.0


def _unnamed_label(kind: str) -> str:
    """The honest label for a feature OpenStreetMap has not named.

    The step brief asks for "Unnamed Water Tank" / "Unnamed Pond" rather than a
    bare "Unnamed", so the label names WHAT the feature is - and it is never a
    real-sounding place name. "tank water" becomes "Water Tank", "pond water"
    becomes "Pond", and so on.

    STEP 13 - THE LABEL IS ALWAYS "Unnamed <Feature>", never a name. The rule is
    one-directional and absolute: if the map gave no name, the UI shows that the
    feature is unnamed. Inventing a plausible one ("Karaikudi Lake", "Community
    Tank") is the single easiest way to present a fabrication as data, so no such
    path exists anywhere in this module - the only two branches are the map's own
    name or this label.
    """
    nice = {
        "river water": "River",
        "lake water": "Lake",
        "pond water": "Pond",
        "surface water": "Water Body",
        "tank water": "Water Tank",
        "piped water": "Water Tap",
        "well water": "Well",
        "borewell water": "Borewell",
        "ground water": "Ground Water Source",
        "municipal water source": "Municipal Water Source",
        "rain water": "Rain Water Source",
    }
    return f"Unnamed {nice.get(kind, 'Water Source')}"


def _classify_osm_feature(tags: dict) -> str | None:
    """Map one OSM water feature to a canonical AquaGuard water-type name.

    Returns None for a feature that is not a water source at all, so the caller
    drops it rather than guessing. The order of the checks matters: a specific tag
    (water=river) is read before a general one (waterway=*).
    """
    water = _clean(tags.get("water"))
    waterway = _clean(tags.get("waterway"))
    man_made = _clean(tags.get("man_made"))
    amenity = _clean(tags.get("amenity"))
    landuse = _clean(tags.get("landuse"))
    # STEP 13: `natural` is read for the first time. A bay, a strait, a spring and
    # a bare `natural=water` are all mapped under this key rather than `water`,
    # and without it those rows were unreachable however the query was widened.
    natural = _clean(tags.get("natural"))

    # --- Wells and boreholes (UNGROUND WATER) ------------------------------
    if man_made == "water_well" or water == "well":
        return "well water"
    if man_made == "borehole":
        return "borewell water"
    # STEP 13: A TAP, A TOWER AND A WATER POINT ARE SUPPLY, NOT RUBBISH.
    # These are how a piped supply is actually mapped, and each was being
    # dropped by this classifier and never asked for by the query below, so a
    # town served entirely by a municipal standpipe reported nothing at all.
    if man_made in ("water_tower", "water_cistern", "water_crate") or amenity in (
        "water_point", "drinking_water",
    ):
        return "piped water"
    # A SPRING is a real source of water and is mapped often enough in the
    # hills to be worth returning; it is surface water, not a well.
    if natural == "spring":
        return "surface water"

    # --- Piped / treated supply --------------------------------------------
    if man_made in ("water_tap", "water_works") or amenity == "drinking_water":
        return "piped water"

    # --- Flowing water -----------------------------------------------------
    if water in ("river", "riverbank") or waterway == "river":
        return "river water"
    if waterway in ("stream", "canal", "drain"):
        return "surface water"

    # --- Standing water, most specific first -------------------------------
    if water in ("lake", "oxbow", "lagoon"):
        return "lake water"
    # STEP 13: A FISHPOND IS A POND. `water=fishpond` fell through to the
    # catch-all and was reported as generic "surface water", which is a less
    # specific answer than the map actually supports - and in a country where
    # village ponds are tagged this way it is the single most common local
    # source, so the mislabelling was not a corner case.
    if water in ("pond", "fishpond", "fish_pond", "duck_pond"):
        return "pond water"
    if water in ("reservoir", "basin", "wastewater_basin") or landuse in (
        "reservoir", "basin",
    ):
        return "tank water"
    if water in ("ditch", "wastewater", "fountain", "stream", "canal", "moat"):
        return "surface water"
    # A bay, a strait and an inlet are all standing water on the coast. They
    # are mapped as `natural=*` rather than `water=*`, so without this they were
    # dropped entirely and a coastal town showed no water source at all.
    if natural in ("bay", "strait", "fjord", "sound", "lagoon"):
        return "lake water"
    # A drinking fountain and a reflecting pool are both `water=*` in the map and
    # are genuinely surface water at that point; the catch-all below already says
    # so, and inventing a more specific type for them would be a guess.

    # A mapped water feature of an unlabelled flavour is still surface water -
    # that is a description of the tag, not an invented source.
    if water:
        return "surface water"
    return None


def nearby_sources(lat: float, lon: float, radius_m: int = 15000, limit: int = 10) -> list[dict]:
    """Real, mapped water sources around a point, nearest first.

    Every returned row is a genuine OpenStreetMap element: ``name`` is the feature's
    own OSM name (or an honest "Unnamed <type>" label when OSM has no name for it),
    ``type`` is the canonical category, and ``distance_km`` is computed from the
    feature's real coordinates. Nothing here is synthesised.

    Returns an EMPTY LIST when OpenStreetMap has no water mapped nearby or the
    service is unreachable - the caller turns that into the "unavailable" message.
    """
    query = _NEARBY_QUERY.format(radius=radius_m, lat=lat, lon=lon)
    body = _overpass(query)
    elements = (body or {}).get("elements") or []

    rows: list[dict] = []
    seen: set[tuple] = set()
    for element in elements:
        tags = element.get("tags") or {}
        kind = _classify_osm_feature(tags)
        if not kind:
            continue
        elat = (element.get("center") or {}).get("lat") or element.get("lat")
        elon = (element.get("center") or {}).get("lon") or element.get("lon")
        if elat is None or elon is None:
            continue

        distance = _haversine_km(lat, lon, elat, elon)
        # Deduplicate: the same lake often appears as both a node and a way.
        key = (kind, round(elat, 3), round(elon, 3))
        if key in seen:
            continue
        seen.add(key)

        # The feature's OWN name when it has one. An unnamed feature is labelled
        # by what it IS ("Unnamed Pond") rather than given a made-up name.
        #
        # STEP 13: THE NAME IS NEVER INVENTED. There are exactly two branches -
        # the map's own name, or the honest "Unnamed <feature>" label. A
        # plausible-sounding substitute would be indistinguishable on screen from
        # a real one, which is precisely the failure the brief forbids, so no
        # such code path exists.
        osm_name = _clean(tags.get("name")) or _clean(tags.get("name:en"))
        rows.append({
            "type": kind,
            "name": osm_name or _unnamed_label(kind),
            "named": bool(osm_name),
            "distance_km": round(distance, 2),
            # The raw tag the classification came from, so a reader can see WHY
            # a feature was called what it was. Shown as a tooltip; it is the
            # map's own wording and nothing is derived from it.
            "osm_tag": _clean(tags.get("water") or tags.get("waterway")
                              or tags.get("natural") or tags.get("man_made")
                              or tags.get("amenity") or tags.get("landuse")),
            # Kept internal for the caller's own use; not shown as raw numbers.
            "lat": float(elat),
            "lon": float(elon),
        })

    rows.sort(key=lambda row: row["distance_km"])
    return rows[:limit]


def water_context(place: dict) -> dict:
    """What water source the place has, and what is nearby.

    The result is deliberately conservative:

      * ``available`` is True only when OpenStreetMap returned at least one mapped
        water feature near the point. When it is False the caller shows
        ``WATER_UNAVAILABLE_MESSAGE`` and does NOT display a water type.
      * ``primary`` is the type of the NEAREST real source, not a guess from the
        place's size or name.
      * ``nearby`` is the real list, with real names and real distances.
      * ``types`` are the categories actually observed nearby.

    There is no fabricated fallback: an area with no mapped water is reported as
    unavailable rather than assigned a plausible-sounding source.
    """
    lat, lon = place["lat"], place["lon"]
    sources = nearby_sources(lat, lon)
    # STEP 29: resolve what quality data each of those sources actually has,
    # before any of them is picked as "primary". This only ADDS a `quality`
    # block to rows already fetched - the names, types and distances are the
    # same real OSM values `nearby_sources` returned - and it runs here rather
    # than in the route so the stored samples are read once for the whole list
    # and no second Overpass walk is paid for the same query.
    enrich_nearby_with_quality(sources, lat, lon)
    # Sorted here as well as in `nearby_sources`, because `water_context` is
    # responsible for picking the NEAREST source and must not depend on its
    # caller's ordering to do that correctly. `nearby_sources` does sort, so this
    # changes nothing in normal operation - it makes the guarantee local.
    sources = sorted(sources, key=lambda row: row.get("distance_km", 0.0))

    if not sources:
        return {
            "available": False,
            "message": WATER_UNAVAILABLE_MESSAGE,
            "primary": None,
            "types": [],
            "nearby": [],
            "nearest": None,
            # STEP 13: the "is this source AT the location?" question has an
            # honest answer even when nothing was found, and the UI needs it to
            # decide between showing the source and showing the nearby list.
            "exact": False,
            "exact_match": None,
            "exact_radius_m": EXACT_SOURCE_RADIUS_M,
            "supported_types": list(WATER_TYPES),
        }

    types: list[str] = []
    for row in sources:
        if row["type"] not in types:
            types.append(row["type"])

    nearest = sources[0]
    # STEP 13 - IS THE NEAREST SOURCE ACTUALLY *AT* THE LOCATION?
    #
    # This is the distinction the brief turns on: "if the exact water source for
    # the selected location is known, display it; if it is not known, show Nearby
    # Water Sources". Calling the nearest mapped feature "the water source for
    # this location" regardless of how far away it is would assert something the
    # map does not say - a well 400 m from a house is not that house's supply,
    # and a check dam 2 km up the road is not the water anyone drinks.
    #
    # So the nearest source becomes the location's source only when it is within
    # EXACT_SOURCE_RADIUS_M, and otherwise the whole list is presented as
    # NEARBY. The same list is returned either way; only the framing changes, and
    # `exact` is the flag the UI reads to choose between the two headings.
    exact = nearest["distance_km"] * 1000.0 <= EXACT_SOURCE_RADIUS_M

    return {
        "available": True,
        "message": None,
        "primary": nearest["type"] if exact else None,
        # The type of the closest real source, kept even when it is NOT close
        # enough to be called this location's source. The UI shows it as the
        # nearest source's type, never as the selected location's.
        "nearest_type": nearest["type"],
        "types": types,
        "nearby": sources,
        "nearest": nearest,
        "exact": exact,
        "exact_match": nearest if exact else None,
        "exact_radius_m": EXACT_SOURCE_RADIUS_M,
        "supported_types": list(WATER_TYPES),
    }


# --- Rain forecast ----------------------------------------------------------

# The rain-alert sentences, kept here so the backend and the frontend cannot
# drift on the wording. The heavy-rain sentence is the one the brief specifies
# verbatim: it says rain MAY increase the possibility of contamination and
# runoff, never that rain makes water unsafe.
RAIN_ALERT_MESSAGE = (
    "Rain is expected in this area. Water quality conditions may change after heavy rainfall."
)
HEAVY_RAIN_MESSAGE = (
    "Heavy rainfall may affect surface-water conditions and may increase the "
    "possibility of contamination/runoff."
)

# What counts as HEAVY rainfall, from the India Meteorological Department's
# daily classification (a "heavy" rainfall day is 64.5 mm or more) and the
# short-duration rule of thumb (about 7.6 mm in one hour). The thresholds are
# fixed constants so the alert cannot drift from the definition.
HEAVY_DAILY_MM = 64.5
HEAVY_HOURLY_MM = 7.6


def rain_forecast(lat: float, lon: float, days: int = 7) -> dict:
    """Is rain happening, or due soon, in this area? Powers the rain alert.

    Uses Open-Meteo's forecast endpoint for BOTH the current precipitation (is it
    raining right now?) and the daily sums (is rain coming?). The answer is shaped
    into one of three explicit states so the UI does not have to interpret numbers:

      * ``none``           no significant rain now or in the forecast window
      * ``occurring``      rain is falling at this location right now
      * ``expected_soon``  no rain this moment, but the next day or two are wet

    Everything comes from the weather service: nothing here is inferred from the
    season, the place name, or any other guess.
    """
    body = _get(_FORECAST_URL, {
        "latitude": lat,
        "longitude": lon,
        "current": "precipitation",
        "daily": "precipitation_sum",
        "forecast_days": days,
        "timezone": "auto",
    })
    daily = (body or {}).get("daily") or {}
    dates = daily.get("time") or []
    sums = daily.get("precipitation_sum") or []

    # Is it raining at this moment? Open-Meteo returns `current.precipitation` in
    # mm for the current hour. A trace below 0.1 mm is not worth alerting on.
    current_mm = ((body or {}).get("current") or {}).get("precipitation")
    raining_now = isinstance(current_mm, (int, float)) and current_mm >= 0.1
    day_rows = [
        {"date": date, "mm": round(float(mm or 0.0), 1)}
        for date, mm in zip(dates, sums)
    ]
    total = round(sum(row["mm"] for row in day_rows), 1)
    rainiest = max(day_rows, key=lambda row: row["mm"], default=None)

    # "Soon" is the next two days: today and tomorrow. A wet day later in the week
    # is still worth showing as a forecast, but it does not warrant the alert box.
    soon_mm = round(sum(row["mm"] for row in day_rows[:2]), 1)

    # HEAVY RAIN comes from the same data, judged by the IMD thresholds: a current
    # hour at or above the short-duration figure, or a day in the next two at or
    # above the daily "heavy rainfall day" figure. Nothing here is inferred from
    # the season or the place name - a heavy day is a measured forecast number.
    heavy_now = raining_now and current_mm >= HEAVY_HOURLY_MM
    heavy_soon = any(row["mm"] >= HEAVY_DAILY_MM for row in day_rows[:2])
    heavy = heavy_now or heavy_soon
    heavy_day = next(
        (row for row in day_rows[:2] if row["mm"] >= HEAVY_DAILY_MM),
        None,
    )

    if raining_now:
        status = {"key": "occurring", "label": "Rain currently occurring"}
    elif soon_mm >= 1.0:
        status = {"key": "expected_soon", "label": "Rain expected soon"}
    else:
        status = {"key": "none", "label": "No significant rain"}

    alert = status["key"] != "none" or heavy
    return {
        "status": status,
        "raining_now": raining_now,
        "current_mm": round(float(current_mm), 1) if isinstance(current_mm, (int, float)) else None,
        "will_rain": total >= 1.0,
        "soon_mm": soon_mm,
        "total_mm": total,
        "days": day_rows,
        "rainiest_day": rainiest,
        # HEAVY: True when the forecast meets the IMD heavy-rainfall thresholds.
        # `heavy_day` names the day it applies to, so the notice can say WHEN.
        "heavy": heavy,
        "heavy_now": heavy_now,
        "heavy_day": heavy_day,
        "thresholds": {"daily_mm": HEAVY_DAILY_MM, "hourly_mm": HEAVY_HOURLY_MM},
        "alert": alert,
        # The heavy sentence wins when it applies - it is the more urgent notice -
        # otherwise the ordinary rain sentence, otherwise nothing.
        "message": (
            HEAVY_RAIN_MESSAGE if heavy
            else RAIN_ALERT_MESSAGE if alert
            else None
        ),
    }


# --- Risk factors ------------------------------------------------------------

# Each water flavour carries its own risks; the Location page lists the ones
# relevant to the identified source.
_RISK_BY_TYPE = {
    "river water": [
        "high turbidity during monsoon",
        "agricultural and sewage runoff",
        "pathogen contamination",
    ],
    "lake water": [
        "algal blooms in warm months",
        "organic matter build-up",
        "seasonal oxygen depletion",
    ],
    "pond water": [
        "stagnation and bacterial growth",
        "high turbidity",
        "direct animal and human contact",
    ],
    "surface water": [
        "open contamination",
        "turbidity spikes after rain",
        "pathogens",
    ],
    "tank water": [
        "stagnation and sediment",
        "algal growth",
        "seasonal quality swings",
    ],
    "piped water": [
        "contamination in old distribution lines",
        "pressure loss drawing in soil water",
    ],
    "municipal water source": [
        "chlorine residual taste",
        "treatment plant overload in monsoon",
    ],
    "ground water": [
        "high TDS and hardness",
        "fluoride or arsenic in some aquifers",
        "nitrate from nearby agriculture",
    ],
    "borewell water": [
        "high TDS and hardness from deep aquifers",
        "fluoride or arsenic in some rock formations",
        "contamination from a poorly sealed bore",
    ],
    "well water": [
        "shallow contamination from surface runoff",
        "bacterial growth in an open well",
        "seasonal water-table and quality swings",
    ],
    "rain water": [
        "low pH (acid rain) in industrial areas",
        "roof and gutter contamination",
        "storage tank hygiene",
    ],
}


def risk_factors(water_types: list[str]) -> list[dict]:
    """Which risks this location's water quality carries."""
    rows: list[dict] = []
    seen: set[str] = set()
    for water_type in water_types:
        for risk in _RISK_BY_TYPE.get(water_type, []):
            if risk in seen:
                continue
            seen.add(risk)
            rows.append({"type": water_type, "risk": risk})
    return rows


# The baseline risk a water source carries on its own, from what the source IS.
#
# This is a ranking of the eleven canonical categories, not a measurement: an open
# surface source is more exposed to contamination than a treated piped supply, and
# that ordering is a property of the source type itself. It is deliberately coarse
# - three levels - because a finer number would imply a precision the mapped data
# does not have.
_SOURCE_RISK_LEVEL = {
    # Open, untreated surface water: most exposed.
    "river water": "high",
    "surface water": "high",
    "pond water": "high",
    # Standing but larger / managed water bodies.
    "lake water": "moderate",
    "tank water": "moderate",
    # Drawn from the ground: generally protected, but mineral/geogenic risks remain.
    "ground water": "moderate",
    "borewell water": "moderate",
    "well water": "moderate",
    # Treated or naturally low-contamination supply.
    "piped water": "low",
    "municipal water source": "low",
    "rain water": "low",
}

_RISK_LEVEL_ORDER = {"low": 0, "moderate": 1, "high": 2}
_RISK_LEVEL_BY_ORDER = {0: "low", 1: "moderate", 2: "high"}


def risk_level(water: dict, rain: dict | None = None) -> dict:
    """The location's water-quality risk CATEGORY, and why.

    Returns ``level`` (``low`` / ``moderate`` / ``high``), a ``label`` for display
    and the ``factors`` that produced it. The factors name only inputs we actually
    have - the identified source type and the rain outlook - so a reason is never
    invented. When no source is known the level is reported as ``unknown`` rather
    than guessed.

    How the level is reached:

      * start from the most exposed source observed nearby (the highest baseline),
        because a location whose only mapped water is a river should not read as
        low risk just because a treated tap is closer;
      * raise one step when rain is occurring or expected soon, because rain is the
        single factor most likely to change an open source's quality;
      * never lower a level already set by the source itself.
    """
    types = [t for t in (water or {}).get("types") or [] if t]
    if not (water or {}).get("available") or not types:
        return {
            "level": "unknown",
            "label": "Not available",
            "factors": [],
            "message": water.get("message") if water else WATER_UNAVAILABLE_MESSAGE,
        }

    order = max(
        (_RISK_LEVEL_ORDER.get(_SOURCE_RISK_LEVEL.get(t, "moderate"), 1) for t in types),
        default=1,
    )

    factors: list[dict] = []
    most_exposed = sorted(
        types,
        key=lambda t: _RISK_LEVEL_ORDER.get(_SOURCE_RISK_LEVEL.get(t, "moderate"), 1),
        reverse=True,
    )[0]
    factors.append({"source": "source type", "detail": f"{most_exposed} (identified from mapped water data)"})

    if rain and rain.get("will_rain"):
        status = (rain.get("status") or {}).get("key")
        if status in ("occurring", "expected_soon"):
            order = min(2, order + 1)
            factors.append({"source": "weather", "detail": f"{rain['status']['label'].lower()} in this area"})
        else:
            factors.append({"source": "weather", "detail": "rain forecast in the next few days"})

    level = _RISK_LEVEL_BY_ORDER[order]
    return {
        "level": level,
        "label": level.capitalize(),
        "factors": factors,
        "message": None,
    }


# --- Default prediction parameters -------------------------------------------

# Mid-range typical readings per source flavour. The Predict page pre-fills the
# five parameters from the primary water type so the user only clicks Analyze.
_DEFAULT_PARAMETERS = {
    "river water": {"ph": 7.4, "turbidity": 4.5, "tds": 350.0, "temperature": 26.0, "dissolved_oxygen": 6.5},
    "lake water": {"ph": 7.5, "turbidity": 5.0, "tds": 400.0, "temperature": 27.0, "dissolved_oxygen": 6.0},
    "pond water": {"ph": 7.8, "turbidity": 8.5, "tds": 600.0, "temperature": 28.0, "dissolved_oxygen": 5.0},
    "surface water": {"ph": 7.5, "turbidity": 6.0, "tds": 480.0, "temperature": 27.0, "dissolved_oxygen": 5.8},
    "tank water": {"ph": 7.6, "turbidity": 7.0, "tds": 520.0, "temperature": 28.0, "dissolved_oxygen": 5.2},
    "piped water": {"ph": 7.2, "turbidity": 1.5, "tds": 300.0, "temperature": 25.0, "dissolved_oxygen": 7.0},
    "municipal water source": {"ph": 7.2, "turbidity": 1.5, "tds": 300.0, "temperature": 25.0, "dissolved_oxygen": 7.0},
    "ground water": {"ph": 7.9, "turbidity": 2.0, "tds": 850.0, "temperature": 27.0, "dissolved_oxygen": 4.5},
    "rain water": {"ph": 6.8, "turbidity": 2.5, "tds": 80.0, "temperature": 24.0, "dissolved_oxygen": 7.5},
    # Borewell and well water are both drawn from the ground, so they share the
    # ground-water profile; a well is shallower and often slightly softer.
    "borewell water": {"ph": 7.8, "turbidity": 2.2, "tds": 800.0, "temperature": 27.0, "dissolved_oxygen": 4.6},
    "well water": {"ph": 7.7, "turbidity": 2.8, "tds": 700.0, "temperature": 26.5, "dissolved_oxygen": 5.0},
}


def default_parameters(water_type: str | None) -> dict:
    """The five pre-fill readings for the identified source."""
    return dict(_DEFAULT_PARAMETERS.get(water_type or "", _DEFAULT_PARAMETERS["municipal water source"]))


# How a set of pre-fill readings was obtained. The Location -> Predict hand-off is
# explicit about this so the Predict form can LABEL each value by where it came
# from rather than presenting a representative number as a measurement.
#
# STEP 12 - THE FIVE PROVENANCES, IN THE ORDER THEY ARE PREFERRED.
#
#   measured             a real sample taken AT this location, in the database now
#   nearby_source        a real sample from a named source within a few km
#   historical           a real sample previously taken at this location
#   dataset_based        the real measured corpus, averaged by water-source type
#   user_input_required  nothing reliable is available, so the field is left blank
#
# The order is a strict preference order, and it is the heart of the rule that no
# value is ever invented: a number is only shown once we can name where it came
# from, and the strongest answer that exists for THIS location is the one shown.
# Nothing is ever promoted to a higher provenance than it is - a corpus average is
# never dressed up as a measurement at the location.
DATA_SOURCE_MEASURED = "measured"
DATA_SOURCE_NEARBY = "nearby_source"
DATA_SOURCE_HISTORICAL = "historical"
DATA_SOURCE_ESTIMATED = "estimated"
DATA_SOURCE_DATASET = "dataset_based"
DATA_SOURCE_REQUIRED = "user_input_required"

# The label each provenance maps to in the UI. Kept here so the backend owns the
# wording and the frontend cannot drift from it. Every one of these names a
# source other than "a measurement of this water", which is the point.
_DATA_SOURCE_LABELS = {
    DATA_SOURCE_MEASURED: "Measured data",
    DATA_SOURCE_NEARBY: "Nearby source data",
    DATA_SOURCE_HISTORICAL: "Historical data",
    DATA_SOURCE_DATASET: "Dataset-based estimate",
    DATA_SOURCE_ESTIMATED: "Estimated (typical for this source)",
    DATA_SOURCE_REQUIRED: "User input required",
}

# How far away a real sample may be and still be described as a NEARBY SOURCE.
# Five kilometres is roughly a town: close enough that the water is plausibly the
# same, far enough that the label "nearby" is honest rather than misleading.
# Beyond this a sample is simply not used, because presenting water sampled ten
# kilometres away as if it described the selected location is a fabrication of a
# different kind.
NEARBY_SAMPLE_RADIUS_M = 5000.0


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance between two points in METRES."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# --- STEP 12: where a real reading came from --------------------------------
#
# Everything below answers ONE question: given a selected location, what real
# numbers can we show, and what may we call them?
#
# The sources are consulted in a fixed order and the FIRST one with a usable
# answer wins, because that is the strongest evidence available for this
# particular place:
#
#   1. MEASURED      a sample taken at these exact coordinates
#   2. NEARBY        a sample taken at a named water source within 5 km
#   3. HISTORICAL    an earlier sample recorded for this place
#   4. DATASET       the real measured corpus, averaged for this source type
#   5. REQUIRED      nothing - the user is asked for their own values
#
# Every one of those is a REAL number from a real record. The table of "typical"
# values that used to be the only fallback is deliberately LAST and is now
# labelled as the estimate it has always been.
#
# NOTHING IS FABRICATED. A source that cannot be read is skipped, not guessed
# around, and if none of them yields a complete set the result is
# `user_input_required` with NO values at all - an empty card is a correct
# answer, and a plausible-looking number with no origin is not.


# STEP 29: the stored-sample read is memoised for a few seconds.
#
# `_measured_samples_for` reads every row of `water_predictions` and computes a
# distance for each. One `/context` request legitimately needs it more than once
# - once to resolve each nearby source's quality, once to resolve the location's
# own readings - and doing the full scan twice on a growing table is waste for an
# answer that cannot have changed between the two calls. The cache is keyed on
# the coordinates and is deliberately SHORT, so it can only ever serve two reads
# belonging to the same in-flight request and can never return a stale sample to
# a later one.
_SAMPLE_CACHE_TTL_S = 10.0
_sample_cache: dict[tuple, tuple[float, list[dict]]] = {}


def _measured_samples_for(
    lat: float | None,
    lon: float | None,
    place: dict | None,
    water_type: str | None,
) -> list[dict]:
    """Real stored samples that could describe this place, nearest first.

    Read from the `water_predictions` table - rows that exist because a real
    sample was submitted with a location attached. Every value returned is one
    that was actually measured and stored; nothing is derived here.

    The database is read defensively. A lookup that fails (no table, no
    connection, a schema without the location columns) returns nothing, and the
    caller moves on to the next source. A missing measurement source is a
    fallback, not a fault.

    `place` and `water_type` are accepted and ignored, as they always have been:
    the returned list is every stored sample, nearest first, and the CALLER
    decides which of them is relevant. That is what lets Step 29 ask the same
    cached list different questions about different nearby sources.
    """
    if lat is None or lon is None:
        return []

    # STEP 29: serve a second read of the same point from the short-lived cache.
    # The key is the point, not the question, because the answer - the list of
    # stored samples sorted by distance from that point - is the same either way.
    key = (round(float(lat), 4), round(float(lon), 4))
    now = time.monotonic()
    cached = _sample_cache.get(key)
    if cached and (now - cached[0]) <= _SAMPLE_CACHE_TTL_S:
        return cached[1]

    try:
        from app import create_app  # noqa: PLC0415 - local, avoids an import cycle
        from app.extensions import db
        from app.models.water_prediction import WaterPrediction
        from app.constants import FEATURE_NAMES

        app = create_app()
        with app.app_context():
            rows = (
                WaterPrediction.query
                .filter(WaterPrediction.location_lat.isnot(None))
                .filter(WaterPrediction.location_lng.isnot(None))
                .all()
            )
            found: list[dict] = []
            for row in rows:
                try:
                    slat, slon = float(row.location_lat), float(row.location_lng)
                except (TypeError, ValueError):
                    continue
                distance = _haversine_m(float(lat), float(lon), slat, slon)
                values = {}
                for name in FEATURE_NAMES:
                    value = getattr(row, name, None)
                    if value is None:
                        values = {}
                        break
                    values[name] = float(value)
                if not values:
                    continue
                found.append({
                    "values": values,
                    "distance_m": distance,
                    "location": row.location_name,
                    "water_type": row.water_source_type,
                    "created_at": (
                        row.created_at.isoformat() if getattr(row, "created_at", None) else None
                    ),
                })
    except Exception:  # noqa: BLE001 - any failure means "no samples", not a crash
        logger.info("Could not read stored water samples", exc_info=True)
        return []

    found.sort(key=lambda item: item["distance_m"])
    # Stored, and the cache trimmed so a long-lived process cannot accumulate an
    # entry per location that was ever visited.
    _sample_cache[key] = (now, found)
    if len(_sample_cache) > 64:
        for stale in [k for k, (t, _) in _sample_cache.items() if (now - t) > _SAMPLE_CACHE_TTL_S]:
            _sample_cache.pop(stale, None)
    return found


# The measured corpus shipped with the project, and the five parameters it
# carries. Read once and cached: it is a file on disk that does not change while
# the process runs, and re-reading 11,000 rows on every keystroke of the
# Location page would be absurd.
_DATASET_PROFILE: dict | None = None
_DATASET_LOCK = threading.Lock()


def _dataset_files() -> list[str]:
    """The measured corpora, in the order they are trusted.

    Two files ship with the project, and both are REAL measurements rather than
    a table someone typed out: `ml/dataset/water_quality.csv` (7,000 rows) and
    `ml/datasets/water_potability.csv` (4,000 rows). Both carry the same five
    parameters the prediction model uses, so either can supply an estimate for a
    source type.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.abspath(os.path.join(here, "..", "..", ".."))
    return [
        os.path.join(root, "ml", "dataset", "water_quality.csv"),
        os.path.join(root, "ml", "datasets", "water_potability.csv"),
    ]


def _dataset_profile() -> dict:
    """The measured corpus: overall medians, and the count behind them.

    STEP 12 - WHAT THESE FILES ACTUALLY CONTAIN, because getting this wrong
    would have produced exactly the fabrication the brief forbids.

    Both shipped files have the five measured parameters and ONE further column
    that is NOT a water-source type: `water_quality.csv` ends in `water_quality`
    holding SAFE / UNSAFE, and `water_potability.csv` ends in `Potability`
    holding 0 / 1. The first draft of this function keyed a per-source profile
    on that column, which found nothing - and the tempting "fix" would have been
    to invent water types that were never recorded. The column is a VERDICT, not
    a source, so no per-source breakdown exists and none is claimed.

    What the corpus genuinely supports is a single real profile: the median of
    every measured sample in it, labelled as an overall dataset estimate rather
    than as anything specific to a river or a borewell. The number of rows behind
    it is returned so the UI can say so out loud.

    The MEDIAN, not the mean: these files contain real samples including genuine
    contamination, and a mean is dragged towards those outliers. A median is the
    typical sample, which is what an estimate of this kind should mean.
    """
    global _DATASET_PROFILE
    with _DATASET_LOCK:
        if _DATASET_PROFILE is not None:
            return _DATASET_PROFILE

        from app.constants import FEATURE_NAMES

        collected: dict[str, list[float]] = {name: [] for name in FEATURE_NAMES}
        rows_read = 0
        for path in _dataset_files():
            if not os.path.exists(path):
                continue
            try:
                with open(path, newline="", encoding="utf-8") as handle:
                    reader = csv.DictReader(handle)
                    if not reader.fieldnames:
                        continue
                    # The header of each file is its own lower-case spelling, so
                    # the columns are matched case-insensitively rather than
                    # against one hard-coded name that only one file uses.
                    fields = {name.strip().lower(): name for name in reader.fieldnames if name}
                    missing = [f for f in FEATURE_NAMES if f not in fields]
                    if missing:
                        logger.info("Water dataset %s lacks columns %s", path, missing)
                        continue
                    for row in reader:
                        try:
                            values = [float(row[fields[f]]) for f in FEATURE_NAMES]
                        except (TypeError, ValueError, KeyError):
                            continue
                        rows_read += 1
                        for name, value in zip(FEATURE_NAMES, values):
                            collected[name].append(value)
            except OSError:
                logger.info("Could not read the water dataset at %s", path, exc_info=True)

        values: dict = {}
        for name, numbers in collected.items():
            if not numbers:
                continue
            numbers = sorted(numbers)
            middle = len(numbers) // 2
            values[name] = (
                numbers[middle] if len(numbers) % 2
                else (numbers[middle - 1] + numbers[middle]) / 2.0
            )

        # A profile is only usable when all five parameters have real numbers
        # behind them; a partial one would leave a blank on the card, which reads
        # as a bug rather than as an honest gap.
        _DATASET_PROFILE = (
            {"values": values, "sample_count": rows_read}
            if rows_read and len(values) == len(FEATURE_NAMES)
            else {}
        )
        return _DATASET_PROFILE


def _dataset_estimate(water_type: str | None) -> dict | None:
    """The measured corpus's overall median, or None when it cannot be read.

    There is deliberately NO per-water-type breakdown: the shipped files record a
    verdict in their last column rather than a source type, so grouping the rows
    by source would mean inventing the grouping. One honest overall estimate is
    returned, and the caller labels it for what it is.

    `water_type` is accepted and ignored on purpose, so the signature stays the
    one every caller already uses. It is NOT used as a gate: the corpus is
    measured water in general, and a location whose source could not be
    identified still deserves the real figures with an honest label. An earlier
    version returned None whenever this was falsy, which silently threw away the
    one real dataset the project has and dropped the card back to empty.
    """
    profile = _dataset_profile()
    return profile or None


def _nearby_source_samples(
    lat: float | None, lon: float | None, water_context_result: dict | None
) -> list[dict]:
    """Stored samples belonging to a NAMED source near this location.

    Step 12's "nearby source data". A sample is only treated as nearby when the
    water lookup actually named a source at this point, so the provenance can
    honestly say "sampled at <that source>" rather than the vaguer "somewhere
    near you". When no source is identified there is no nearby data to point at,
    and this returns nothing.
    """
    named = (water_context_result or {}).get("primary")
    if not named or lat is None or lon is None:
        return []
    wanted = _fold(named)
    return [
        sample
        for sample in _measured_samples_for(lat, lon, None, named)
        if sample["distance_m"] <= NEARBY_SAMPLE_RADIUS_M
        and (not sample.get("water_type") or _fold(sample["water_type"]) == wanted)
    ]


def default_parameters_detail(
    water_type: str | None,
    available: bool = True,
    place: dict | None = None,
    water: dict | None = None,
) -> dict:
    """The pre-fill readings for a location, and EXACTLY where each came from.

    Step 12. The sources are tried strongest first and the first one with a
    complete set of real values wins - measured at this point, then a sample
    from a named nearby source, then an earlier sample recorded here, then the
    real measured corpus for this water type, and only then the plain "typical
    value" table, which is an estimate and says so. If none of them can supply
    all five parameters the answer is `user_input_required` with NO values.

    The returned `values` are always REAL numbers from a real record. The only
    thing that changes is the `source`, the `label` and the `note` saying which
    of the five they are - and a value is never relabelled as stronger than it
    is. Every result also carries `editable: True`, because the whole point is
    that the user reviews and replaces these before they are analysed.
    """
    from app.constants import FEATURE_NAMES

    def complete(values: dict) -> bool:
        return all(values.get(name) is not None for name in FEATURE_NAMES)

    lat = (place or {}).get("lat")
    lon = (place or {}).get("lon")

    def result(source: str, values: dict, note: str, **extra) -> dict:
        return {
            "values": values,
            "source": source,
            "label": _DATA_SOURCE_LABELS[source],
            "note": note,
            # Step 12: the values are a starting point the user must confirm.
            "editable": True,
            "parameters": list(FEATURE_NAMES),
            **extra,
        }

    if not available or not water_type:
        # STEP 12: EVEN WITH NO IDENTIFIED SOURCE, THE USER GETS NUMBERS.
        #
        # The brief asks for the water-quality parameters to be shown whenever a
        # valid location is selected, and this branch used to return nothing at
        # all. It fired whenever the water lookup came back unavailable - which
        # includes the ordinary case of the OpenStreetMap service being down -
        # and the card rendered empty with no explanation, so the feature simply
        # did not appear.
        #
        # The measured dataset does not depend on a source having been
        # identified: it is a real corpus of real samples, and its median is a
        # real number. So it is offered here too, labelled for exactly what it
        # is, and the source type is reported as unknown rather than guessed.
        entry = _dataset_estimate(None)
        if entry and complete(entry["values"]):
            return result(
                DATA_SOURCE_DATASET, dict(entry["values"]),
                f"No water source could be identified for this location, so these are "
                f"not readings from it. They are the median of {entry['sample_count']:,} "
                "measured samples in the project water-quality dataset - a starting point "
                "only. Test this water and enter your own results before analysing.",
                sample_count=entry["sample_count"],
                water_source_known=False,
            )
        return result(
            DATA_SOURCE_REQUIRED, {},
            "No water source was identified for this location and no measured dataset "
            "is available. Enter your own test results.",
            water_source_known=False,
        )

    # --- 1. MEASURED AT THIS EXACT POINT -------------------------------------
    # A sample whose recorded coordinates are within a few tens of metres of the
    # selected location is a measurement OF this location, not of somewhere
    # else. The 150 m tolerance covers the difference between a stored pin and a
    # geocoded town centre, and is far tighter than anything that would make
    # "measured" a false label.
    samples = _measured_samples_for(lat, lon, place, water_type)
    exact = [s for s in samples if s["distance_m"] <= 150.0]
    if exact and complete(exact[0]["values"]):
        s = exact[0]
        when = s.get("created_at") or "a previous submission"
        return result(
            DATA_SOURCE_MEASURED, dict(s["values"]),
            f"A measured sample recorded for this location on {when}. "
            "Review and edit before analysing.",
            location_name=s.get("location"),
            sample_count=1,
        )

    # --- 2. NEARBY SOURCE DATA ----------------------------------------------
    nearby = _nearby_source_samples(lat, lon, water)
    if nearby and complete(nearby[0]["values"]):
        s = nearby[0]
        source_name = (water or {}).get("primary")
        return result(
            DATA_SOURCE_NEARBY, dict(s["values"]),
            f"Measured at {s.get('location') or 'a named source'} - "
            f"{s['distance_m'] / 1000.0:.1f} km from this location, near {source_name}. "
            "This is nearby water, not a reading of this exact spot.",
            location_name=s.get("location"),
            distance_m=round(s["distance_m"], 1),
            sample_count=1,
        )

    # --- 3. HISTORICAL DATA --------------------------------------------------
    # A real sample recorded for this place at some point in the past. Used only
    # when it is close enough to be about this location, and always labelled as
    # historical - water quality moves, and an old reading is not a current one.
    if samples and complete(samples[0]["values"]):
        s = samples[0]
        if s["distance_m"] <= NEARBY_SAMPLE_RADIUS_M:
            when = s.get("created_at") or "an earlier submission"
            return result(
                DATA_SOURCE_HISTORICAL, dict(s["values"]),
                f"Previously measured at this location ({when}). This is a "
                "historical reading, not a current one - test again before relying on it.",
                location_name=s.get("location"),
                sample_count=1,
            )

    # --- 4. DATASET-BASED ESTIMATE ------------------------------------------
    # The real measured corpus, by source type. Genuine measured data, but
    # averaged over many samples from many places, so it describes water of this
    # KIND rather than this water.
    entry = _dataset_estimate(water_type)
    if entry and complete(entry["values"]):
        return result(
            DATA_SOURCE_DATASET, dict(entry["values"]),
            f"Median of {entry['sample_count']:,} measured samples in the project "
            f"water-quality dataset. A dataset-based estimate for {water_type}, not a "
            "reading taken at this location.",
            sample_count=entry["sample_count"],
        )

    # --- 5. THE PLAIN ESTIMATE -----------------------------------------------
    # The last resort, and what the Location page used to show unconditionally.
    # Representative values for the source flavour from our own table, with no
    # measured corpus behind them - so it is the weakest answer and says so.
    return result(
        DATA_SOURCE_ESTIMATED, default_parameters(water_type),
        f"Typical values for {water_type}, not a measurement at this location and "
        "not drawn from a measured sample. Review and replace with your own test "
        "results before analysing.",
        sample_count=0,
    )


# --- Scope (state / country enforcement) --------------------------------------

# The one message a blocked user sees, for a state scope and a country scope
# alike. It names the restriction without naming the configured area, so the
# coverage of a deployment cannot be read off the block message.
SCOPE_DENIED_MESSAGE = (
    "Water quality analysis is currently available only within the configured "
    "location area."
)

# PROMPT 13, REQUIREMENT 8: THE MESSAGE FOR A PLACE WE COULD NOT PLACE.
#
# Deliberately NOT the denial sentence, and deliberately vague about the
# configured area for the same reason that one is. Saying "that is outside the
# area" about a pin we could not resolve is a confident boundary claim the
# lookup never made; saying "we could not determine which area this point is
# in" is what actually happened, and it tells the user what to do next - pick a
# place by name, or drop the pin somewhere unambiguous.
SCOPE_AMBIGUOUS_MESSAGE = (
    "This point could not be matched to a specific administrative area, so it "
    "cannot be checked against the configured location area. Please choose a "
    "location by name, or place the pin somewhere that resolves clearly."
)


def within_scope(place: dict, scope_state: str | None = None, scope_country: str | None = None) -> dict:
    """Is this place inside the admin-fixed scope?

    ``allowed`` answers the question, ``reason`` is the message the UI shows when
    it does not. The reason is the SAME sentence for a state and a country scope,
    deliberately: the user is told the analysis is limited to a configured area,
    without being told which area is configured.

    MATCHING IS NORMALISED AND WHOLE-VALUE, not a substring test. "India" must not
    match "Indianapolis", and a state is compared against the resolved state with
    surrounding whitespace and case removed.

    PROMPT 13, REQUIREMENT 8: THE VERDICT CARRIES `ambiguous` AS WELL AS
    `allowed`, and the two failures are kept DISTINCT. A place the lookup could
    not place - no state resolved, as at a border or at sea - is refused, but it
    is reported as ambiguous rather than as out of scope, because calling it
    out of scope asserts a boundary judgement that was never made. An
    unverifiable place is still refused, because allowing a place we cannot
    verify is in scope is the wrong default for an access restriction; the
    `ambiguous` flag exists so the refusal can ASK FOR CLARIFICATION instead of
    pretending to know where the boundary is.
    """
    if not scope_state and not scope_country:
        return {"allowed": True, "reason": None}

    def _norm(value) -> str:
        return " ".join(str(value or "").split()).casefold()

    if scope_state:
        wanted = _norm(scope_state)
        if wanted:
            place_state = _norm(place.get("state"))
            if not place_state:
                # PROMPT 13, REQUIREMENT 8: THE PLACE COULD NOT BE PLACED, WHICH
                # IS NOT THE SAME AS BEING OUTSIDE THE SCOPE.
                #
                # A pin near a border, in the sea, or in a region the geocoder
                # names only at country level resolves with NO state. Calling
                # that "outside the configured area" is a specific and confident
                # claim about a place we could not actually place, and it is
                # wrong often enough to be misleading - the pin may well be
                # inside the scope. So it is reported as AMBIGUOUS, which asks
                # the caller to clarify instead of asserting a boundary
                # judgement it never made. The access answer is still NO: an
                # unverifiable place is refused, because the alternative -
                # allowing a place we cannot verify is in scope - is the wrong
                # default for a restriction.
                return {
                    "allowed": False,
                    "ambiguous": True,
                    "reason": SCOPE_AMBIGUOUS_MESSAGE,
                }
            if place_state != wanted:
                return {"allowed": False, "ambiguous": False, "reason": SCOPE_DENIED_MESSAGE}

    if scope_country:
        wanted = _norm(scope_country)
        if wanted:
            place_country = _norm(place.get("country"))
            if not place_country:
                return {
                    "allowed": False,
                    "ambiguous": True,
                    "reason": SCOPE_AMBIGUOUS_MESSAGE,
                }
            if place_country != wanted:
                return {"allowed": False, "ambiguous": False, "reason": SCOPE_DENIED_MESSAGE}

    return {"allowed": True, "ambiguous": False, "reason": None}


def active_scope() -> tuple[str | None, str | None]:
    """The admin-fixed ``(state, country)``, honouring the stored MODE.

    THE MODE IS THE AUTHORITY, not the presence of a name. `set_location_scope`
    clears the column a mode is not using, but that is a property of one writer
    rather than a guarantee - a hand-edited row, a restored partial dump, or a
    future writer could leave a stale name beside an OFF mode. Reading the mode
    first makes OFF mean off by construction, so a leftover name can never apply
    a restriction the administrator never asked for.

    Returns ``(None, None)`` when the scope is off, or when the settings row
    cannot be read at all: a scope read failure must not take the whole feature
    down, and allowing (rather than blocking) is the correct default for an
    OPTIONAL guard whose failure mode would otherwise lock every user out.
    """
    try:
        from app.services.admin_service import get_settings

        settings = get_settings()
        mode = (getattr(settings, "location_scope_mode", None) or "").strip().lower()
        if mode not in ("state", "country"):
            return (None, None)
        return (
            (getattr(settings, "location_scope_state", None) or "").strip() or None,
            (getattr(settings, "location_scope_country", None) or "").strip() or None,
        )
    except Exception:  # noqa: BLE001 - scope is an optional guard, not the feature
        return (None, None)


def enforce_prediction_scope(location_fields: dict) -> None:
    """Refuse a PREDICTION whose place is outside the configured scope.

    WHY THIS EXISTS AS WELL AS THE LOCATION-ROUTE CHECKS. The Location routes
    already block a search or a resolve outside the scope, but a prediction can
    be submitted directly to the prediction endpoint carrying its own location
    labels - so a caller who never used the Location screen could bypass the
    restriction entirely. Requirement 7 is explicit that the check must be on the
    BACKEND for every relevant prediction/location API, so the guard is repeated
    HERE, at the point the prediction is actually recorded.

    A PREDICTION WITH NO LOCATION IS ALLOWED. The parameter-only prediction path
    is a documented feature and carries no place to check; the scope restricts
    WHICH PLACES may be analysed, not whether a location-free reading may be.

    A PLACE THAT CANNOT BE PLACED IS TREATED AS AMBIGUOUS and refused, matching
    `within_scope` - see its docstring for why an unverifiable place is refused
    rather than assumed to be inside.

    Raises `ForbiddenError` on a refusal, so the caller receives a 403 with the
    same sentence the Location screens show, instead of a silently substituted
    location - the brief is explicit that the user's chosen place must never be
    silently replaced.
    """
    scope_state, scope_country = active_scope()
    if not scope_state and not scope_country:
        return

    if not location_fields:
        return

    # Only the labels the resolver would compare. A prediction carrying no place
    # at all (all four NULL) is the location-free path and is allowed above.
    place = {
        "state": location_fields.get("location_state"),
        "country": location_fields.get("location_country"),
    }
    if not (place["state"] or place["country"]):
        return

    verdict = within_scope(place, scope_state=scope_state, scope_country=scope_country)
    if not verdict["allowed"]:
        from app.utils.errors import ForbiddenError

        raise ForbiddenError(verdict["reason"] or SCOPE_DENIED_MESSAGE)


# --- State-level rain alerts (the Rainy Alerts screen) ------------------------
#
# WHAT THIS IS FOR. The Rainy Alerts screen asks the browser where the device
# is, resolves that to a STATE, and shows the rain situation for that state. The
# browser supplies coordinates; everything else - which state, where its centre
# is, and what the weather there is doing - is resolved live from open data. No
# state is named, listed or assumed anywhere in this file.
#
# WHY A STATE AND NOT A POINT. A device pin is one point, and weather at one
# point is not weather for a region. The screen is about a state, so the forecast
# is taken at the state's administrative centre - resolved by the SAME
# `country_service.resolve_state` that the existing state overview uses, so the
# Rainy Alerts screen and the Location screens can never disagree about where
# "Kerala" is.
#
# IT IS A LOCATION-TO-WEATHER LOOKUP, NOT A GEOGRAPHY ENCYCLOPEDIA. There is no
# country here, no season heuristic, and no "it is June so it must be the
# monsoon". Every number on the screen is a figure the weather service returned.


def _state_label(state: str | None, country: str | None) -> str:
    """How the state is named on screen: "Tamil Nadu, India"."""
    parts = [part for part in (state, country) if part]
    return ", ".join(parts)


def state_rain_alert(
    lat: float,
    lon: float,
    days: int = 7,
) -> dict[str, Any] | None:
    """The rain situation for the STATE a device coordinate falls in.

    ``lat``/``lon`` are the browser's own geolocation fix. The state is resolved
    from THAT POINT by reverse geocoding, then its centre is resolved by name,
    then the forecast is taken there. Returns None only when the coordinates
    cannot be placed in any state at all - in which case the caller says so
    honestly rather than showing weather for somewhere the device is not.

    The response is one object carrying the place, the state, the forecast and
    the notice, so the screen never has to join two responses together or decide
    which half is authoritative.
    """
    place = reverse(lat, lon)
    if place is None:
        return None

    state = place.get("state")
    if not state:
        # Coordinates that resolve to a place with no state: an ocean point, or a
        # country whose subdivision Nominatim does not carry. The district or
        # city is then the best available region name, and it is used AS NAMED -
        # never replaced with a guess about which state it "should" be in.
        state = place.get("district") or place.get("city")
    if not state:
        return None

    from app.services.country_service import resolve_state

    # THE FORECAST IS TAKEN AT THE CHOSEN POINT, NOT THE STATE'S CENTRE.
    #
    # This used to resolve the state's administrative centre by name and forecast
    # THERE - so every location inside a state returned the identical numbers.
    # Four cities hundreds of kilometres apart in Tamil Nadu (Chennai, Ooty,
    # Tirunelveli, Thanjavur) all reported the same `soon_mm` and `total_mm`, and
    # the page attributed one city's rain to all of them. The rain figures a
    # visitor sees must belong to the place they named or pinned, so the request's
    # own latitude/longitude is what the weather service is asked about.
    #
    # The state is still resolved, because the state's NAME is shown beside the
    # figures. It is a LABEL, not the point the weather is read at.
    centre = resolve_state(state) or {}
    forecast_lat = lat
    forecast_lon = lon
    # Whether the figures are for the visitor's own point (True) or could only be
    # read at the state centre (False). Always True now; kept as a field so the UI
    # can state which point the forecast belongs to without a schema change.
    resolved_at_centre = False

    weather = rain_forecast(forecast_lat, forecast_lon, days=days)
    if weather is None:
        return None

    # The state's canonical name, preferring the administrative answer over the
    # raw address text: "Tamil Nadu" rather than a long Nominatim label.
    state_name = (
        centre.get("state")
        or centre.get("name")
        or place.get("state")
        or place.get("district")
        or place.get("city")
    )
    country = centre.get("country") or place.get("country")

    # A state NAME the weather service could not place: the forecast is real and
    # is still returned, flagged, rather than being withheld or quietly attributed
    # to a state the device may not be in.
    located = bool(state_name)

    return {
        "place": {
            "name": place.get("name"),
            "city": place.get("city"),
            "district": place.get("district"),
            "state": place.get("state"),
            "country": place.get("country"),
            "pincode": place.get("pincode"),
        },
        "state": state_name,
        "country": country,
        "label": _state_label(state_name, country),
        # Where the figures below were measured, and whether that is the state's
        # administrative centre or the device's own point.
        "forecast_lat": forecast_lat,
        "forecast_lon": forecast_lon,
        "forecast_at_state_centre": resolved_at_centre,
        "located": located,
        "source": "Open-Meteo",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "weather": weather,
    }


# --- Regional rain alerts (PROMPT 2, B.7-B.9) --------------------------------
#
# The Rainy Alerts screen's bottom section: the rain situation for a SAMPLE of
# the resolved state's own districts, each row a REAL forecast read at that
# district's real location. Nothing is copied from the device's own weather and
# nothing is invented: a district the weather service cannot place is reported
# as unavailable, never filled in.
#
# WHY A SAMPLE OF DISTRICTS AND NOT EVERY ONE. A large state has 75 districts,
# and Open-Meteo is a free shared service - one request per district, bounded by
# the same per-URL politeness interval as every other call here, so asking about
# all of them would hold the screen open for minutes. The cap keeps the section
# bounded while still covering the state widely; the rows are the state's own
# districts from the SAME bundled administrative list the state overview uses,
# so the two screens can never disagree about what the districts are.

# How many districts one regional-alerts answer samples. Bounded so the whole
# state's section answers in seconds rather than minutes.
_REGIONAL_ALERT_LIMIT = 8


def _nearest_districts_to(
    districts: list[dict], lat: float, lon: float
) -> list[dict]:
    """The state's districts, ordered NEAREST-FIRST to a chosen point.

    WHY THIS EXISTS. `state_districts` returns a state's districts in the bundled
    list's order, so every point inside a state produced the same regional rows.
    The brief is explicit that a location's own rain must be shown for that
    location, so when the caller knows WHICH point the visitor chose, the sample
    is taken from the districts nearest it.

    A district with no known centre cannot be measured against the point, so it
    is kept AFTER every district that can be - dropping it would silently shrink
    the state's coverage, and its own row still resolves or reports honestly.
    The original order is preserved within each group, so the answer is stable
    for two points that are equidistant.
    """
    def sort_key(item: tuple[int, dict]) -> tuple[int, float, int]:
        index, district = item
        dlat, dlon = district.get("lat"), district.get("lon")
        if dlat is None or dlon is None:
            # Last, but still present; `index` keeps ties deterministic.
            return (1, 0.0, index)
        try:
            distance = _haversine_km(lat, lon, float(dlat), float(dlon))
        except (TypeError, ValueError):
            return (1, 0.0, index)
        return (0, distance, index)

    return [district for _, district in sorted(enumerate(districts), key=sort_key)]


def regional_rain_alerts(
    state: str | None,
    lat: float | None = None,
    lon: float | None = None,
    days: int = 2,
) -> dict[str, Any]:
    """Real rain outlooks for a sample of ONE state's districts.

    ``state`` is the state the device was resolved into (or that the user
    selected). Each district is geocoded by its own name + state - the SAME
    bundled list the state overview uses - and its forecast is read AT THAT
    DISTRICT's own coordinates. A district the geocoder or the weather service
    cannot place is returned with ``available: false`` and a reason; nothing is
    substituted, copied from a neighbouring row, or invented.

    ``lat``/``lon`` are the CALLER'S OWN CHOSEN POINT when it has one. They do
    not change how a row is measured - every row is still read at that
    district's real coordinates - but they decide WHICH districts are sampled:
    the ones nearest the chosen point come first. Without them the sample was the
    state's districts in list order, identical for every place in the state.

    The answer distinguishes the two states the brief requires:

      * ``available: true``  with rows  - real per-district forecasts
      * ``available: false``            - the provider could not answer; the
        UI says "Alert data unavailable", which is NOT "no active alerts".
    """
    if not state or not str(state).strip():
        return {"available": False, "reason": "no_state", "state": None,
                "rows": [], "generated_at": datetime.now(timezone.utc).isoformat()}

    state = str(state).strip()
    generated_at = datetime.now(timezone.utc).isoformat()

    from app.services.country_service import resolve_state, state_districts

    # The state's own districts, from the bundled administrative list.
    centre = resolve_state(state) or {}
    canonical = centre.get("state") or centre.get("name") or state
    districts = state_districts(centre or {"name": canonical}, limit=_REGIONAL_ALERT_LIMIT,
                                enrich=False)
    from concurrent.futures import ThreadPoolExecutor

    def _centre_of(district: dict) -> tuple[float | None, float | None]:
        """A district's own coordinates, geocoding by name when it has none.

        THE BUNDLED LIST IS NAMES ONLY. `state_districts(enrich=False)` returns
        each district with no `lat`/`lon` (the enrichment that would supply a
        centroid is a live Overpass walk, skipped on the fast path and returning
        nothing at all when Overpass is unreachable). Without a centre a district
        cannot be measured against the visitor's point, which is why the sample
        was identical for every place in the state: every district was kept, and
        each was then geocoded individually in list order.

        Resolving here - BEFORE the nearest-first sort - is what makes the sort
        meaningful. The geocode is the same name+state search the row already
        used, so nothing new is introduced; it has only been moved earlier so its
        result can decide the ORDER rather than just the row's own weather.
        """
        dlat, dlon = district.get("lat"), district.get("lon")
        if dlat is not None and dlon is not None:
            return float(dlat), float(dlon)
        name = district.get("name") or district.get("district")
        if not name:
            return None, None
        try:
            matches = search(f"{name}, {canonical}", limit=1)
        except Exception:  # noqa: BLE001 - a geocode failure is a row-level answer
            matches = []
        if not matches:
            return None, None
        return matches[0].get("lat"), matches[0].get("lon")

    # FILL IN THE CENTRES FIRST, then sample the NEAREST-FIRST.
    #
    # `state_districts` hands back the state's districts in the bundled list's
    # order, so the same rows were returned for every point inside a state - a
    # visitor in Chennai and one in Kanyakumari saw the same districts. When the
    # caller knows the chosen point (a device fix, a search or a pin), the
    # districts actually nearest it are sampled, so the section is about the
    # visitor's own part of the state rather than an arbitrary slice of it.
    if lat is not None and lon is not None:
        with ThreadPoolExecutor(max_workers=4) as centre_pool:
            centres = list(centre_pool.map(_centre_of, districts))
        for district, (clat, clon) in zip(districts, centres):
            if clat is not None and clon is not None:
                district["lat"], district["lon"] = clat, clon
        # Only a district that could not be placed at all is pushed to the end;
        # the rest are ordered by real distance to the chosen point.
        districts = _nearest_districts_to(districts, float(lat), float(lon))
    if not districts:
        return {"available": False, "reason": "no_districts", "state": canonical,
                "rows": [], "generated_at": generated_at}

    def _row(district: dict) -> dict[str, Any]:
        name = district.get("name") or district.get("district")
        row: dict[str, Any] = {
            "name": name,
            "district": name,
            "state": canonical,
            "lat": district.get("lat"),
            "lon": district.get("lon"),
            "available": False,
            "reason": None,
            "weather": None,
        }
        # Already centred above when the caller supplied a point; geocoded here
        # otherwise, so a request with only a state name still resolves each row.
        dlat, dlon = _centre_of(district)
        if dlat is None or dlon is None:
            row["reason"] = "not_locatable"
            return row
        row["lat"], row["lon"] = dlat, dlon
        try:
            weather = rain_forecast(float(dlat), float(dlon), days=days)
        except Exception:  # noqa: BLE001
            weather = None
        if weather is None:
            row["reason"] = "forecast_unavailable"
            return row
        row["available"] = True
        row["weather"] = weather
        return row

    # The forecasts are independent of one another, so they are fetched
    # concurrently. Each is a plain Open-Meteo request with its own politeness
    # interval; the pool size is bounded so the burst stays polite.
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(_row, districts))

    available_rows = [row for row in rows if row["available"]]
    return {
        "available": bool(available_rows),
        # No single district answered: that is an outage, not an all-clear.
        "reason": None if available_rows else "forecast_unavailable",
        "state": canonical,
        "label": _state_label(canonical, centre.get("country")),
        "rows": rows,
        "generated_at": generated_at,
        "source": "Open-Meteo",
    }


# =============================================================================
# STEP 29: WHAT QUALITY DATA DOES EACH NEARBY SOURCE ACTUALLY HAVE?
# =============================================================================
#
# The brief asks, for every source in the "Nearby Water Sources" list, what its
# available quality data is - and it is the last two lines that decide whether
# this feature could ever have been faked:
#
#   "Do not invent water-quality measurements."
#   "If exact water-quality measurements are unavailable, provide the available
#    dataset-based/historical estimate and label it correctly."
#
# So each source gets a status, and there are exactly three of them. They are
# resolved strongest-first, and a source that matches nothing is reported as
# having NO data rather than being handed the next tier's numbers.
#
#   measured        A real stored sample exists for THIS source - a real measured
#                   row within NEARBY_SAMPLE_RADIUS_M whose recorded water type
#                   matches this source's type. Every number is one that was
#                   actually measured and stored.
#
#   dataset_estimate The real measured corpus (11,000+ samples) is all that
#                   exists for this source. Its median is a real number from real
#                   measurements, but it describes measured water in GENERAL, not
#                   this river or this tank, and the label says so.
#
#   none            No measured sample and no readable corpus. The five
#                   parameters are ABSENT from the payload rather than null-
#                   filled, so a client cannot render a plausible-looking blank
#                   as a value.
#
# THE ONE THING THIS WILL NOT DO, and the reason it is worth writing down: a
# measured sample is matched to a source by its water TYPE and a radius, not by
# its name. Attaching "measured at River" to a sample whose recorded location
# was three kilometres away at a different tank would assert a link between two
# independent records that neither one makes. The radius is what keeps the claim
# inside what the data supports.

# How far a stored sample may be from a source and still be described as a
# measurement OF that source. The same 5 km Step 12 uses for "nearby": wide
# enough to find a sample in a town, tight enough that it is still a claim about
# this neighbourhood's water rather than the district's.
NEARBY_SOURCE_SAMPLE_RADIUS_M = 5000.0

# The three states a source's quality data can be in. The labels are the ones
# shown on screen, kept here so the backend owns the wording and the frontend
# cannot drift from it - the same rule the Step 12 provenance labels follow.
NEARBY_QUALITY_MEASURED = "measured"
NEARBY_QUALITY_ESTIMATED = "dataset_estimate"
NEARBY_QUALITY_NONE = "none"

_NEARBY_QUALITY_LABELS = {
    NEARBY_QUALITY_MEASURED: "Measured sample available",
    NEARBY_QUALITY_ESTIMATED: "Dataset-based estimate only",
    NEARBY_QUALITY_NONE: "No quality data available",
}


def _nearby_source_quality(
    source: dict, samples: list[dict]
) -> dict:
    """What quality data one nearby source genuinely has, and where it came from.

    ``samples`` is the already-read list of real stored samples for this
    location, sorted nearest-first by `_measured_samples_for`. It is passed in
    rather than re-read because one `/context` request looks at every nearby
    source and must not re-query the database once per row.

    Returns a dict carrying the status, the label, the five values where they
    exist, and a note saying what they are. The `values` key is OMITTED entirely
    when there is no data at all, which is what stops a client from inventing the
    numbers itself: there is nothing to render and nothing to read.
    """
    def complete(values: dict) -> bool:
        from app.constants import FEATURE_NAMES  # noqa: PLC0415 - avoids an import cycle

        return bool(values) and all(values.get(name) is not None for name in FEATURE_NAMES)

    wanted = _fold(source.get("type"))
    sample_m = (source.get("distance_km") or 0.0) * 1000.0

    # --- 1. A REAL MEASUREMENT OF THIS SOURCE -------------------------------
    #
    # Matched on the water TYPE and a radius. `sample["water_type"]` is the type
    # recorded on the stored sample, so a river sample can attach to a river and
    # nothing else; a sample with no recorded type is NOT matched, because an
    # untyped sample is evidence about some water, not about this feature.
    for sample in samples:
        if sample["distance_m"] > NEARBY_SOURCE_SAMPLE_RADIUS_M:
            continue
        sample_type = _fold(sample.get("water_type") or "")
        if not sample_type or sample_type != wanted:
            continue
        if not complete(sample["values"]):
            continue
        return {
            "status": NEARBY_QUALITY_MEASURED,
            "label": _NEARBY_QUALITY_LABELS[NEARBY_QUALITY_MEASURED],
            "values": dict(sample["values"]),
            "source_name": sample.get("location"),
            "source_distance_m": round(sample["distance_m"], 1),
            "recorded_at": sample.get("created_at"),
            "note": (
                f"Measured at {sample.get('location') or 'this source'} on "
                f"{sample.get('created_at') or 'a previous submission'}, "
                f"{sample['distance_m'] / 1000.0:.1f} km from this source. "
                "These are real recorded readings, not a reading of this spot."
            ),
        }

    # --- 2. THE REAL MEASURED CORPUS, LABELLED AS WHAT IT IS -----------------
    #
    # The corpus is a genuine set of measured samples, so its median is a real
    # number - but it is averaged over many places and does not describe this
    # particular river or tank. It is offered because the brief asks for an
    # estimate where no measurement exists, and it is labelled `dataset_estimate`
    # rather than `measured` precisely so it can never be read as a test result.
    entry = _dataset_estimate(source.get("type"))
    if entry and complete(entry["values"]):
        return {
            "status": NEARBY_QUALITY_ESTIMATED,
            "label": _NEARBY_QUALITY_LABELS[NEARBY_QUALITY_ESTIMATED],
            "values": dict(entry["values"]),
            "sample_count": entry["sample_count"],
            "note": (
                f"No test result has been recorded for this source. These figures "
                f"are the median of {entry['sample_count']:,} measured samples in "
                "the project water-quality dataset - an estimate for water in "
                "general, not a measurement of this source. Test it and enter your "
                "own readings."
            ),
        }

    # --- 3. NOTHING. SAY SO, AND CARRY NO VALUES. -----------------------------
    return {
        "status": NEARBY_QUALITY_NONE,
        "label": _NEARBY_QUALITY_LABELS[NEARBY_QUALITY_NONE],
        "note": (
            "No measured sample and no readable dataset are available for this "
            "source, so no readings are shown. Enter your own test results."
        ),
    }


def enrich_nearby_with_quality(sources: list[dict], lat: float, lon: float) -> list[dict]:
    """Add a `quality` block to each already-fetched nearby source, in place.

    STEP 29. This is the form `water_context` uses, because it has ALREADY paid
    for the Overpass walk: re-querying here would double the slowest call on the
    page for no new information. Splitting it out from
    `nearby_sources_with_quality` is what keeps the two paths from drifting -
    they share this function, so a change to how quality is resolved reaches
    both.
    """
    if not sources:
        return sources

    # Read the stored samples once for the whole list. Read defensively: no
    # table, no connection or a schema without the location columns yields an
    # empty list, and every source then falls through to its estimate - never to
    # a fabricated reading.
    samples = _measured_samples_for(lat, lon, None, None)

    for source in sources:
        source["quality"] = _nearby_source_quality(source, samples)
        source["distance_m"] = round((source.get("distance_km") or 0.0) * 1000.0, 1)
    return sources


def nearby_sources_with_quality(
    lat: float, lon: float, radius_m: int = 15000, limit: int = 10
) -> list[dict]:
    """Real nearby water sources, each carrying what quality data it actually has.

    STEP 29. This wraps `nearby_sources` - it does not replace it - so the list
    is the SAME list of real OpenStreetMap features, with the SAME real names and
    the SAME real distances, and the only thing added is a `quality` block per
    row. There is one source of truth for what water is nearby, and this step
    adds a column to it rather than a second list that could disagree.

    An empty database is the normal case and simply means every row is reported
    without measured data, which is the honest answer.
    """
    sources = nearby_sources(lat, lon, radius_m=radius_m, limit=limit)
    return enrich_nearby_with_quality(sources, lat, lon)
