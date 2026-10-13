import json
d = json.load(open("app/services/india_districts.json", encoding="utf-8"))
for k in sorted(d, key=str.casefold):
    print("%-42s %3d" % (k, len(d[k])))
