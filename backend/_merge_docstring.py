"""Merge the two docstrings the Step 17 edit left split in state_overview."""
path = "app/services/country_service.py"
lines = open(path, encoding="utf-8").read().splitlines(keepends=True)

# Lines 558..586 (1-based) are the broken block: a docstring that closed early
# at 566, then the original body text, then a stray closing quotes at 586.
start, end = 557, 586  # 0-based slice covering lines 558..586
block = "".join(lines[start:end])
assert block.lstrip().startswith('"""Step 20/17'), block[:60]
assert block.rstrip().endswith('"""'), block[-60:]

merged = block.replace("lookup.\n    \"\"\"\n\n", "lookup.\n\n", 1)
open(path, "w", encoding="utf-8", newline="").write(
    "".join(lines[:start]) + merged + "".join(lines[end:]))
print("merged; removed the early close")
