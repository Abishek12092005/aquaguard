"""Run the backend for measurement, without the debug reloader.

`run.py` enables the reloader whenever DEBUG is on, and the reloader restarts
the server whenever ANY watched .py file changes - so editing a file mid-run
silently swaps the process out from under a benchmark. This serves the same app
with the reloader off, which is also how it is deployed (waitress/gunicorn).
"""
import os
import sys

os.environ["DEBUG"] = "false"
os.environ.setdefault("FLASK_APP", "app")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False, threaded=True)
