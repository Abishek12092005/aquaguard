import requests, time
QUERY = "[out:json][timeout:20];node(9.84,78.4,9.9,78.5);out body 1;"
for url in ["https://overpass-api.de/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter"]:
    t0 = time.monotonic()
    try:
        r = requests.post(url, data=QUERY, timeout=90,
                          headers={"User-Agent": "AquaGuardAI/1.0"})
        n = len(r.json().get("elements") or []) if r.status_code == 200 else 0
        print(url.split("/")[2], r.status_code, "elements=", n, f"{time.monotonic()-t0:.1f}s", flush=True)
    except Exception as e:
        print(url.split("/")[2], "FAIL", type(e).__name__, f"{time.monotonic()-t0:.1f}s", flush=True)
