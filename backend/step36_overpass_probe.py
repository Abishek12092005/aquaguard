"""Probe the Overpass mirrors the water-source lookup depends on.

Used by STEP 36 to tell an external provider outage apart from a bug in this
application: the same query is sent to every mirror with the same timeout the
service uses, and the answer is reported as the provider gave it.
"""

import json
import sys
import time

import requests

MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.maps.mail.ru/osm/tools/overpass/api/interpreter",
]

QUERY = """
[out:json][timeout:25];
(
  node["natural"="spring"](13.07,80.26,13.11,80.30);
  node["natural"="water"](13.07,80.26,13.11,80.30);
  way["waterway"="river"](13.07,80.26,13.11,80.30);
);
out 5;
"""

# Overpass rejects anonymous clients. A descriptive User-Agent is what the
# service asks for, so a 406/429 from a bare request can be a missing header
# rather than an outage - and those two need very different conclusions.
USER_AGENTS = {
    "with-UA": "AquaGuard-AI/1.0 (water quality; contact: shekabi2005@gmail.com)",
    "no-UA": None,
}

for url in MIRRORS:
    for label, agent in USER_AGENTS.items():
        headers = {"User-Agent": agent} if agent else {}
        started = time.time()
        try:
            response = requests.post(url, data={"data": QUERY}, headers=headers, timeout=45)
            elapsed = time.time() - started
            count = "?"
            if response.status_code == 200:
                count = len(response.json().get("elements", []))
            print(
                f"{url}\n    [{label}] status={response.status_code} "
                f"elapsed={elapsed:.1f}s elements={count} "
                f"body={response.text[:100]!r}"
            )
        except Exception as exc:  # noqa: BLE001 - the failure IS the datum
            print(
                f"{url}\n    [{label}] FAILED after {time.time() - started:.1f}s: {exc}"
            )

sys.exit(0)