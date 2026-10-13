"""Serves the API with the admin console already UNLOCKED, for UI verification.

The console's unlock is server-side process state (`console_session`), so it
must be opened in the SAME process that serves requests - a separate one-shot
script would be closed again before the browser loaded the page. This unlocks
and then serves, which is what lets a headless browser drive the unlocked
console.

    python database/serve_unlocked.py 5000

FOR LOCAL UI VERIFICATION ONLY. It opens the console without the password or
the mailed approval, which is exactly the gate the console exists to enforce,
so it must never be used as a way to run the application.
"""

from __future__ import annotations

import sys
from pathlib import Path

# `app` lives one directory up; this file is run as `python database/...`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app  # noqa: E402
from app.services.console_session import unlock  # noqa: E402

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 5000

app = create_app("development")

with app.app_context():
    print("console unlocked:", unlock(), flush=True)

app.run(port=PORT, debug=False, use_reloader=False)