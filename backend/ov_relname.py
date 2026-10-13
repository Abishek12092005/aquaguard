import requests, json
# What admin_level=6 relations in Tamil Nadu match "Sivaganga"?
q = '[out:json][timeout:60];rel["name"~"Sivaganga",i]["boundary"="administrative"]["admin_level"="6"];out tags 5;'
r = requests.post("https://overpass.kumi.systems/api/interpreter", data=q, timeout=120)
print("status", r.status_code)
for el in r.json().get("elements", []):
    print(el.get("tags", {}).get("name"), "| id", el.get("id"))
