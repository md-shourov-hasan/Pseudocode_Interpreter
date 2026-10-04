import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from engine.errors import PseudocodeError
from engine.interpreter import Interpreter
from engine.lexer import tokenize
from engine.parser import parse
import webapp.run_session as run_session


def parse_src(source):
    return parse(tokenize(source))


def test_interpreter_execution_timeout_stops_infinite_while():
    program = parse_src(
        "DECLARE X : INTEGER\n"
        "WHILE TRUE DO\n"
        "X <- X + 1\n"
        "ENDWHILE"
    )
    with pytest.raises(PseudocodeError, match="Execution exceeded the 0.05-second time limit") as exc_info:
        Interpreter(max_execution_seconds=0.05).run(program)
    assert exc_info.value.line in {2, 3}


def test_interpreter_execution_timeout_stops_infinite_repeat():
    program = parse_src(
        "DECLARE X : INTEGER\n"
        "X <- 0\n"
        "REPEAT\n"
        "X <- X + 1\n"
        "UNTIL FALSE"
    )
    with pytest.raises(PseudocodeError, match="Execution exceeded the 0.05-second time limit"):
        Interpreter(max_execution_seconds=0.05).run(program)


def test_interpreter_execution_timeout_stops_empty_while_body():
    # The loop body is empty, so the loop implementation itself must perform
    # the timeout check rather than relying only on statement dispatch.
    program = parse_src("WHILE TRUE DO\nENDWHILE")
    with pytest.raises(PseudocodeError, match="Execution exceeded"):
        Interpreter(max_execution_seconds=0.05).run(program)


def test_invalid_interpreter_timeout_configuration_is_rejected():
    with pytest.raises(ValueError, match="finite positive number"):
        Interpreter(max_execution_seconds=0)


def _wait_for_state(session, target, timeout=3.0):
    deadline = time.monotonic() + timeout
    collected = []
    while time.monotonic() < deadline:
        collected.extend(session.drain_events())
        if session.state == target:
            collected.extend(session.drain_events())
            return collected
        time.sleep(0.03)
    collected.extend(session.drain_events())
    assert session.state == target
    return collected


def test_web_session_hard_terminates_infinite_loop(monkeypatch):
    monkeypatch.setattr(run_session, "MAX_EXECUTION_SECONDS", 0.25)
    session = run_session.RunSession(
        "DECLARE X : INTEGER\n"
        "WHILE TRUE DO\n"
        "X <- X + 1\n"
        "ENDWHILE"
    )
    try:
        events = _wait_for_state(session, "timeout")
        assert any(event["type"] == "error" and "possible infinite loop" in event["message"] for event in events)
        assert session.process.is_alive() is False
    finally:
        if session.process.is_alive():
            session.process.terminate()
            session.process.join(timeout=1)


def test_web_session_pauses_timeout_while_waiting_for_input(monkeypatch):
    monkeypatch.setattr(run_session, "MAX_EXECUTION_SECONDS", 0.2)
    session = run_session.RunSession(
        "DECLARE Answer : INTEGER\n"
        "INPUT Answer\n"
        "OUTPUT Answer"
    )
    try:
        _wait_for_state(session, "waiting_for_input")
        time.sleep(0.35)
        session.drain_events()
        assert session.state == "waiting_for_input"
        assert session.provide_input("7") is True
        events = _wait_for_state(session, "finished")
        events.extend(session.drain_events())
        assert {event.get("text") for event in events if event.get("type") == "output"} == {"7"}
    finally:
        if session.process.is_alive():
            session.process.terminate()
            session.process.join(timeout=1)
