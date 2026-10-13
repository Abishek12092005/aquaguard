import json, time
from app.services.location_service import _overpass

q = (
    '[out:json][timeout:90];'
    'rel["name"~"^Tamil Nadu$",i]["boundary"="administrative"]["admin_level"="4"];'
    'map_to_area ->.st;'
    'rel(area.st)["boundary"="administrative"]["admin_level"="6"];'
    'out tags center 5;'
)
t = time.time()
body = _overpass(q)
print('secs', round(time.time() - t, 1))
if body and body.get('elements'):
    print('count', len(body['elements']))
    for el in body['elements'][:5]:
        print(el.get('tags', {}).get('name'))
else:
    print('EMPTY or None:', json.dumps(body)[:200] if body else None)
