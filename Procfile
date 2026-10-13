# AquaGuard AI — process definition
#
# Render, Railway and Heroku all read this file to learn how to start the app.
# The command runs gunicorn with the project's own configuration file
# (gunicorn.conf.py), which owns the bind address, worker count and timeouts.
#
#   gunicorn -c gunicorn.conf.py wsgi:app
#
# `wsgi:app` is the production WSGI entrypoint in backend/wsgi.py. Render runs
# this from the repository root, so the working directory is set in render.yaml
# (rootDir: backend); on Railway/Heroku set "Root Directory" to `backend`.
#
# NOTE: the port is taken from $PORT by the platform. gunicorn.conf.py binds
# 0.0.0.0:5000 by default and reads GUNICORN_BIND; Render injects PORT, so bind
# to it explicitly below. The shell expansion is handled by the platform's shell.
web: gunicorn -c gunicorn.conf.py --bind 0.0.0.0:$PORT wsgi:app
