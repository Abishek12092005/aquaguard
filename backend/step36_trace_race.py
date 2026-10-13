"""STEP 36 - when does each mirror's POST actually START, and for how long?

The walk races four mirrors, but the log shows overpass-api.de being given only
3.07 s of an 11 s read timeout - meaning its request did not start until ~9 s
after the walk began. That contradicts "released together", so this measures the
actual start/finish time of every mirror rather than inferring it.
"""

import os
import sys
import threading
import time

import json

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import requests  # noqa: E402

from app import create_app  # noqa: E402
from app.services import location_service as ls  # noqa: E402

app = create_app("testing")
T0 = time.monotonic()
TIMINGS = {}
LOCK = threading.Lock()


TIMINGS_PATH = os.path.join(HERE, "s36_race_timings.json")


def dump(stage):
    """Persist the timings after every stage change.

    The walk leaves daemon threads unwinding, and interpreter shutdown can kill
    the process before the final report is printed - which is how an earlier
    version of this produced no output at all. Writing after each stage means the
    data survives even an abrupt exit.
    """
    with LOCK:
        snapshot = {u: dict(t) for u, t in TIMINGS.items()}
    with open(TIMINGS_PATH, "w", encoding="utf-8") as handle:
        json.dump({"stage": stage, "timings": snapshot}, handle, indent=2)


def timed_post(url, query, headers, timeout):
    started = time.monotonic()
    try:
        response = requests.post(url, data=query, headers=headers, timeout=timeout)
        outcome = f"status={response.status_code} n={len(response.json().get('elements', []))}"
    except Exception as exc:  # noqa: BLE001
        outcome = f"{type(exc).__name__}"
    with LOCK:
        TIMINGS[url] = {
            "start": round(started - T0, 2),
            "end": round(time.monotonic() - T0, 2),
            "timeout_given": round(timeout, 2),
            "outcome": outcome,
        }
    dump(f"done:{url.split('/')[2]}")
    return None


with app.app_context():
    query = ls._NEARBY_QUERY.format(radius=15000, lat=13.08784, lon=80.27847)
    print(f"budget={ls._OVERPASS_BUDGET_S}s read_timeout={ls._OVERPASS_READ_TIMEOUT}s")
    print(f"polite interval for overpass = {ls._POLITE_INTERVALS['overpass']}s")

    real_post = ls._session.post
    ls._session.post = timed_post
    T0 = time.monotonic()
    try:
        result = ls._overpass(query)
    finally:
        ls._session.post = real_post

print(f"\nresult: {'None (no mirror answered)' if result is None else str(len(result.get('elements', []))) + ' elements'}")
print("\nper-mirror timings (seconds from walk start):")
for url in ls._OVERPASS_MIRRORS:
    timing = TIMINGS.get(url)
    if timing:
        print(f"  {url.split('/')[2]:28s} "
              f"start={timing['start']:6.2f}  end={timing['end']:6.2f}  "
              f"timeout_given={timing['timeout_given']:5.2f}  {timing['outcome']}")
    else:
        print(f"  {url.split('/')[2]:28s} never ran")

# STEP 36: the executor's worker threads can still be unwinding at interpreter
# shutdown, and that raises into atexit - which truncated this report before. The
# measurements are written out here, before exit, and the file is read back.
import json

with open(os.path.join(HERE, "s36_race_timings.json"), "w", encoding="utf-8") as handle:
    json.dump({
        "budget": ls._OVERPASS_BUDGET_S,
        "read_timeout": ls._OVERPASS_READ_TIMEOUT,
        "result_elements": None if result is None else len(result.get("elements", [])),
        "timings": {u.split("/")[2]: t for u, t in TIMINGS.items()},
        "never_ran": [u.split("/")[2] for u in ls._OVERPASS_MIRRORS if u not in TIMINGS],
    }, handle, indent=2)
print("\nwrote s36_race_timings.json")
sys.stdout.flush()