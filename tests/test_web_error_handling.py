"""
Web server protection: run lifecycle limits (cancel, abandoned runs, INPUT
wait limit), output cap, concurrency / rate limits, request validation.
"""

import time

import pytest

import webapp.run_session as run_session
from webapp.app import app


def _wait_for_state(session, targets, timeout=15.0):
    if isinstance(targets, str):
        targets = {targets}
    collected = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        collected.extend(session.drain_events())
        if session.state in targets:
            time.sleep(0.05)
            collected.extend(session.drain_events())
            return collected
        session.touch()
        time.sleep(0.03)
    collected.extend(session.drain_events())
    assert session.state in targets
    return collected


def _cleanup(session):
    if session.process.is_alive():
        session.process.terminate()
        session.process.join(timeout=1)


WAITING_PROGRAM = "DECLARE A : INTEGER\nINPUT A\nOUTPUT A"


# ---- run lifecycle ---------------------------------------------------


def test_cancel_stops_worker_waiting_for_input():
    session = run_session.RunSession(WAITING_PROGRAM)
    try:
        _wait_for_state(session, "waiting_for_input")
        assert session.cancel() is True
        assert session.state == "cancelled"
        assert session.process.is_alive() is False
        assert session.cancel() is False
    finally:
        _cleanup(session)


def test_abandoned_run_is_stopped(monkeypatch):
    monkeypatch.setattr(run_session, "ABANDONED_RUN_SECONDS", 0.5)
    session = run_session.RunSession(WAITING_PROGRAM)
    try:
        _wait_for_state(session, "waiting_for_input")
        time.sleep(1.0)  # nobody polls (touch) any more
        assert session.state == "cancelled"
        assert session.process.is_alive() is False
    finally:
        _cleanup(session)


def test_input_wait_limit(monkeypatch):
    monkeypatch.setattr(run_session, "MAX_INPUT_WAIT_SECONDS", 0.4)
    session = run_session.RunSession(WAITING_PROGRAM)
    try:
        events = _wait_for_state(session, "timeout")
        assert any("waiting" in e.get("message", "") for e in events if e["type"] == "error")
        assert session.process.is_alive() is False
    finally:
        _cleanup(session)


def test_second_input_before_resume_is_refused():
    session = run_session.RunSession(
        "DECLARE A : INTEGER\nDECLARE B : INTEGER\nINPUT A\nINPUT B\nOUTPUT A, B"
    )
    try:
        _wait_for_state(session, "waiting_for_input")
        assert session.provide_input("1") is True
        assert session.provide_input("2") is False  # double-click on Send
        _wait_for_state(session, "waiting_for_input")
        assert session.provide_input("3") is True
        events = _wait_for_state(session, "finished")
        assert [e["text"] for e in events if e["type"] == "output"] == ["13"]
    finally:
        _cleanup(session)


def test_output_flood_is_capped(monkeypatch):
    monkeypatch.setattr(run_session, "MAX_OUTPUT_LINES", 50)
    session = run_session.RunSession("WHILE TRUE DO\nOUTPUT \"x\"\nENDWHILE")
    try:
        events = _wait_for_state(session, "error")
        assert sum(1 for e in events if e["type"] == "output") == 50
        error = [e for e in events if e["type"] == "error"][-1]
        assert "too much output" in error["message"]
        assert error["line"] == 2
    finally:
        _cleanup(session)


# ---- store limits ----------------------------------------------------


@pytest.fixture
def store():
    s = run_session.SessionStore()
    yield s
    for session in list(s._sessions.values()):
        session.cancel()
        _cleanup(session)


def test_per_client_active_limit(monkeypatch, store):
    monkeypatch.setattr(run_session, "MAX_ACTIVE_RUNS_PER_CLIENT", 2)
    store.create(WAITING_PROGRAM, client_key="a")
    store.create(WAITING_PROGRAM, client_key="a")
    with pytest.raises(run_session.RunLimitError) as exc:
        store.create(WAITING_PROGRAM, client_key="a")
    assert exc.value.status == 429
    store.create(WAITING_PROGRAM, client_key="b")  # another client is unaffected


def test_global_active_limit(monkeypatch, store):
    monkeypatch.setattr(run_session, "MAX_ACTIVE_RUNS", 2)
    store.create(WAITING_PROGRAM, client_key="a")
    store.create(WAITING_PROGRAM, client_key="b")
    with pytest.raises(run_session.RunLimitError) as exc:
        store.create(WAITING_PROGRAM, client_key="c")
    assert exc.value.status == 503


def test_cancelled_run_frees_its_slot(monkeypatch, store):
    monkeypatch.setattr(run_session, "MAX_ACTIVE_RUNS_PER_CLIENT", 1)
    first = store.create(WAITING_PROGRAM, client_key="a")
    first.cancel()
    store.create(WAITING_PROGRAM, client_key="a")


def test_run_start_rate_limit(monkeypatch, store):
    monkeypatch.setattr(run_session, "MAX_RUN_STARTS_PER_MINUTE", 2)
    for _ in range(2):
        store.create('OUTPUT "hi"', client_key="a")
    with pytest.raises(run_session.RunLimitError) as exc:
        store.create('OUTPUT "hi"', client_key="a")
    assert exc.value.status == 429


def test_ended_runs_are_pruned(monkeypatch, store):
    monkeypatch.setattr(run_session, "RESULT_RETENTION_SECONDS", 0.1)
    first = store.create('OUTPUT "hi"', client_key="a")
    _wait_for_state(first, "finished")
    time.sleep(0.2)
    store.create('OUTPUT "hi"', client_key="a")
    assert store.get(first.id) is None


# ---- HTTP layer --------------------------------------------------------


@pytest.fixture
def client():
    app.config["TESTING"] = True
    return app.test_client()


def test_rejects_non_string_source(client):
    res = client.post("/api/run", json={"source": ["OUTPUT 1"]})
    assert res.status_code == 400
    assert "error" in res.get_json()


def test_rejects_oversized_source(client):
    res = client.post("/api/run", json={"source": "OUTPUT 1\n" * 20_000})
    assert res.status_code == 413
    assert "error" in res.get_json()


def test_oversized_body_gets_json_error(client):
    res = client.post("/api/run", data="x" * (2 * 1024 * 1024), content_type="application/json")
    assert res.status_code == 413
    assert "error" in res.get_json()


def test_unknown_run_endpoints_404(client):
    assert client.get("/api/run/nope/poll").status_code == 404
    assert client.post("/api/run/nope/input", json={"value": "1"}).status_code == 404
    assert client.post("/api/run/nope/cancel").status_code == 404


def test_input_validation_and_cancel_over_http(client):
    run_id = client.post("/api/run", json={"source": WAITING_PROGRAM}).get_json()["run_id"]
    deadline = time.monotonic() + 15
    while client.get(f"/api/run/{run_id}/poll").get_json()["state"] != "waiting_for_input":
        assert time.monotonic() < deadline
        time.sleep(0.05)
    assert client.post(f"/api/run/{run_id}/input", json={"value": 5}).status_code == 400
    assert client.post(f"/api/run/{run_id}/input", json={"value": "9" * 20_000}).status_code == 413
    assert client.post(f"/api/run/{run_id}/cancel").status_code == 200
    assert client.get(f"/api/run/{run_id}/poll").get_json()["state"] == "cancelled"


def test_long_poll_waits_for_events_then_returns():
    session = run_session.RunSession(WAITING_PROGRAM)
    try:
        _wait_for_state(session, "waiting_for_input")
        started = time.monotonic()
        assert session.drain_events(wait=0.3) == []  # nothing new: waits, then returns
        assert time.monotonic() - started >= 0.25
        session.provide_input("4")
        started = time.monotonic()
        events = session.drain_events(wait=5)  # returns as soon as output arrives
        assert time.monotonic() - started < 4
        events += _wait_for_state(session, "finished")
        assert [e["text"] for e in events if e["type"] == "output"] == ["4"]
    finally:
        _cleanup(session)


def test_poll_wait_parameter_is_capped(client):
    run_id = client.post("/api/run", json={"source": WAITING_PROGRAM}).get_json()["run_id"]
    try:
        started = time.monotonic()
        client.get(f"/api/run/{run_id}/poll?wait=1000")
        assert time.monotonic() - started < 15
    finally:
        client.post(f"/api/run/{run_id}/cancel")
