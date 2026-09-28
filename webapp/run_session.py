"""
Run session management for the web interface.

Each browser "Run" executes inside a dedicated child process. This is
important for Milestone 11: Python threads cannot be safely force-killed,
but a worker process can be terminated by its parent when a program exceeds
MAX_EXECUTION_SECONDS.

There are two IPC queues:
    output_queue  worker -> parent -> browser (OUTPUT, waiting, errors, done)
    input_queue   browser -> parent -> worker (values for INPUT statements)

The timeout clock measures active execution time. It is paused while the
program is blocked waiting for browser INPUT, because waiting for a student
to type is not an infinite loop and should not consume the program's runtime
budget. Once input is supplied, a fresh execution segment begins.
"""

import multiprocessing
import os
import queue
import shutil
import tempfile
import threading
import time
import uuid

from engine.lexer import tokenize
from engine.parser import parse
from engine.interpreter import Interpreter
from engine.errors import PseudocodeError


def _read_timeout_setting() -> float:
    raw = os.environ.get("PSEUDOCODE_MAX_EXECUTION_SECONDS", "10")
    try:
        value = float(raw)
    except ValueError:
        value = 10.0
    return value if value > 0 else 10.0


MAX_EXECUTION_SECONDS = _read_timeout_setting()


def _worker_main(source: str, output_queue, input_queue):
    """Parse and execute one program inside an isolated child process.

    FR-9.1 - FR-9.4 (file handling) read and write real files, so this
    worker's OPENFILE/READFILE/WRITEFILE/CLOSEFILE calls are pointed at
    a fresh temporary directory that exists only for this one run and is
    always removed afterwards -- satisfying NFR-4 ("shall not allow a
    pseudocode program to access arbitrary locations on the host file
    system") and NFR-6 ("each program's execution shall be isolated")
    without the engine itself needing to know it's running inside a web
    backend at all.
    """

    def input_fn() -> str:
        output_queue.put({"type": "waiting"})
        value = input_queue.get()
        output_queue.put({"type": "resumed"})
        return value

    def output_fn(line: str):
        output_queue.put({"type": "output", "text": line})

    file_root = tempfile.mkdtemp(prefix="pseudocode-run-")
    try:
        # Startup time (including multiprocessing spawn/import overhead) is
        # not part of the user program's execution budget.
        output_queue.put({"type": "started"})
        tokens = tokenize(source)
        program = parse(tokens)
        interp = Interpreter(input_fn=input_fn, output_fn=output_fn, file_root=file_root)
        interp.run(program)
        output_queue.put({"type": "done"})
    except PseudocodeError as e:
        output_queue.put(
            {
                "type": "error",
                "line": e.line,
                "message": e.message,
                "column": e.column,
                "end_column": e.end_column,
            }
        )
    except Exception:
        # Keep the web boundary strict even if a future engine change raises
        # something outside the normal PseudocodeError contract.
        output_queue.put(
            {
                "type": "error",
                "line": 0,
                "message": "The program could not be completed because the compiler encountered an unexpected problem.",
            }
        )
    finally:
        shutil.rmtree(file_root, ignore_errors=True)


class RunSession:
    def __init__(self, source: str):
        self.id = uuid.uuid4().hex
        self.source = source
        self.output_queue: "queue.Queue[dict]" = queue.Queue()
        self.state = "running"  # running | waiting_for_input | finished | error | timeout
        self.start_time = time.monotonic()

        self._ctx = multiprocessing.get_context("spawn")
        self.input_queue = self._ctx.Queue()
        self._worker_output_queue = self._ctx.Queue()
        self._worker_input_queue = self.input_queue
        self._lock = threading.Lock()
        # The worker sends a ``started`` event once it is actually executing.
        # This avoids counting multiprocessing startup/import overhead toward
        # the user's pseudocode execution budget.
        self._execution_segment_started_at = None
        self._process = self._ctx.Process(
            target=_worker_main,
            args=(self.source, self._worker_output_queue, self._worker_input_queue),
            daemon=True,
        )
        self.process = self._process  # public alias useful to tests/diagnostics

        self._reader_thread = threading.Thread(target=self._read_worker_events, daemon=True)
        self._watchdog_thread = threading.Thread(target=self._watchdog, daemon=True)

        self._process.start()
        self._reader_thread.start()
        self._watchdog_thread.start()

    # ---- worker event handling ------------------------------------------

    def _read_worker_events(self):
        while True:
            try:
                event = self._worker_output_queue.get(timeout=0.1)
            except queue.Empty:
                if not self._process.is_alive():
                    with self._lock:
                        if self.state in {"running", "waiting_for_input"}:
                            self.state = "error"
                            self.output_queue.put(
                                {
                                    "type": "error",
                                    "line": 0,
                                    "message": "The compiler process stopped unexpectedly before the program finished.",
                                }
                            )
                    return
                continue

            event_type = event.get("type")
            with self._lock:
                if self.state == "timeout":
                    # The watchdog owns the terminal state after a hard kill.
                    continue

                if event_type == "started":
                    self.state = "running"
                    self._execution_segment_started_at = time.monotonic()
                    continue

                if event_type == "waiting":
                    self.state = "waiting_for_input"
                    self._execution_segment_started_at = None
                    self.output_queue.put(event)
                    continue

                if event_type == "resumed":
                    self.state = "running"
                    self._execution_segment_started_at = time.monotonic()
                    continue

                if event_type == "output":
                    self.state = "running"
                    self.output_queue.put(event)
                    continue

                if event_type == "done":
                    self.state = "finished"
                    self.output_queue.put(event)
                    self._reap_worker()
                    return

                if event_type == "error":
                    self.state = "error"
                    self.output_queue.put(event)
                    self._reap_worker()
                    return

    # ---- hard timeout ----------------------------------------------------

    def _watchdog(self):
        while True:
            time.sleep(0.05)
            with self._lock:
                if self.state in {"finished", "error", "timeout"}:
                    return
                segment_started_at = self._execution_segment_started_at
                process_alive = self._process.is_alive()

                if not process_alive:
                    # The reader thread normally consumes the terminal event.
                    # If the worker exited without one, surface a safe error.
                    if self.state == "running":
                        self.state = "error"
                        self.output_queue.put(
                            {
                                "type": "error",
                                "line": 0,
                                "message": "The compiler process stopped unexpectedly before the program finished.",
                            }
                        )
                    return

                if segment_started_at is None:
                    # Program is waiting for INPUT; active timeout is paused.
                    continue

                if time.monotonic() - segment_started_at >= MAX_EXECUTION_SECONDS:
                    # Kill first, then publish the terminal state. That keeps
                    # the observable timeout state synchronized with the hard
                    # termination of the worker process.
                    self._terminate_worker()
                    self.state = "timeout"
                    self.output_queue.put(
                        {
                            "type": "error",
                            "line": 0,
                            "message": (
                                f"Execution stopped after exceeding the "
                                f"{MAX_EXECUTION_SECONDS:g}-second time limit "
                                f"(possible infinite loop)."
                            ),
                        }
                    )
                    return

    def _terminate_worker(self):
        if self._process.is_alive():
            self._process.terminate()
        self._process.join(timeout=1.0)
        if self._process.is_alive():
            # terminate() is expected to be enough for a normal worker. On a
            # stubborn platform/process state, kill() provides the stronger
            # hard-stop guarantee available in modern Python.
            kill = getattr(self._process, "kill", None)
            if kill is not None:
                kill()
                self._process.join(timeout=1.0)

    def _reap_worker(self):
        if self._process.is_alive():
            self._process.join(timeout=0.2)

    # ---- called from the Flask request thread ---------------------------

    def provide_input(self, value: str) -> bool:
        with self._lock:
            if self.state != "waiting_for_input":
                return False
            self._worker_input_queue.put(value)
            return True

    def drain_events(self) -> list:
        """Return every browser event queued since the previous poll."""
        events = []
        while True:
            try:
                events.append(self.output_queue.get_nowait())
            except queue.Empty:
                break
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
