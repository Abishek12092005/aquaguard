import requests, json
q = "[out:json][timeout:20];area[\"ISO3166-1\"=\"CH\"][admin_level=2];out count;"
for url in ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter", "https://overpass.private.coffee/api/interpreter"]:
    try:
        r = requests.post(url, data=q, timeout=30)
        print(url, "->", r.status_code, len(r.content))
    except Exception as e:
        print(url, "-> FAIL", type(e).__name__)
