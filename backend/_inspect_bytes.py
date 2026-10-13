raw = open("app/services/country_service.py", "rb").read()
text = raw.decode("utf-8")
lines = text.splitlines()
line = lines[568]
print("line 569 repr:")
print(repr(line))
for ch in line:
    if ord(ch) > 127:
        print("  U+%04X %r" % (ord(ch), ch))
