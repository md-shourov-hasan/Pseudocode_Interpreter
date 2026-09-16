"""
Run session management for the web interface.

The interpreter (engine/interpreter.py) is synchronous: when it hits an
INPUT statement it calls a blocking `input_fn()` and expects a value
back immediately. A web request/response cycle can't block like that,
so each "Run" click gets its own background thread with two queues:

    output_queue  interpreter -> browser   (OUTPUT lines, prompts, errors, done)
    input_queue   browser -> interpreter   (the value typed for an INPUT statement)

The Flask routes in app.py create a RunSession, poll its output_queue
to relay events to the browser, and push submitted INPUT values into
its input_queue.

NFR-3 note: a full implementation should hard-terminate a program that
exceeds the configured execution time (e.g. by running it in a
sandboxed subprocess that can be killed — this also serves NFR-6's
isolation requirement). Python threads cannot be safely force-killed,
so this milestone only *reports* a timeout to the browser once
MAX_EXECUTION_SECONDS is exceeded; the underlying thread is left to
finish or block. No loop constructs exist yet (Milestone 6), so this
gap has no practical impact today — it's flagged here so it isn't
forgotten when loops arrive.
"""

import threading
import queue
import time
import uuid

from engine.lexer import tokenize
from engine.parser import parse
from engine.interpreter import Interpreter
from engine.errors import PseudocodeError

MAX_EXECUTION_SECONDS = 10


class RunSession:
    def __init__(self, source: str):
        self.id = uuid.uuid4().hex
        self.source = source
        self.output_queue: "queue.Queue[dict]" = queue.Queue()
        self.input_queue: "queue.Queue[str]" = queue.Queue()
        self.state = "running"  # running | waiting_for_input | finished | error | timeout
        self.start_time = time.time()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    # ---- called from the interpreter thread ------------------------------

    def _input_fn(self) -> str:
        self.state = "waiting_for_input"
        self.output_queue.put({"type": "waiting"})
        value = self.input_queue.get()  # blocks until provide_input() is called
        self.state = "running"
        return value

    def _output_fn(self, line: str):
        self.output_queue.put({"type": "output", "text": line})

    def _run(self):
        try:
            tokens = tokenize(self.source)
            program = parse(tokens)
            interp = Interpreter(input_fn=self._input_fn, output_fn=self._output_fn)
            interp.run(program)
            self.state = "finished"
            self.output_queue.put({"type": "done"})
        except PseudocodeError as e:
            self.state = "error"
            self.output_queue.put({"type": "error", "line": e.line, "message": e.message})
        except Exception as e:
            # A Python-level crash in the engine itself should never reach the
            # student as a raw traceback (NFR-10) — surface it as a generic
            # internal error instead.
            self.state = "error"
            self.output_queue.put(
                {"type": "error", "line": 0, "message": f"Internal error: {e}"}
            )

    # ---- called from the Flask request thread -----------------------

    def provide_input(self, value: str):
        self.input_queue.put(value)

    def drain_events(self) -> list:
        """Return every event queued since the last call, plus a synthetic
        timeout event if the run has exceeded the execution time limit."""
        events = []
        while True:
            try:
                events.append(self.output_queue.get_nowait())
            except queue.Empty:
                break

        if self.state == "running" and time.time() - self.start_time > MAX_EXECUTION_SECONDS:
            self.state = "timeout"
            events.append(
                {
                    "type": "error",
                    "line": 0,
                    "message": (
                        f"Execution stopped after exceeding the "
                        f"{MAX_EXECUTION_SECONDS}-second time limit "
                        f"(possible infinite loop)."
                    ),
                }
            )
        return events


class SessionStore:
    """In-memory session registry. Fine for a single local test user;
    would need a real backing store for multi-user / production use."""

    def __init__(self):
        self._sessions: dict[str, RunSession] = {}
        self._lock = threading.Lock()

    def create(self, source: str) -> RunSession:
        session = RunSession(source)
        with self._lock:
            self._sessions[session.id] = session
        return session

    def get(self, run_id: str) -> "RunSession | None":
        with self._lock:
            return self._sessions.get(run_id)
