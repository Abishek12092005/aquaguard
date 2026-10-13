"""Remove the stray UTF-8 BOM from the files Step 17 created fresh.

`fix_step17_bom.py` restored a BOM on every file it was given, including
`district_service.py`, which was written new and never had one. A BOM is legal
in a Python source file only when the file is read as utf-8-sig; read as plain
utf-8 it becomes U+FEFF in the source and the module will not import. The
pre-existing modules keep their BOM - that is their original state - so only
the ones that never had one are touched here.
"""
import codecs

# Files that were CREATED by Step 17 and must have no BOM.
NEW_FILES = ["app/services/district_service.py"]

for path in NEW_FILES:
    with open(path, "rb") as fh:
        raw = fh.read()
    if raw.startswith(codecs.BOM_UTF8):
        with open(path, "wb") as fh:
            fh.write(raw[len(codecs.BOM_UTF8):])
        print("%s: BOM removed" % path)
    else:
        print("%s: clean" % path)
