"""Report which Step 17 files have mojibake and what form it is in."""
FILES = [
    "app/services/country_service.py",
    "app/services/district_service.py",
    "app/services/location_service.py",
    "app/routes/location_routes.py",
]
for path in FILES:
    raw = open(path, "rb").read()
    text = raw.decode("utf-8", "replace")
    markers = {
        "U+20AC euro (one pass of mojibake)": text.count("€"),
        "U+00E2 a-circumflex (one pass)": text.count("â"),
        "double: a-circumflex + euro": text.count("â€"),
        "good em dash": text.count("—"),
        "good ellipsis": text.count("…"),
    }
    print(path)
    for k, v in markers.items():
        if v:
            print("   %-42s %d" % (k, v))
