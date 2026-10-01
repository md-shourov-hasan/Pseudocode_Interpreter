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

Server-protection limits (the app is public, embedded as an iframe on the
SudoLab site, and runs on a small instance where every Run is a whole
process):

* A run nobody has polled for ABANDONED_RUN_SECONDS (the tab was closed or
  navigated away) is stopped, and so is a run that has waited for INPUT
  longer than MAX_INPUT_WAIT_SECONDS -- otherwise a program parked at an
  INPUT prompt would keep its worker process alive forever, since the
  execution timeout is paused while waiting.
* Finished runs are forgotten RESULT_RETENTION_SECONDS after they end.
* SessionStore caps how many runs can be active at once, overall and per
  client, and how quickly one client can start new runs.
* The worker stops a program once its OUTPUT exceeds MAX_OUTPUT_LINES or
  MAX_OUTPUT_CHARS, so a tight OUTPUT loop can't pile millions of events
  into the parent's memory, and (on POSIX) caps its own address space at
  WORKER_MEMORY_LIMIT_MB so one program can't exhaust the host's memory.

Every limit can be tuned with the environment variable of the same name
prefixed by ``PSEUDOCODE_`` (e.g. ``PSEUDOCODE_MAX_ACTIVE_RUNS``).
"""

import collections
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


def _read_number_setting(name: str, default: float) -> float:
    raw = os.environ.get(f"PSEUDOCODE_{name}", str(default))
    try:
        value = float(raw)
    except ValueError:
        value = default
    return value if value > 0 else default


def _read_timeout_setting() -> float:
    return _read_number_setting("MAX_EXECUTION_SECONDS", 10.0)


MAX_EXECUTION_SECONDS = _read_timeout_setting()

# Browsers throttle timers in background tabs (Chrome down to one wake-up a
# minute after a tab has been hidden for 5 minutes), so a live but hidden
# tab may poll only about once a minute. This must stay comfortably above
# that, or a student who switches tabs while at an INPUT prompt loses the run.
ABANDONED_RUN_SECONDS = _read_number_setting("ABANDONED_RUN_SECONDS", 150.0)
# A run waiting at INPUT costs no CPU but still holds one of the few
# MAX_ACTIVE_RUNS slots, so this is kept fairly short.
MAX_INPUT_WAIT_SECONDS = _read_number_setting("MAX_INPUT_WAIT_SECONDS", 300.0)
RESULT_RETENTION_SECONDS = _read_number_setting("RESULT_RETENTION_SECONDS", 120.0)

# Defaults are sized for Render's free plan (512 MB RAM, 0.1 CPU), measured
# on Linux: the web server process uses ~36 MB and an idle worker ~18 MB.
# MAX_ACTIVE_RUNS * WORKER_MEMORY_LIMIT_MB must stay below the instance's
# RAM minus ~100 MB for the server, or a few memory-hungry programs running
# at once could get the whole instance killed: 6 * 64 MB + ~60 MB < 512 MB.
# On a bigger plan, raise both through the environment.
MAX_ACTIVE_RUNS = int(_read_number_setting("MAX_ACTIVE_RUNS", 6))
MAX_ACTIVE_RUNS_PER_CLIENT = int(_read_number_setting("MAX_ACTIVE_RUNS_PER_CLIENT", 3))
MAX_RUN_STARTS_PER_MINUTE = int(_read_number_setting("MAX_RUN_STARTS_PER_MINUTE", 30))

MAX_OUTPUT_LINES = int(_read_number_setting("MAX_OUTPUT_LINES", 5000))
MAX_OUTPUT_CHARS = int(_read_number_setting("MAX_OUTPUT_CHARS", 500_000))
# Address-space cap, not RSS. A worker needs ~41 MB of address space for a
# demanding student program (50,000-element array, 100x100 grid, 199-deep
# recursion) and fails to start below ~40 MB, so 64 MB leaves headroom.
WORKER_MEMORY_LIMIT_MB = int(_read_number_setting("WORKER_MEMORY_LIMIT_MB", 64))
# Workers run at a lower CPU priority than the web server, so on a tiny
# CPU share a few infinite loops can't starve the process answering
# everyone's polls. They still get all the CPU nothing else is using.
WORKER_NICE_INCREMENT = 10

ACTIVE_STATES = frozenset({"running", "waiting_for_input"})
TERMINAL_STATES = frozenset({"finished", "error", "timeout", "cancelled"})


class RunLimitError(Exception):
    """Raised by SessionStore.create when a new run would exceed a limit.
    ``status`` is the HTTP status the web layer should answer with."""

    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.message = message
        self.status = status


def _limit_worker_memory(limit_mb: int):
    """Cap this worker's address space so a runaway program (e.g. a STRING
    doubled in a loop) fails with an ordinary out-of-memory error inside the
    worker instead of exhausting the host. Only POSIX has RLIMIT_AS; local
    Windows runs simply go without it."""
    try:
        import resource
    except ImportError:
        return
    limit = limit_mb * 1024 * 1024
    try:
        _, hard = resource.getrlimit(resource.RLIMIT_AS)
        if hard != resource.RLIM_INFINITY:
            limit = min(limit, hard)
        resource.setrlimit(resource.RLIMIT_AS, (limit, hard))
    except (ValueError, OSError):
        pass


def _worker_main(source: str, output_queue, input_queue, limits=None):
    """Parse and execute one program inside an isolated child process.

    FR-9.1 - FR-9.4 (file handling) read and write real files, so this
    worker's OPENFILE/READFILE/WRITEFILE/CLOSEFILE calls are pointed at
    a fresh temporary directory that exists only for this one run and is
    always removed afterwards -- satisfying NFR-4 ("shall not allow a
    pseudocode program to access arbitrary locations on the host file
    system") and NFR-6 ("each program's execution shall be isolated")
    without the engine itself needing to know it's running inside a web
    backend at all.

    ``limits`` is passed in explicitly rather than read from this module's
    globals, because a spawned child re-imports the module and would not
    see values the parent changed at runtime.
    """
    limits = limits or {}
    max_lines = limits.get("max_output_lines", MAX_OUTPUT_LINES)
    max_chars = limits.get("max_output_chars", MAX_OUTPUT_CHARS)
    _limit_worker_memory(limits.get("memory_limit_mb", WORKER_MEMORY_LIMIT_MB))
    if hasattr(os, "nice"):  # POSIX only
        try:
            os.nice(WORKER_NICE_INCREMENT)
        except OSError:
            pass

    interp = None
    output_used = {"lines": 0, "chars": 0}

    def input_fn() -> str:
        output_queue.put({"type": "waiting"})
        value = input_queue.get()
        output_queue.put({"type": "resumed"})
        return value

    def output_fn(line: str):
        output_used["lines"] += 1
        output_used["chars"] += len(line)
        if output_used["lines"] > max_lines or output_used["chars"] > max_chars:
            raise PseudocodeError(
                interp._current_line if interp is not None else 0,
                f"The program was stopped because it produced too much output "
                f"(the limit is {max_lines:,} lines or {max_chars:,} characters). "
                f"Check for a loop that OUTPUTs more than intended.",
            )
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
    except MemoryError:
        output_queue.put(
            {
                "type": "error",
                "line": 0,
                "message": "The program was stopped because it used too much memory.",
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


_context = None
_context_lock = threading.Lock()


def _process_context():
    """The multiprocessing context workers start from.

    Where available (Linux), a fork server with the engine already imported:
    each Run is then a cheap fork of that small, single-threaded server
    instead of a brand-new Python interpreter, which on a 0.1-CPU instance
    takes 1.5-2 seconds per Run. The fork server, not this multi-threaded
    web process, is what gets forked, so it's safe to use here. Windows has
    no fork, so it falls back to spawn.
    """
    global _context
    with _context_lock:
        if _context is None:
            if "forkserver" in multiprocessing.get_all_start_methods():
                _context = multiprocessing.get_context("forkserver")
                _context.set_forkserver_preload(["webapp.run_session"])
            else:
                _context = multiprocessing.get_context("spawn")
        return _context


class RunSession:
    def __init__(self, source: str, client_key: str = ""):
        self.id = uuid.uuid4().hex
        self.source = source
        self.client_key = client_key
        self.output_queue: "queue.Queue[dict]" = queue.Queue()
        self.state = "running"  # running | waiting_for_input | finished | error | timeout | cancelled
        self.start_time = time.monotonic()
        # Last time the browser polled or sent input; a run nobody is
        # watching any more is stopped by the watchdog (ABANDONED_RUN_SECONDS).
        self.last_seen = self.start_time
        self.finished_at = None
        self._waiting_since = None

        self._ctx = _process_context()
        self.input_queue = self._ctx.Queue()
        self._worker_output_queue = self._ctx.Queue()
        self._worker_input_queue = self.input_queue
        self._lock = threading.Lock()
        # The worker sends a ``started`` event once it is actually executing.
        # This avoids counting multiprocessing startup/import overhead toward
        # the user's pseudocode execution budget.
        self._execution_segment_started_at = None
        limits = {
            "max_output_lines": MAX_OUTPUT_LINES,
            "max_output_chars": MAX_OUTPUT_CHARS,
            "memory_limit_mb": WORKER_MEMORY_LIMIT_MB,
        }
        self._process = self._ctx.Process(
            target=_worker_main,
            args=(self.source, self._worker_output_queue, self._worker_input_queue, limits),
            daemon=True,
        )
        self.process = self._process  # public alias useful to tests/diagnostics

        self._reader_thread = threading.Thread(target=self._read_worker_events, daemon=True)
        self._watchdog_thread = threading.Thread(target=self._watchdog, daemon=True)

        self._process.start()
        self._reader_thread.start()
        self._watchdog_thread.start()

    @property
    def is_active(self) -> bool:
        return self.state in ACTIVE_STATES

    # ---- worker event handling ------------------------------------------

    def _read_worker_events(self):
        """The one place that turns the worker's exit into a final state.
        (The watchdog deliberately leaves a dead worker to this thread.)"""
        while True:
            try:
                event = self._worker_output_queue.get(timeout=0.1)
            except queue.Empty:
                if self._process.is_alive():
                    continue
                # The worker may have sent its final event and exited just
                # after the get() above timed out, so look once more before
                # calling it a crash. On a slow, CPU-throttled host this gap
                # is wide enough to hit regularly.
                try:
                    event = self._worker_output_queue.get(timeout=1.0)
                except queue.Empty:
                    with self._lock:
                        if self.state in ACTIVE_STATES:
                            self._set_terminal("error")
                            self.output_queue.put(
                                {
                                    "type": "error",
                                    "line": 0,
                                    "message": "The compiler process stopped unexpectedly before the program finished.",
                                }
                            )
                    return
                except (OSError, ValueError, EOFError):
                    return
            except (OSError, ValueError, EOFError):
                # The queue was closed underneath us (see close()).
                return

            event_type = event.get("type")
            with self._lock:
                if self.state in TERMINAL_STATES:
                    # A stop (timeout, cancel, abandonment) owns the terminal
                    # state after a hard kill; drop anything still in flight.
                    continue

                if event_type == "started":
                    self.state = "running"
                    self._execution_segment_started_at = time.monotonic()
                    continue

                if event_type == "waiting":
                    self.state = "waiting_for_input"
                    self._execution_segment_started_at = None
                    self._waiting_since = time.monotonic()
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
                    self._set_terminal("finished")
                    self.output_queue.put(event)
                    self._reap_worker()
                    return

                if event_type == "error":
                    self._set_terminal("error")
                    self.output_queue.put(event)
                    self._reap_worker()
                    return

    def _set_terminal(self, state: str):
        """Caller holds self._lock."""
        self.state = state
        self.finished_at = time.monotonic()
        self._waiting_since = None

    # ---- hard timeout ----------------------------------------------------

    def _watchdog(self):
        while True:
            time.sleep(0.05)
            with self._lock:
                if self.state in TERMINAL_STATES:
                    return
                segment_started_at = self._execution_segment_started_at
                process_alive = self._process.is_alive()
                now = time.monotonic()

                if not process_alive:
                    # The reader thread decides how a dead worker ended:
                    # its final event may still be in flight, so declaring
                    # a crash here would race with it.
                    return

                if now - self.last_seen >= ABANDONED_RUN_SECONDS:
                    # Nobody is polling any more: the tab was closed or the
                    # SudoLab page navigated away from the iframe.
                    self._stop_locked("cancelled", "The program was stopped because its page was closed.")
                    return

                if (
                    self._waiting_since is not None
                    and now - self._waiting_since >= MAX_INPUT_WAIT_SECONDS
                ):
                    minutes = MAX_INPUT_WAIT_SECONDS / 60
                    self._stop_locked(
                        "timeout",
                        f"The program was stopped after waiting {minutes:g} minutes for INPUT. "
                        f"Press Run to start it again.",
                    )
                    return

                if segment_started_at is None:
                    # Program is waiting for INPUT; active timeout is paused.
                    continue

                if now - segment_started_at >= MAX_EXECUTION_SECONDS:
                    self._stop_locked(
                        "timeout",
                        f"Execution stopped after exceeding the "
                        f"{MAX_EXECUTION_SECONDS:g}-second time limit "
                        f"(possible infinite loop).",
                    )
                    return

    def _stop_locked(self, state: str, message: str):
        """Hard-stop the worker and publish a terminal state. Caller holds
        self._lock. Kill first, then publish the terminal state, so the
        observable state stays synchronized with the worker's termination."""
        self._terminate_worker()
        self._set_terminal(state)
        self.output_queue.put({"type": "error", "line": 0, "message": message})

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

    def touch(self):
        """Record that the browser is still watching this run."""
        self.last_seen = time.monotonic()

    def cancel(self) -> bool:
        """Stop the run at the browser's request (Run pressed again, or the
        page is being closed). Returns False if it had already ended."""
        with self._lock:
            if self.state in TERMINAL_STATES:
                return False
            self._stop_locked("cancelled", "The program was stopped.")
            return True

    def provide_input(self, value: str) -> bool:
        with self._lock:
            if self.state != "waiting_for_input":
                return False
            self._worker_input_queue.put(value)
            # Leave the waiting state immediately, so a second submission
            # sent before the worker resumes (a double click on Send) is
            # refused instead of silently becoming the answer to the
            # program's NEXT INPUT.
            self.state = "running"
            self._waiting_since = None
            return True

    def drain_events(self, wait: float = 0) -> list:
        """Return every browser event queued since the previous poll.

        With ``wait`` > 0 this long-polls: if nothing is queued yet, it
        blocks for up to ``wait`` seconds for the first event. That lets
        the browser poll about once a second instead of several times a
        second -- on a 0.1-CPU instance, fast polling from a handful of
        running programs costs more CPU than the instance has."""
        events = []
        if wait > 0 and self.state not in TERMINAL_STATES:
            try:
                events.append(self.output_queue.get(timeout=wait))
            except queue.Empty:
                return events
        while True:
            try:
                events.append(self.output_queue.get_nowait())
            except queue.Empty:
                break
        return events

    def close(self):
        """Release the IPC queues and process handle of an ended run."""
        if self._process.is_alive():
            with self._lock:
                self._terminate_worker()
        self._reader_thread.join(timeout=0.5)
        for q in (self.input_queue, self._worker_output_queue):
            try:
                q.close()
            except (OSError, ValueError):
                pass
        try:
            self._process.close()
        except ValueError:
            pass


class SessionStore:
    """In-memory session registry.

    Lives in a single process, so the web server must run exactly ONE
    worker process (see gunicorn.conf.py); a run started in one worker
    would be unknown to the others. Ended runs are pruned lazily whenever a
    new run is created, which keeps the registry bounded by the run-start
    rate limits without needing another background thread.
    """

    def __init__(self):
        self._sessions: dict[str, RunSession] = {}
        self._lock = threading.Lock()
        # Runs being started right now, counted against the limits before
        # their (slow) process spawn finishes, keyed by client.
        self._pending: collections.Counter = collections.Counter()
        self._recent_starts: dict[str, collections.deque] = {}

    def create(self, source: str, client_key: str = "") -> RunSession:
        with self._lock:
            expired = self._prune_locked()
        # Closing joins threads/processes, so it happens outside the lock
        # rather than stalling every concurrent poll.
        for session in expired:
            session.close()
        with self._lock:
            self._check_limits_locked(client_key)
            self._pending[client_key] += 1
        try:
            session = RunSession(source, client_key=client_key)
        finally:
            with self._lock:
                self._pending[client_key] -= 1
                if self._pending[client_key] <= 0:
                    del self._pending[client_key]
        with self._lock:
            self._sessions[session.id] = session
        return session

    def get(self, run_id: str) -> "RunSession | None":
        with self._lock:
            return self._sessions.get(run_id)

    def _check_limits_locked(self, client_key: str):
        now = time.monotonic()
        starts = self._recent_starts.setdefault(client_key, collections.deque())
        while starts and now - starts[0] >= 60:
            starts.popleft()
        if len(starts) >= MAX_RUN_STARTS_PER_MINUTE:
            raise RunLimitError(
                "Too many runs started in the last minute. Please wait a moment and try again.",
                429,
            )

        active = [s for s in self._sessions.values() if s.is_active]
        client_active = sum(1 for s in active if s.client_key == client_key)
        client_active += self._pending.get(client_key, 0)
        if client_active >= MAX_ACTIVE_RUNS_PER_CLIENT:
            raise RunLimitError(
                "Too many programs are already running from your network. "
                "Stop one, or wait for it to finish, then try again.",
                429,
            )
        if len(active) + sum(self._pending.values()) >= MAX_ACTIVE_RUNS:
            raise RunLimitError(
                "The interpreter is busy right now. Please try again in a few seconds.",
                503,
            )
        starts.append(now)

    def _prune_locked(self) -> list:
        """Forget runs that ended long enough ago, returning them so the
        caller can close() them once the lock is released."""
        now = time.monotonic()
        expired_ids = [
            run_id
            for run_id, s in self._sessions.items()
            if s.finished_at is not None and now - s.finished_at >= RESULT_RETENTION_SECONDS
        ]
        for client_key in [k for k, d in self._recent_starts.items() if not d or now - d[-1] >= 60]:
            del self._recent_starts[client_key]
        return [self._sessions.pop(run_id) for run_id in expired_ids]
