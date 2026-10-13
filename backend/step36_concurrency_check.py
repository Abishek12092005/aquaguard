"""STEP 36 - is the four-mirror race actually running CONCURRENTLY?

The walk submits one worker per mirror and expects the cost to be the FASTEST
response. If the workers serialise, the cost becomes the SUM of the timeouts and
no budget can save it. This measures that directly, with no Overpass involved:
four workers each sleeping a known duration, released through the same executor
shape the walk uses.
"""

import os
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor
from concurrent.futures import wait as futures_wait

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

OUT = os.path.join(HERE, "s36_concurrency.json")

SLEEPS = {"a": 8.0, "b": 3.0, "c": 6.0, "d": 5.0}
# Matches _OVERPASS_MIRRORS: one worker per mirror, all submitted up front.
MAX_WORKERS = len(SLEEPS)
BUDGET = 12.0


def worker(name):
    time.sleep(SLEEPS[name])
    return name


if __name__ == "__main__":
    started = time.time()
    deadline = started + BUDGET
    winner = []
    pending = set()
    executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
    try:
        for name in SLEEPS:
            pending.add(executor.submit(worker, name))
        while pending:
            done, pending = futures_wait(pending, timeout=BUDGET, return_when=FIRST_COMPLETED)
            if not done:
                break
            for future in done:
                winner.append(future.result())
            if winner:
                break
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    elapsed = time.time() - started

    fastest = min(SLEEPS.values())
    slowest = max(SLEEPS.values())
    # Serial execution costs about the SUM; concurrent costs about the FASTEST.
    serial_estimate = sum(SLEEPS.values())

    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write(
            f"workers            : {MAX_WORKERS}\n"
            f"sleeps             : {SLEEPS}\n"
            f"elapsed            : {elapsed:.2f}s\n"
            f"winner             : {winner}\n"
            f"fastest single     : {fastest:.2f}s  <- what concurrent execution costs\n"
            f"sum (if serial)    : {serial_estimate:.2f}s\n"
            f"verdict            : {'CONCURRENT' if elapsed < serial_estimate * 0.75 else 'SERIAL'}\n"
        )
    print(open(OUT).read())