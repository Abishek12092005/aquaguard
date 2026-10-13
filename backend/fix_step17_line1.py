"""Restore the module docstring's opening quotes on line 1 of country_service.

The earlier mojibake repair turned line 1 into `""Country overview service ...`,
losing one of the three quotes that open the module docstring, so Python reads
the em dash as code rather than as text. This puts the third quote back.
"""
PATH = "app/services/country_service.py"

lines = open(PATH, encoding="utf-8-sig").read().splitlines(keepends=True)
old = lines[0]
if old.startswith('""') and not old.startswith('"""'):
    lines[0] = '"' + old
open(PATH, "w", encoding="utf-8", newline="").write("".join(lines))
print("after :", lines[0].rstrip())
