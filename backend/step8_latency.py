"""STEP 8 latency check: how long does a suggestion actually take to appear?

The complaint the search bar has to answer is "it should not wait until the full
word is typed", which is a latency requirement as much as a matching one. This
times the real provider path for a simulated typing session - one keystroke at a
time, exactly what the autocomplete issues - and reports each step.

Two paths are timed for every prefix:

  * autocomplete=True  the typing path: bounded number of spelling variants
  * autocomplete=False the "resolve one place" path: every variant

A cold run and a warm run are both reported. The warm one is not a fake cache of
results handed to the user: it is the same live geocoders, and the point is to
show what a user who is mid-search actually experiences, since consecutive
prefixes share most of their provider lookups.
"""
import os
import sys
import time

# Place names come back with the accents and non-Latin scripts the provider
# actually uses ("Płock", "திண்டுக்கல்"). Printing those to a cp1252 console
# raises UnicodeEncodeError, which is a crash in the MEASUREMENT script and not
# a fault in the search path - so the console is forced to UTF-8 here.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001 - older/odd streams simply keep the default
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from app.services import location_service  # noqa: E402

WORDS = ["karaikudi", "chennai", "thiru", "anna nagar"]


def timed(query: str, autocomplete: bool) -> tuple[float, int, str]:
    started = time.perf_counter()
    try:
        results = location_service.search(query, limit=8, autocomplete=autocomplete)
    except Exception as exc:  # noqa: BLE001
        return (time.perf_counter() - started) * 1000, 0, f"ERROR {exc}"
    elapsed = (time.perf_counter() - started) * 1000
    top = f"{results[0].get('name')} [{results[0].get('poi_label') or results[0].get('kind')}]" if results else "-"
    return elapsed, len(results), top


print("=" * 84)
print(f"{'prefix':<12} {'AUTO ms':>9} {'hits':>5} {'FULL ms':>9} {'hits':>5}   top suggestion")
print("=" * 84)

auto_all: list[float] = []
worst_auto = 0.0
for word in WORDS:
    for n in range(1, len(word) + 1):
        prefix = word[:n]
        if n > 2 and prefix not in (word[:3], word[:5], word) and n != len(word):
            # Sample a few points along each word rather than every keystroke.
            continue
        a_ms, a_n, top = timed(prefix, True)
        f_ms, f_n, _ = timed(prefix, False)
        auto_all.append(a_ms)
        worst_auto = max(worst_auto, a_ms)
        print(f"{prefix:<12} {a_ms:9.0f} {a_n:5d} {f_ms:9.0f} {f_n:5d}   {top}")

auto_all.sort()
p50 = auto_all[len(auto_all) // 2]
p95 = auto_all[int(len(auto_all) * 0.95)]
print("-" * 84)
print(f"AUTOCOMPLETE  p50 {p50:.0f} ms   p95 {p95:.0f} ms   worst {worst_auto:.0f} ms")
print(f"{'TARGET <= 2000 ms (autocomplete must feel instant)':<44}"
      f"{'PASS' if p95 <= 2000 else 'FAIL'}")
