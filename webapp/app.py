"""
Flask web interface for the IGCSE Pseudocode Compiler (Milestone 12,
scoped down to local testing per the current request).

Routes:
    GET  /                      the editor page
    POST /api/run               start executing a program, returns {run_id}
    GET  /api/run/<id>/poll     drain queued events (output/waiting/error/done)
    POST /api/run/<id>/input    submit a value for a pending INPUT statement

Run with:
    python webapp/app.py
then open http://127.0.0.1:5000

INPUT handling (FR-4.1, Section 4.1): each Run starts a background
thread (see run_session.py) that blocks on a queue when it hits an
INPUT statement. The browser polls for events and shows a live prompt
when the program is waiting, so INPUT behaves interactively rather
than requiring every value to be supplied up front.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, render_template, request, jsonify

from webapp.run_session import SessionStore

app = Flask(__name__)
sessions = SessionStore()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/run", methods=["POST"])
def start_run():
    data = request.get_json(silent=True) or {}
    source = data.get("source", "")
    if not source.strip():
        return jsonify({"error": "There's no pseudocode to run."}), 400
    session = sessions.create(source)
    return jsonify({"run_id": session.id})


@app.route("/api/run/<run_id>/poll")
def poll_run(run_id):
    session = sessions.get(run_id)
    if session is None:
        return jsonify({"error": "Unknown run — it may have expired."}), 404
    return jsonify({"state": session.state, "events": session.drain_events()})


@app.route("/api/run/<run_id>/input", methods=["POST"])
def submit_input(run_id):
    session = sessions.get(run_id)
    if session is None:
        return jsonify({"error": "Unknown run — it may have expired."}), 404
    if session.state != "waiting_for_input":
        return jsonify({"error": "This program isn't waiting for input right now."}), 409
    data = request.get_json(silent=True) or {}
    if not session.provide_input(data.get("value", "")):
        return jsonify({"error": "This program is no longer waiting for input."}), 409
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="127.0.0.1", port=port, debug=True)
