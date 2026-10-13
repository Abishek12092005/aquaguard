import requests
q = "[out:json][timeout:20];node(9.84,78.47,9.86,78.49)[\"place\"=\"town\"];out body 2;"
try:
    r = requests.post("https://overpass.kumi.systems/api/interpreter", data=q, timeout=30)
    print("kumi:", r.status_code, len(r.content))
except Exception as e:
    print("kumi FAIL:", type(e).__name__)
