"""Strip the ' district' suffix from the captured Wikidata labels."""
import json
import re

PATH = "app/services/india_districts.json"
data = json.load(open(PATH, encoding="utf-8"))
out = {}
for state, names in data.items():
    cleaned = set()
    for n in names:
        c = re.sub(r"\s+district$", "", n, flags=re.I).strip()
        if c:
            cleaned.add(c)
    out[state] = sorted(cleaned, key=str.casefold)
json.dump(out, open(PATH, "w", encoding="utf-8"), ensure_ascii=False,
          indent=1, sort_keys=True)
print("states %d districts %d" % (len(out), sum(len(v) for v in out.values())))
print("Tamil Nadu %d: %s" % (len(out["Tamil Nadu"]), out["Tamil Nadu"][:6]))
