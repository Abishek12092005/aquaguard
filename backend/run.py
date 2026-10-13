"""Development entrypoint.

    python run.py

For anything beyond local development use a WSGI server instead:

    waitress-serve --port=5000 run:app        (Windows)
    gunicorn -w 4 -b 0.0.0.0:5000 run:app     (Linux/macOS)
"""

import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    host = os.getenv("FLASK_HOST", "127.0.0.1")
    port = int(os.getenv("FLASK_PORT", "5000"))
    debug = app.config.get("DEBUG", True)

    print(f"  AquaGuard AI API")
    print(f"  -> http://{host}:{port}/")
    print(f"  -> http://{host}:{port}/api/v1/health\n")

    app.run(host=host, port=port, debug=debug, use_reloader=debug)
