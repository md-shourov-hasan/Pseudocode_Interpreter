"""
Gunicorn settings, picked up automatically when gunicorn is started from
the repository root (as the Procfile and Render's start command do).

Run sessions live in memory in ONE process (webapp/run_session.py's
SessionStore), so there must be exactly one worker process: with several,
a browser's poll could reach a worker that never heard of its run. This
file overrides gunicorn's WEB_CONCURRENCY-based default, but an explicit
``--workers``/``-w`` on the command line would still override it.

Concurrency comes from threads instead. Every request is short (the
browser polls), and each program runs in its own child process, not in a
request thread.
"""

workers = 1
worker_class = "gthread"
threads = 16
timeout = 60
