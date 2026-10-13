"""Parse the Step 17 modules to prove they are still valid Python."""
import ast
import codecs

FILES = [
    "app/services/country_service.py",
    "app/services/district_service.py",
    "app/services/location_service.py",
    "app/routes/location_routes.py",
    "build_step17_districts.py",
]
BOM = codecs.BOM_UTF8.decode("utf-8")

for path in FILES:
    text = open(path, "rb").read().decode("utf-8-sig")
    # A leading BOM decoded as a literal character is U+FEFF in the source,
    # which ast.parse rejects. Strip it either way.
    if text.startswith(BOM):
        text = text[len(BOM):]
    ast.parse(text, path)
    print("OK", path)
