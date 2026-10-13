"""Keeps retrying the Wikidata build in the background until it succeeds."""
import subprocess
import sys
import time

PY = sys.executable
for attempt in range(40):
    print("=== attempt %d ===" % (attempt + 1), flush=True)
    result = subprocess.run([PY, "build_step17_districts.py"],
                            capture_output=True, text=True)
    print(result.stdout[-3000:], flush=True)
    if result.returncode == 0 and "districts:" in (result.stdout or ""):
        print("BUILD OK", flush=True)
        break
    if result.stderr:
        print("stderr:", result.stderr[-1000:], flush=True)
    time.sleep(45)
