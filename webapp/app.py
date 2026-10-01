"""
Flask web interface for the IGCSE Pseudocode Compiler (Milestone 12,
scoped down to local testing per the current request).

Routes:
    GET  /                      the editor page
    POST /api/run               start executing a program, returns {run_id}
    GET  /api/run/<id>/poll     drain queued events (output/waiting/error/done)
    POST /api/run/<id>/input    submit a value for a pending INPUT statement
    POST /api/run/<id>/cancel   stop a run (Run pressed again, or page closed)

Run with:
    python webapp/app.py
then open http://127.0.0.1:5000

INPUT handling (FR-4.1, Section 4.1): each Run starts a background
worker process (see run_session.py) that blocks on a queue when it hits
an INPUT statement. The browser polls for events and shows a live prompt
when the program is waiting, so INPUT behaves interactively rather
than requiring every value to be supplied up front.

The app is public and embedded as an iframe on the SudoLab site, so the
run limits in run_session.py apply per client. The client is identified
by IP address, because the iframe is a third-party context where cookies
are often blocked.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, render_template, request, jsonify
from werkzeug.middleware.proxy_fix import ProxyFix

from webapp.run_session import RunLimitError, SessionStore

MAX_SOURCE_CHARS = 100_000
MAX_INPUT_CHARS = 10_000
MAX_POLL_WAIT_SECONDS = 2.0

app = Flask(__name__)
# Rejects oversized request bodies before they are read (see the 413
# handler below). Comfortably above MAX_SOURCE_CHARS of UTF-8 in JSON.
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024

# Behind Render's proxy every request arrives from the proxy's address; the
# real client is in X-Forwarded-For. Only trust as many hops as there really
# are proxies, or a client could spoof its address to dodge the per-client
# run limits. Defaults to 1 on Render (which sets RENDER), 0 elsewhere.
_trusted_proxies = int(os.environ.get("TRUSTED_PROXY_COUNT", "1" if os.environ.get("RENDER") else "0"))
if _trusted_proxies > 0:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=_trusted_proxies)

sessions = SessionStore()


def _client_key() -> str:
    return request.remote_addr or "unknown"


@app.errorhandler(413)
def request_too_large(_error):
    return jsonify({"error": "This program is too large to run."}), 413


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/health")
def health():
    """Lightweight endpoint the parent SudoLab site polls to detect when
    this Render service has finished waking up from a cold start."""
    resp = jsonify({"status": "ok"})
    # Explicit CORS header: this route is fetched cross-origin from the
    # SudoLab site while this app itself is still asleep/booting, so it
    # must not depend on any session or app-level auth.
    resp.headers["Access-Control-Allow-Origin"] = os.environ.get(
        "SUDOLAB_ORIGIN", "*"
    )
    return resp, 200


@app.route("/api/run", methods=["POST"])
def start_run():
    data = request.get_json(silent=True) or {}
    source = data.get("source", "")
    if not isinstance(source, str):
        return jsonify({"error": "The program must be sent as text."}), 400
    if not source.strip():
        return jsonify({"error": "There's no pseudocode to run."}), 400
    if len(source) > MAX_SOURCE_CHARS:
        return jsonify(
            {"error": f"This program is too long to run (the limit is {MAX_SOURCE_CHARS:,} characters)."}
        ), 413
    try:
        session = sessions.create(source, client_key=_client_key())
    except RunLimitError as e:
        resp = jsonify({"error": e.message})
        resp.headers["Retry-After"] = "5"
        return resp, e.status
    return jsonify({"run_id": session.id})


@app.route("/api/run/<run_id>/poll")
def poll_run(run_id):
    session = sessions.get(run_id)
    if session is None:
        return jsonify({"error": "Unknown run — it may have expired."}), 404
    session.touch()
    # ?wait=<seconds> long-polls (see RunSession.drain_events), capped so a
    # request never ties up one of gunicorn's threads for long.
    wait = min(max(request.args.get("wait", 0, type=float), 0), MAX_POLL_WAIT_SECONDS)
    events = session.drain_events(wait=wait)
    return jsonify({"state": session.state, "events": events})


@app.route("/api/run/<run_id>/input", methods=["POST"])
def submit_input(run_id):
    session = sessions.get(run_id)
    if session is None:
        return jsonify({"error": "Unknown run — it may have expired."}), 404
    session.touch()
    if session.state != "waiting_for_input":
        return jsonify({"error": "This program isn't waiting for input right now."}), 409
    data = request.get_json(silent=True) or {}
    value = data.get("value", "")
    if not isinstance(value, str):
        return jsonify({"error": "INPUT values must be sent as text."}), 400
    if len(value) > MAX_INPUT_CHARS:
        return jsonify(
            {"error": f"That value is too long (the limit is {MAX_INPUT_CHARS:,} characters)."}
        ), 413
    if not session.provide_input(value):
        return jsonify({"error": "This program is no longer waiting for input."}), 409
    return jsonify({"ok": True})


@app.route("/api/run/<run_id>/cancel", methods=["POST"])
def cancel_run(run_id):
    # Also sent with navigator.sendBeacon when the page is closed, so it
    # ignores the request body entirely.
    session = sessions.get(run_id)
    if session is None:
        return jsonify({"error": "Unknown run — it may have expired."}), 404
    session.cancel()
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="127.0.0.1", port=port, debug=True)
