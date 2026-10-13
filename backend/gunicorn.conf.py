"""Gunicorn configuration.

    gunicorn -c gunicorn.conf.py wsgi:app

Only relevant on Linux/macOS. On Windows use waitress instead:

    waitress-serve --port=5000 wsgi:app

The worker count, timeout and logging are the settings that actually matter for
this application; everything else is left at gunicorn's defaults deliberately.
"""

import multiprocessing
import os

# --- Binding ---------------------------------------------------------------
bind = os.getenv("GUNICORN_BIND", "0.0.0.0:5000")

# --- Workers ---------------------------------------------------------------
# The standard 2n+1 heuristic, capped. The cap is the important part here: each
# worker loads its own copy of the Random Forest artifact, so an unbounded count
# on a large host would hold many duplicate copies of the model in memory for no
# throughput benefit - this application's work is I/O-bound (MySQL + the LLM
# provider), not CPU-bound.
workers = min(int(os.getenv("GUNICORN_WORKERS", multiprocessing.cpu_count() * 2 + 1)), 8)
worker_class = "sync"

# --- Timeouts --------------------------------------------------------------
# Raised above gunicorn's 30s default because an Aqua AI turn waits on an
# external provider, and AI_REQUEST_TIMEOUT defaults to 30s. A shorter worker
# timeout would kill a request that is legitimately still in flight and surface
# as a 502 with no useful cause.
timeout = int(os.getenv("GUNICORN_TIMEOUT", "90"))
graceful_timeout = 30
keepalive = 5

# --- Restart safety --------------------------------------------------------
# Recycle workers periodically so a slow memory leak cannot accumulate across a
# long-running deployment, and jitter the restart so workers do not all recycle
# at once and drop concurrent requests.
max_requests = 1000
max_requests_jitter = 100

# --- Logging ---------------------------------------------------------------
# Access log to stdout so the platform's log collector captures it.
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info").lower()
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(M)sms'

# --- Proxies ---------------------------------------------------------------
# Trust X-Forwarded-* only from a front proxy, so client IPs and HTTPS scheme are
# reported correctly behind nginx/ALB without allowing a direct client to spoof
# them. Set FORWARDED_ALLOW_IPS to the proxy's address when not on a private
# network.
forwarded_allow_ips = os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1")

# --- Startup ---------------------------------------------------------------
# Fail fast if the production pre-flight in app/__init__.py raises, rather than
# retrying a misconfigured boot. 1 is the right number: a bad config fails the
# same way in every worker.
preload_app = True
