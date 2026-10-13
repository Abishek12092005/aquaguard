"""STEP 29: the `/locations/context` payload, with the Overpass walk stubbed.

Overpass is unreachable on some networks, including this one right now, so a live
end-to-end run proves nothing about this step's logic. The OSM element list is
therefore stubbed with rows shaped exactly as `nearby_sources` shapes them, and
the real `water_context`, the real quality resolution and the real route run on
top of it.

What matters is that the payload carries, per source: the real name, the real
type, the real distance, and a `quality` block whose status matches where its
numbers actually came from - and that nothing appears in the response that the
stub did not put there.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from app import create_app  # noqa: E402
from app.services import location_service as ls  # noqa: E402

# Rows shaped exactly as `nearby_sources` returns them: real OSM names, real
# types, real computed distances, and the `named` flag that says whether the map
# supplied a name at all.
STUBBED_OSM = [
    {"type": "river water", "name": "Karaikudi River", "named": True,
     "distance_km": 1.23, "osm_tag": "river", "lat": 9.979, "lon": 76.244},
    {"type": "tank water", "name": "Unnamed Water Tank", "named": False,
     "distance_km": 0.84, "osm_tag": "reservoir", "lat": 9.975, "lon": 76.251},
]


def main() -> int:
    failures = []

    def check(name, condition, detail=""):
        if condition:
            print(f"  PASS  {name}")
        else:
            print(f"  FAIL  {name}  {detail}")
            failures.append(name)

    print("STEP 29: /locations/context carries per-source quality data")

    real_nearby = ls.nearby_sources
    real_samples = ls._measured_samples_for
    ls.nearby_sources = lambda lat, lon, radius_m=15000, limit=10: [
        dict(row) for row in STUBBED_OSM
    ]
    # No stored samples: the normal case on a fresh database. Each source must
    # then report the dataset estimate, and must not claim to be measured.
    ls._measured_samples_for = lambda lat, lon, place, water_type: []

    try:
        app = create_app()
        with app.test_client() as client:
            response = client.get("/api/v1/locations/context?lat=9.9679&lon=76.2444")
            body = response.get_json()
    finally:
        ls.nearby_sources = real_nearby
        ls._measured_samples_for = real_samples

    check("the request succeeded", response.status_code == 200, response.status_code)
    data = (body or {}).get("data") or {}
    sources = data.get("nearby_sources") or []
    check("both stubbed sources are present", len(sources) == 2, len(sources))

    by_name = {row.get("name"): row for row in sources}
    river = by_name.get("Karaikudi River")
    tank = by_name.get("Unnamed Water Tank")
    check("the real OSM name is passed through unchanged", river is not None)
    check("the unnamed feature keeps its honest label", tank is not None,
          sorted(by_name))
    if river:
        check("the real type is passed through", river.get("type") == "river water",
              river.get("type"))
        check("the real distance is passed through", river.get("distance_km") == 1.23,
              river.get("distance_km"))
        quality = river.get("quality") or {}
        check("it has a quality block", bool(quality), quality)
        check("with no stored sample it is an estimate, not measured",
              quality.get("status") == ls.NEARBY_QUALITY_ESTIMATED,
              quality.get("status"))
        check("the estimate is labelled as an estimate",
              "estimate" in (quality.get("label") or "").lower(),
              quality.get("label"))
        check("the estimate carries the five parameters",
              len(quality.get("values") or {}) == 5, quality.get("values"))
        check("the note says it is not a measurement of this source",
              "not a measurement of this source" in (quality.get("note") or ""),
              (quality.get("note") or "")[:70])
    if tank:
        check("the unnamed flag survives to the client",
              tank.get("named") is False, tank.get("named"))
        check("it also gets the estimate",
              (tank.get("quality") or {}).get("status") == ls.NEARBY_QUALITY_ESTIMATED,
              (tank.get("quality") or {}).get("status"))

    # The one thing that must never be true: a source with no stored sample
    # claiming to carry a measurement.
    measured_claims = [
        row.get("name") for row in sources
        if (row.get("quality") or {}).get("status") == ls.NEARBY_QUALITY_MEASURED
    ]
    check("no source claims to be measured without a stored sample",
          not measured_claims, measured_claims)

    # And the "do not invent a name" rule: the unnamed feature is still unnamed.
    invented = [
        row.get("name") for row in sources
        if row.get("named") is False
        and not (row.get("name") or "").startswith("Unnamed")
    ]
    check("no unnamed feature was given a real-sounding name", not invented, invented)

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {failures}")
        return 1
    print("All STEP 29 context-payload checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
