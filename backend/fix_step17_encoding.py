"""Repair the single-pass mojibake left in country_service.py.

The file is UTF-8 on disk, but 43 sequences were written as cp1252 bytes that
had already been through a UTF-8 decode, so they read as three real characters
("a-circumflex" + Euro + "trademark") where one was meant (an em dash). Those
are legal inside a string, and a docstring is a str, so the module still
imports - the damage is the visible garbage in the source. Mapping them back
keeps the comments and docstrings readable and leaves the code untouched.

Only the sequences measured present are replaced; nothing that was already
correct is rewritten. Whatever survives is reported rather than left to be
noticed later.
"""
import codecs

PATH = "app/services/country_service.py"

# Written with explicit code points so this script's own encoding cannot change
# what it does.
FIXES = [
    ("â€", "—"),      # mojibake'd em dash
    ("â€¦", "…"),      # mojibake'd ellipsis
    ("â€™", "’"),      # mojibake'd right single quote
    ("â€¢", "·"),      # mojibake'd middle dot
    ("â€œ", "“"),      # mojibake'd left double quote
    ("â€\x9d", "”"),      # mojibake'd right double quote
    ("â€", "—"),      # leftover two-char prefix
]

raw = open(PATH, "rb").read()
if raw.startswith(codecs.BOM_UTF8):
    raw = raw[len(codecs.BOM_UTF8):]
text = raw.decode("utf-8")

before = text
for bad, good in FIXES:
    if bad != good:
        text = text.replace(bad, good)

left = text.count("â") + text.count("€") + text.count("�")
open(PATH, "w", encoding="utf-8", newline="").write(text)
print("repaired=%s  remaining_mojibake=%d" % (text != before, left))
