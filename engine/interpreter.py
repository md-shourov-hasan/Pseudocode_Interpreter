"""
Interpreter for the IGCSE Pseudocode Compiler (Milestone 3).

Implements:
    FR-2.x        The five data types and their runtime representation
    FR-3.1        DECLARE reserves storage for an identifier (or several,
                  comma-separated, sharing one data type — extension added
                  on request: DECLARE a, b, c : INTEGER)
    FR-3.2        CONSTANT declares a value that cannot be reassigned
    FR-3.3        Assignment evaluates an expression and stores it
    FR-3.4        Undeclared-identifier and type-mismatch errors
    FR-4.1        INPUT reads a value from the user (or, extended on
                  request, directly into an array element)
    FR-4.2        OUTPUT displays one or more values
    FR-5.1        Arithmetic operators (+ - * / ^)
    FR-5.4        Relational operators (= < <= > >= <>)
    FR-7.1        IF ... THEN ... ENDIF (no ELSE)
    FR-7.2        IF ... THEN ... ELSE ... ENDIF
    FR-7.3        CASE OF ... ENDCASE, first matching value wins
    FR-7.4        CASE OF ... OTHERWISE ... ENDCASE
    FR-4.3        ROUND(value, places)
    FR-4.4        RANDOM() — random REAL in [0, 1]
    FR-5.2        DIV(dividend, divisor) — truncated integer quotient
    FR-5.3        MOD(dividend, divisor) — truncated-division remainder
    FR-5.5        LENGTH(string)
    FR-5.6        LCASE(string/char)
    FR-5.7        UCASE(string/char)
    FR-5.8        SUBSTRING(string, start, length) — 1-based, inclusive
    FR-11.2       Undeclared identifier -> error, not silent execution
    FR-11.3       Incompatible assignment -> error, not silent execution
    FR-6.1        FOR <var> <- <start> TO <finish> ... NEXT <var>
    FR-6.2        start == finish runs once; start "past" finish (for the
                  step's direction) runs zero times
    FR-6.3        Optional STEP <increment>, ascending or descending
    FR-6.4        REPEAT ... UNTIL <condition> — runs at least once
    FR-6.5        WHILE <condition> DO ... ENDWHILE — may run zero times
    FR-8.1        1D array DECLARE: ARRAY[<l>:<u>] OF <type>
    FR-8.2        1D array element assignment: <id>[<index>] <- <value>
    FR-8.3        2D array DECLARE: ARRAY[<lr>:<ur>, <lc>:<uc>] OF <type>
    FR-8.4        2D array element assignment: <id>[<row>, <col>] <- <value>
    FR-10.1       PROCEDURE <identifier> [(<params>)] ... ENDPROCEDURE
    FR-10.2       CALL <identifier> [(<args>)] -- substitutes and runs
    FR-10.3       FUNCTION <identifier> [(<params>)] RETURNS <type> ...
                  ENDFUNCTION; RETURN <expr> supplies its one value
    FR-10.4       A FUNCTION can only be invoked from within an
                  expression, never with CALL (checked in _exec_call
                  and _eval_call respectively)
    FR-9.1        OPENFILE <file identifier> FOR READ|WRITE
    FR-9.2        READFILE <file identifier>, <identifier> -- one line in
    FR-9.3        WRITEFILE <file identifier>, <value> -- one line out
    FR-9.4        CLOSEFILE <file identifier>
    (ext)         AND / OR / NOT boolean connectives in conditions,
                  requested beyond the reference syntax guide

Two deliberate deviations from strict type-mismatch behaviour
(requested; see the comments at their call sites):
  - Assigning a REAL value into an INTEGER variable truncates toward
    zero instead of raising an error (division always yields a float
    in the underlying arithmetic, even for exact quotients).
  - OUTPUT of a REAL value is rounded to at most 5 decimal places,
    with insignificant trailing zeros trimmed.

Milestone 8 scoping decision (the SRS doesn't specify variable scope
rules): each PROCEDURE/FUNCTION call runs in its own fresh local
scope containing only its parameters and whatever it DECLAREs itself.
Global variables from the main program are NOT visible inside a
procedure/function body -- but global CONSTANTs are, since they're
read-only and so carry none of the aliasing/mutation risk a shared
global variable would. A parameter is always scalar and passed by
value, like an ordinary assignment (REAL/INTEGER narrowing and
widening apply the same way) -- arrays cannot be passed as
PROCEDURE/FUNCTION parameters at all. See Interpreter._call_frame.

File handling (FR-9.1 - FR-9.4, Milestone 9): a "file identifier" is
whatever STRING/CHAR value `file_expr` evaluates to (see
ast_nodes.py's module docstring) -- normally a literal filename, as in
every SRS example, but a variable works too. NFR-4 ("shall not allow a
pseudocode program to access arbitrary locations on the host file
system") is enforced two ways: every file identifier must be a plain
name with no path separators or '..' (Interpreter._resolve_file_path),
and it is then resolved against ``file_root`` -- a directory supplied
by the caller (defaulting to the current working directory), which the
web interface points at a fresh, per-run temporary directory that is
deleted once the run ends (see webapp/run_session.py). Open files are
tracked in ``self._open_files`` (keyed by file identifier, not by any
particular variable, since OPENFILE/READFILE/WRITEFILE/CLOSEFILE all
name the file directly); FR-9.1's "a file shall only be opened in one
mode at a time" is enforced by refusing to OPENFILE a name that's
already open. Any files a program leaves open when it finishes (or
errors out) are closed automatically by ``run()``.

Array storage note: each array's elements live in a plain dict keyed
by index tuple (e.g. (3,) for 1D, (2, 5) for 2D), eagerly filled with
the element type's default value at DECLARE time. That trades a little
memory for simplicity — fine at the scale of a student program, but
not something you'd want for, say, a 1,000,000-element array.

NFR-3 note: callers can configure a cooperative execution time limit
with ``max_execution_seconds``. The web interface additionally runs each
program in a separate process so the parent can hard-terminate a runaway
execution rather than relying on a Python thread.

Design: a tree-walking interpreter. `Interpreter.run(program)` executes
every statement in order and returns the list of OUTPUT lines produced.
INPUT is satisfied by an injectable `input_fn` so tests don't need a real
stdin/stdout, and so the web interface can wire it up to a browser prompt.
When ``max_execution_seconds`` is set, the interpreter checks the elapsed
monotonic time between statements and loop iterations and raises a
student-facing ``PseudocodeError`` when the limit is exceeded.
"""

import math
import os
import random
import sys
import time
from decimal import ROUND_HALF_UP, Context, Decimal

from . import ast_nodes as ast
from .errors import PseudocodeError, format_type_name, normalize_unexpected_error
from .tokens import BUILTIN_FUNCTIONS

# ROUND works on the number's decimal text, not its binary float, and rounds a
# tie away from zero ("0.5 rounds up"), which is what students do by hand and
# what exam mark schemes expect. Python's own round() breaks ties toward the
# even digit (round(2.5) == 2) and sees 2.675 as 2.67499999..., so it disagrees
# with both. A float has at most ~340 digits after the point in its shortest
# form, so places beyond this bound can never change (or must always erase) it.
_ROUND_DIGITS_LIMIT = 350
_ROUND_PRECISION = 800  # comfortably above 309 integer digits + 340 fractional digits


def _round_half_up(value, places):
    """ROUND(value, places) with ties rounded away from zero. INTEGER in,
    INTEGER out; REAL in, REAL out. Raises ArithmeticError if the result cannot
    be represented (the caller turns that into a student-facing message)."""
    is_int = isinstance(value, int)
    if places > _ROUND_DIGITS_LIMIT:
        return value
    if places < -_ROUND_DIGITS_LIMIT:
        return 0 if is_int else 0.0
    exact = Decimal(value) if is_int else Decimal(repr(value))
    step = Decimal((0, (1,), -places))  # 10 ** -places, e.g. 0.01 for 2 places
    # A fresh context per call: quantize() records signals on the context it uses.
    context = Context(prec=_ROUND_PRECISION, rounding=ROUND_HALF_UP)
    rounded = exact.quantize(step, rounding=ROUND_HALF_UP, context=context)
    if is_int:
        return int(rounded)
    return float(rounded) + 0.0  # "+ 0.0" turns a negative zero into 0.0

# Default value each data type gets when DECLAREd, before assignment.
_DEFAULT_VALUE = {
    "INTEGER": 0,
    "REAL": 0.0,
    "CHAR": "",
    "STRING": "",
    "BOOLEAN": False,
}

# Which Python value types are acceptable for each pseudocode data type.
_PYTHON_TYPES_FOR = {
    "INTEGER": (int,),
    "REAL": (int, float),   # an INTEGER value may widen into a REAL variable
    "CHAR": (str,),
    "STRING": (str,),
    "BOOLEAN": (bool,),
}


# Every array element is stored explicitly (about 130 bytes each), so an
# unbounded DECLARE such as ARRAY[1:100000000] would exhaust the machine's
# memory before the execution time limit could ever stop it. IGCSE programs use
# arrays of a few dozen elements; this is a generous ceiling for one program,
# counted across all of its arrays.
MAX_ARRAY_ELEMENTS = 1_000_000

# A tree-walking call to a PROCEDURE/FUNCTION consumes several *Python* stack
# frames per level of pseudocode call nesting, so unbounded recursion would
# eventually hit Python's own recursion limit and raise a raw RecursionError
# rather than a clear pseudocode-level message. This cap is generous for any
# realistic student program (including recursive ones) while still catching
# "recursive call with no base case" well before Python's own limit -- see
# Interpreter._call_frame.
MAX_CALL_DEPTH = 200

# One level of pseudocode call nesting costs several real Python stack
# frames in this tree-walking design (statement dispatch, expression
# evaluation, argument binding, ...). Python's *own* default recursion
# limit (1000) would otherwise be reached well before MAX_CALL_DEPTH, which
# would surface as a generic runtime error instead of the clear message
# above. Interpreter.run() raises the limit for the duration of one run so
# MAX_CALL_DEPTH is always what actually stops runaway recursion; the
# multiplier is a generous over-estimate of frames-per-level so it stays
# safe even if a future change adds a few more calls to the chain.
_FRAMES_PER_CALL_ESTIMATE = 40

# How many _check_execution_timeout() calls happen between actual clock
# reads (see that method). 256 keeps the worst-case overshoot on any
# realistic program imperceptible (a few hundred extra tree-walking steps)
# while cutting the number of time.monotonic() calls in a hot loop by the
# same factor.
_TIMEOUT_CHECK_INTERVAL = 256


class _ReturnSignal(Exception):
    """Internal control-flow signal for RETURN (FR-10.3).

    Never surfaced to the user: always caught by the FUNCTION call whose
    body is currently executing (Interpreter._call_frame). If it were ever
    to escape all the way to Interpreter.run() -- which shouldn't happen,
    since the parser only accepts RETURN inside a FUNCTION body -- it would
    still be caught by run()'s own safety net and reported as a generic
    runtime error rather than leaking a raw traceback.
    """

    def __init__(self, value):
        self.value = value


def _with_article(type_name: str) -> str:
    """'an INTEGER', 'a REAL' -- so messages never say 'a INTEGER'."""
    return f"an {type_name}" if type_name[:1] in "AEIOU" else f"a {type_name}"


class Symbol:
    __slots__ = ("data_type", "value", "is_constant", "is_array", "dimensions")

    def __init__(
        self, data_type: str, value, is_constant: bool, is_array: bool = False, dimensions=None
    ):
        self.data_type = data_type
        self.value = value
        self.is_constant = is_constant
        self.is_array = is_array
        # dimensions: list of (lower, upper) INTEGER pairs — one pair per
        # dimension — only meaningful when is_array is True.
        self.dimensions = dimensions


class Interpreter:
    def __init__(self, input_fn=None, output_fn=None, max_execution_seconds=None, file_root=None):
        """
        input_fn:  callable() -> str, used to satisfy INPUT statements.
                   Defaults to the real `input()`.
        output_fn: callable(str) -> None, called once per OUTPUT statement
                   with the fully-formatted line. Defaults to collecting
                   lines into self.output (and also printing them).
        file_root: directory that OPENFILE/READFILE/WRITEFILE/CLOSEFILE
                   (FR-9.1 - FR-9.4) resolve file identifiers against.
                   Defaults to the current working directory. The web
                   interface passes a fresh per-run temporary directory
                   so a program can never read or write outside it
                   (NFR-4, NFR-6) -- see webapp/run_session.py.
        """
        self.symbols: dict[str, Symbol] = {}
        # A stable handle to the top-level scope, kept even while `self.symbols`
        # is temporarily swapped out for a PROCEDURE/FUNCTION call's local scope
        # (see _call_frame). Used only to read global CONSTANTs into a new call
        # frame -- see the Milestone 8 scoping note in this module's docstring.
        self._global_scope = self.symbols
        # Mirrors the CONSTANT-only subset of `_global_scope`, kept up to date
        # incrementally by `_exec_constant`. `_call_frame` needs exactly this
        # subset on every single PROCEDURE/FUNCTION call (see the Milestone 8
        # scoping note below), so maintaining it here avoids re-scanning every
        # global symbol -- constants and ordinary variables alike -- on each
        # call.
        self._global_constants: dict[str, Symbol] = {}
        self.procedures: dict[str, "ast.ProcedureDecl"] = {}
        self.functions: dict[str, "ast.FunctionDecl"] = {}
        self._call_depth = 0
        self.output: list[str] = []
        self._input_fn = input_fn if input_fn is not None else input
        self._output_fn = output_fn if output_fn is not None else self.output.append
        self._current_line = 0
        self._array_elements = 0  # elements allocated so far, across all arrays
        self._open_files: dict[str, dict] = {}  # file identifier -> {"mode", "handle"}
        self._file_root = file_root if file_root is not None else os.getcwd()
        self._max_execution_seconds = max_execution_seconds
        self._execution_started_at = None
        self._timeout_check_counter = 0
        if max_execution_seconds is not None:
            if (
                not isinstance(max_execution_seconds, (int, float))
                or isinstance(max_execution_seconds, bool)
                or not math.isfinite(float(max_execution_seconds))
                or max_execution_seconds <= 0
            ):
                raise ValueError("max_execution_seconds must be a finite positive number or None")

    # ---- public API -----------------------------------------------------

    def run(self, program: ast.Program) -> list[str]:
        self._execution_started_at = time.monotonic()
        self._timeout_check_counter = 0
        # See _FRAMES_PER_CALL_ESTIMATE: raised only for the duration of this
        # run, and always restored, so it never leaks into other interpreter
        # instances (e.g. other requests handled by the same web process).
        old_recursion_limit = sys.getrecursionlimit()
        needed_limit = MAX_CALL_DEPTH * _FRAMES_PER_CALL_ESTIMATE + 200
        if needed_limit > old_recursion_limit:
            sys.setrecursionlimit(needed_limit)
        try:
            for stmt in program.statements:
                self._exec_statement(stmt)
            return self.output
        except PseudocodeError:
            raise
        except RecursionError:
            # Safety net: MAX_CALL_DEPTH should always fire first (see
            # _FRAMES_PER_CALL_ESTIMATE), but a clear message here costs
            # nothing if some other, non-PROCEDURE/FUNCTION recursive path
            # (e.g. Python's own machinery) ever reaches Python's limit.
            raise PseudocodeError(
                self._current_line,
                "The program ran out of stack space, most likely from unbounded recursion.",
            ) from None
        except Exception as exc:
            # Milestone 10 safety net: implementation-level exceptions must
            # never leak through the public interpreter API.
            raise normalize_unexpected_error(self._current_line, exc) from None
        finally:
            sys.setrecursionlimit(old_recursion_limit)
            self._close_all_files()

    def _close_all_files(self):
        """Close any files a program left open (whether it finished
        normally or errored out) -- a program is never required to
        CLOSEFILE everything itself before ending (FR-9.4 doesn't
        require it), and leaking open file handles would otherwise
        outlive this run."""
        for entry in self._open_files.values():
            try:
                entry["handle"].close()
            except OSError:
                pass
        self._open_files.clear()

    def _check_execution_timeout(self, line=None):
        """Raise a language-level timeout once the configured run limit is exceeded.

        Called on every statement and every loop iteration, so in a tight
        loop this can run millions of times; actually reading the clock
        (time.monotonic()) is comparatively expensive to do that often. Since
        the limit is a "possible infinite loop" safety net rather than a
        precise deadline, it's checked for real only once every
        _TIMEOUT_CHECK_INTERVAL calls -- bounding how late the timeout can
        fire by a negligible, constant amount of extra work, while avoiding a
        clock read on most calls."""
        if self._max_execution_seconds is None or self._execution_started_at is None:
            return
        self._timeout_check_counter += 1
        if self._timeout_check_counter < _TIMEOUT_CHECK_INTERVAL:
            return
        self._timeout_check_counter = 0
        if time.monotonic() - self._execution_started_at >= self._max_execution_seconds:
            error_line = line if line is not None else self._current_line
            seconds = f"{self._max_execution_seconds:g}"
            raise PseudocodeError(
                error_line or 0,
                f"Execution exceeded the {seconds}-second time limit (possible infinite loop).",
            )

    # ---- statement execution --------------------------------------------

    def _exec_statement(self, stmt):
        # Every AST node is guaranteed to carry `line` (see ast_nodes.py's
        # module docstring), so a plain attribute access is used instead of
        # getattr(..., 0) here -- this runs for every statement executed,
        # including every pass through a loop body, so it's worth not paying
        # for a needless default lookup on the hottest path in the
        # interpreter.
        self._check_execution_timeout(stmt.line)
        self._current_line = stmt.line
        handler = self._STATEMENT_HANDLERS.get(type(stmt))
        if handler is None:
            raise PseudocodeError(
                stmt.line,
                "This statement is not supported yet.",
            )
        handler(self, stmt)

    def _exec_declare(self, stmt: ast.Declare):
        seen_in_statement = set()
        for name in stmt.identifiers:
            if name in self.symbols or name in seen_in_statement:
                raise PseudocodeError(
                    stmt.line,
                    f"'{name}' has already been declared.",
                )
            seen_in_statement.add(name)
        for name in stmt.identifiers:
            self.symbols[name] = Symbol(
                stmt.data_type, _DEFAULT_VALUE[stmt.data_type], is_constant=False
            )

    def _exec_array_declare(self, stmt: ast.ArrayDeclare):
        # Evaluate bounds once (they're shared across every identifier in
        # this DECLARE) and validate them before touching the symbol table,
        # so a bad bound never leaves a partially-declared array behind.
        dimensions = []
        for lower_node, upper_node in stmt.dimensions:
            lower = self._eval(lower_node)
            upper = self._eval(upper_node)
            lower = self._expect_integer(None, lower, stmt.line, "An array's lower bound")
            upper = self._expect_integer(None, upper, stmt.line, "An array's upper bound")
            if lower > upper:
                raise PseudocodeError(
                    stmt.line,
                    f"An array's lower bound ({lower}) cannot be greater than its upper bound ({upper}).",
                )
            dimensions.append((lower, upper))

        seen_in_statement = set()
        for name in stmt.identifiers:
            if name in self.symbols or name in seen_in_statement:
                raise PseudocodeError(stmt.line, f"'{name}' has already been declared.")
            seen_in_statement.add(name)

        # Refuse an array that would not fit in memory BEFORE allocating any of it.
        per_array = 1
        for lower, upper in dimensions:
            per_array *= upper - lower + 1
        requested = per_array * len(stmt.identifiers)
        if self._array_elements + requested > MAX_ARRAY_ELEMENTS:
            raise PseudocodeError(
                stmt.line,
                f"This DECLARE would create {requested:,} array elements"
                + (
                    f", bringing the program's total to {self._array_elements + requested:,}"
                    if self._array_elements
                    else ""
                )
                + f", but a program can hold at most {MAX_ARRAY_ELEMENTS:,} array elements.",
            )
        self._array_elements += requested

        default = _DEFAULT_VALUE[stmt.element_type]
        for name in stmt.identifiers:
            if len(dimensions) == 1:
                (lo, hi) = dimensions[0]
                values = {(i,): default for i in range(lo, hi + 1)}
            else:
                (r_lo, r_hi), (c_lo, c_hi) = dimensions
                values = {
                    (r, c): default
                    for r in range(r_lo, r_hi + 1)
                    for c in range(c_lo, c_hi + 1)
                }
            self.symbols[name] = Symbol(
                stmt.element_type, values, is_constant=False, is_array=True, dimensions=dimensions
            )

    def _ensure_scalar(self, symbol, name, line, column=None, end_column=None):
        """Guard against using a whole array where a single value is
        expected (bare `Arr` instead of `Arr[i]`) — without this, the
        array's internal storage dict would leak straight into OUTPUT,
        arithmetic, etc. as an unhelpful Python repr."""
        if symbol.is_array:
            raise PseudocodeError(
                line,
                f"'{name}' is an array — use an index, e.g. {name}[1], to access an element.",
                column=column,
                end_column=end_column,
            )

    def _exec_constant(self, stmt: ast.Constant):
        if stmt.identifier in self.symbols:
            raise PseudocodeError(
                stmt.line,
                f"'{stmt.identifier}' has already been declared.",
            )
        value = self._eval(stmt.value)
        data_type = self._infer_type(value, stmt.line, stmt.identifier)
        symbol = Symbol(data_type, value, is_constant=True)
        self.symbols[stmt.identifier] = symbol
        # CONSTANT is also allowed inside a PROCEDURE/FUNCTION body (it's an
        # ordinary statement per the grammar), where it belongs only to that
        # call's own local scope -- NOT to the global CONSTANTs every call
        # frame inherits (see _call_frame). Only mirror it into the cached
        # global-constants view when we're actually declaring at global scope.
        if self.symbols is self._global_scope:
            self._global_constants[stmt.identifier] = symbol

    def _exec_assignment(self, stmt: ast.Assignment):
        if isinstance(stmt.target, ast.Index):
            self._exec_array_assignment(stmt)
            return
        name = stmt.target.name
        symbol = self.symbols.get(name)
        if symbol is None:
            raise PseudocodeError(
                stmt.line,
                f"'{name}' is used here but was never declared with DECLARE.",
                column=stmt.target.column,
                end_column=stmt.target.end_column,
            )
        if symbol.is_array:
            raise PseudocodeError(
                stmt.line,
                f"'{name}' is an array, so it can't be assigned as a whole. Assign each "
                f"element separately using its index, e.g. {name}[1] <- value.",
                column=stmt.target.column,
                end_column=stmt.target.end_column,
            )
        if symbol.is_constant:
            raise PseudocodeError(
                stmt.line,
                f"'{name}' is a CONSTANT and cannot be reassigned.",
                column=stmt.target.column,
                end_column=stmt.target.end_column,
            )
        value = self._eval(stmt.value)
        self._store(symbol, value, stmt.line, name, stmt.value.column, stmt.value.end_column)

    @staticmethod
    def _element_label(name, index_tuple):
        """'a[2]' or 'g[1, 2]' -- how an array element is named in messages."""
        return f"{name}[{', '.join(str(i) for i in index_tuple)}]"

    def _exec_array_assignment(self, stmt: ast.Assignment):
        """<identifier>[<index>...] <- <value>   (FR-8.2, FR-8.4)"""
        target = stmt.target
        symbol, index_tuple = self._resolve_array_element(
            target.name, target.indices, stmt.line, target.column, target.end_column
        )
        value = self._eval(stmt.value)
        value = self._coerce_for_type(
            symbol.data_type,
            value,
            stmt.line,
            self._element_label(target.name, index_tuple),
            stmt.value.column,
            stmt.value.end_column,
        )
        symbol.value[index_tuple] = value

    def _resolve_array_element(self, name, index_nodes, line, column=None, end_column=None):
        """Shared by array reads (_eval_index) and array-element writes
        (_exec_array_assignment): looks up the array, evaluates and
        bounds-checks each index, and returns (symbol, index_tuple).

        `column`/`end_column` describe the WHOLE `name[...]` expression, for
        errors about the array itself (undeclared, not an array, wrong
        number of indices). An out-of-range or non-INTEGER index is instead
        blamed on that specific index's own expression span, from
        `index_nodes`."""
        symbol = self.symbols.get(name)
        if symbol is None:
            raise PseudocodeError(
                line,
                f"'{name}' is used here but was never declared with DECLARE.",
                column=column,
                end_column=end_column,
            )
        if not symbol.is_array:
            raise PseudocodeError(
                line,
                f"'{name}' is not an array, so it can't be indexed.",
                column=column,
                end_column=end_column,
            )

        if len(index_nodes) != len(symbol.dimensions):
            want = len(symbol.dimensions)
            got = len(index_nodes)
            raise PseudocodeError(
                line,
                f"'{name}' is a {want}D array and needs {want} index/indices, but got {got}.",
                column=column,
                end_column=end_column,
            )

        indices = []
        for index_node, (lower, upper) in zip(index_nodes, symbol.dimensions):
            index_value = self._eval(index_node)
            index_value = self._expect_integer(
                None,
                index_value,
                line,
                f"The index for '{name}'",
                column=index_node.column,
                end_column=index_node.end_column,
            )
            if index_value < lower or index_value > upper:
                raise PseudocodeError(
                    line,
                    f"Index {index_value} is out of bounds for '{name}' "
                    f"(valid range is {lower} to {upper}).",
                    column=index_node.column,
                    end_column=index_node.end_column,
                )
            indices.append(index_value)
        return symbol, tuple(indices)

    def _store(self, symbol, value, line, name, column=None, end_column=None):
        """Shared type-checked store used by plain assignment and by the
        FOR loop's per-iteration update of its loop variable."""
        symbol.value = self._coerce_for_type(symbol.data_type, value, line, name, column, end_column)

    def _coerce_for_type(self, data_type, value, line, name, column=None, end_column=None):
        # A REAL result (e.g. from "/") assigned into an INTEGER variable is
        # narrowed by truncating toward zero, rather than treated as a type
        # error — this is a deliberate product decision (requested), since
        # ordinary division always produces a float in the underlying
        # arithmetic even when the mathematical quotient looks INTEGER-like.
        if data_type == "INTEGER" and isinstance(value, float) and not isinstance(value, bool):
            value = int(value)
        self._check_assignable(data_type, value, line, name, column, end_column)
        # INTEGER assigned into a REAL variable is widened, per FR-2.2 semantics.
        if data_type == "REAL" and isinstance(value, int) and not isinstance(value, bool):
            value = float(value)
        return value

    def _exec_input(self, stmt):
        if isinstance(stmt.target, ast.Index):
            self._exec_array_input(stmt)
            return
        name = stmt.target.name
        symbol = self.symbols.get(name)
        if symbol is None:
            raise PseudocodeError(
                stmt.line,
                f"'{name}' is used here but was never declared with DECLARE.",
                column=stmt.target.column,
                end_column=stmt.target.end_column,
            )
        self._ensure_scalar(symbol, name, stmt.line, stmt.target.column, stmt.target.end_column)
        raw = self._input_fn()
        try:
            value = self._coerce_input(raw, symbol.data_type)
        except ValueError:
            raise PseudocodeError(
                stmt.line,
                f"Couldn't read '{raw}' as {_with_article(symbol.data_type)} value for '{name}'.",
                column=stmt.target.column,
                end_column=stmt.target.end_column,
            )
        symbol.value = value

    def _exec_array_input(self, stmt):
        """INPUT <identifier>[<index>...] — reads directly into an array
        element (FR-4.1 combined with FR-8.2/FR-8.4)."""
        target = stmt.target
        symbol, index_tuple = self._resolve_array_element(
            target.name, target.indices, stmt.line, target.column, target.end_column
        )
        raw = self._input_fn()
        try:
            value = self._coerce_input(raw, symbol.data_type)
        except ValueError:
            raise PseudocodeError(
                stmt.line,
                f"Couldn't read '{raw}' as {_with_article(symbol.data_type)} value for "
                f"'{self._element_label(target.name, index_tuple)}'.",
            )
        symbol.value[index_tuple] = value

    def _exec_output(self, stmt):
        # FR-4.2: comma-separated values are joined, with no separator, into one
        # line. A whole array cannot be output in one go; its elements are
        # output one at a time through an index, e.g. OUTPUT MyArray[1].
        parts = []
        for value_node in stmt.values:
            if isinstance(value_node, ast.Identifier):
                symbol = self.symbols.get(value_node.name)
                if symbol is not None and symbol.is_array:
                    raise PseudocodeError(
                        stmt.line,
                        f"'{value_node.name}' is an array, so it can't be output as a whole. "
                        f"Output each element separately using its index, "
                        f"e.g. OUTPUT {value_node.name}[1].",
                    )
            parts.append(self._format_value(self._eval(value_node)))
        self._output_fn("".join(parts))

    def _exec_for(self, stmt: ast.ForLoop):
        start = self._eval(stmt.start)
        finish = self._eval(stmt.finish)
        step = self._eval(stmt.step) if stmt.step is not None else 1
        start = self._expect_integer("FOR", start, stmt.line, "start value")
        finish = self._expect_integer("FOR", finish, stmt.line, "finish value")
        step = self._expect_integer("FOR", step, stmt.line, "STEP value")
        if step == 0:
            raise PseudocodeError(
                stmt.line, "A FOR loop's STEP value cannot be 0 (it would never finish)."
            )

        symbol = self.symbols.get(stmt.variable)
        if symbol is None:
            raise PseudocodeError(
                stmt.line,
                f"'{stmt.variable}' is used here but was never declared with DECLARE.",
            )
        if symbol.is_constant:
            raise PseudocodeError(
                stmt.line, f"'{stmt.variable}' is a CONSTANT and cannot be used as a FOR loop variable."
            )
        self._ensure_scalar(symbol, stmt.variable, stmt.line)

        # FR-6.2: start == finish runs the body exactly once; start "past"
        # finish for the step's direction runs it zero times. Ascending
        # (step > 0) and descending (step < 0) are handled symmetrically.
        value = start
        ascending = step > 0
        while (value <= finish) if ascending else (value >= finish):
            self._check_execution_timeout(stmt.line)
            self._store(symbol, value, stmt.line, stmt.variable)
            for s in stmt.body:
                self._exec_statement(s)
            value += step

    def _exec_repeat(self, stmt: ast.RepeatLoop):
        while True:
            self._check_execution_timeout(stmt.line)
            for s in stmt.body:
                self._exec_statement(s)
            condition = self._eval(stmt.until_condition)
            if not isinstance(condition, bool):
                raise PseudocodeError(
                    stmt.until_condition.line,
                    f"The UNTIL condition must evaluate to a BOOLEAN value, but got {self._type_name(condition)}.",
                    column=stmt.until_condition.column,
                    end_column=stmt.until_condition.end_column,
                )
            if condition:
                break

    def _exec_while(self, stmt: ast.WhileLoop):
        while True:
            self._check_execution_timeout(stmt.line)
            condition = self._eval(stmt.condition)
            if not isinstance(condition, bool):
                raise PseudocodeError(
                    stmt.condition.line,
                    f"The WHILE condition must evaluate to a BOOLEAN value, but got {self._type_name(condition)}.",
                    column=stmt.condition.column,
                    end_column=stmt.condition.end_column,
                )
            if not condition:
                break
            for s in stmt.body:
                self._exec_statement(s)

    def _exec_if(self, stmt: ast.If):
        condition = self._eval(stmt.condition)
        if not isinstance(condition, bool):
            raise PseudocodeError(
                stmt.condition.line,
                f"The IF condition must evaluate to a BOOLEAN value, but got {self._type_name(condition)}.",
                column=stmt.condition.column,
                end_column=stmt.condition.end_column,
            )
        body = stmt.then_body if condition else stmt.else_body
        for s in body:
            self._exec_statement(s)

    def _exec_case(self, stmt: ast.Case):
        symbol = self.symbols.get(stmt.subject)
        if symbol is None:
            raise PseudocodeError(
                stmt.line,
                f"'{stmt.subject}' is used here but was never declared with DECLARE.",
            )
        self._ensure_scalar(symbol, stmt.subject, stmt.line)
        subject_value = symbol.value
        for value_node, branch_stmt in stmt.branches:
            case_value = self._eval(value_node)
            if self._case_values_match(case_value, subject_value):
                self._exec_statement(branch_stmt)
                return
        if stmt.otherwise is not None:
            self._exec_statement(stmt.otherwise)

    def _case_values_match(self, case_value, subject_value) -> bool:
        # Keep BOOLEAN distinct from INTEGER, mirroring the assignment rules,
        # so CASE OF a BOOLEAN doesn't accidentally match 0/1 branches.
        if isinstance(case_value, bool) or isinstance(subject_value, bool):
            return isinstance(case_value, bool) and isinstance(subject_value, bool) and case_value == subject_value
        return case_value == subject_value

    # ---- procedures / functions (FR-10.1 - FR-10.4) -----------------------
    #
    # ProcedureDecl/FunctionDecl statements only ever appear at the very
    # front of Program.statements (the parser enforces this -- see its module
    # docstring), so both run and register their callable before the main
    # program's own statements execute, which is what lets two procedures/
    # functions call each other (including a function calling itself)
    # regardless of which one is written first.

    def _exec_procedure_decl(self, stmt: ast.ProcedureDecl):
        self._register_callable(stmt.name, "PROCEDURE", stmt.line)
        self.procedures[stmt.name] = stmt

    def _exec_function_decl(self, stmt: ast.FunctionDecl):
        self._register_callable(stmt.name, "FUNCTION", stmt.line)
        self.functions[stmt.name] = stmt

    def _register_callable(self, name, kind, line):
        """PROCEDURE/FUNCTION names share one namespace with each other and
        with the built-in library functions (BUILTIN_FUNCTIONS), separate
        from ordinary variables/constants."""
        if name in BUILTIN_FUNCTIONS:
            raise PseudocodeError(
                line, f"'{name}' is already the name of a built-in function and can't be used for a {kind}."
            )
        if name in self.procedures or name in self.functions:
            raise PseudocodeError(line, f"'{name}' has already been defined as a PROCEDURE or FUNCTION.")

    def _exec_procedure_call(self, stmt: ast.ProcedureCall):
        """CALL <identifier> [(<args>)]   (FR-10.2)"""
        name = stmt.name
        if name in BUILTIN_FUNCTIONS:
            raise PseudocodeError(
                stmt.line,
                f"'{name}' is a built-in function, not a PROCEDURE, so it can't be used with CALL. "
                f"Built-ins are used directly in an expression instead, e.g. OUTPUT {name}(...).",
            )
        if name in self.functions:
            raise PseudocodeError(
                stmt.line,
                f"'{name}' is a FUNCTION, not a PROCEDURE. A FUNCTION can only be called as part "
                f"of an expression, e.g. OUTPUT {name}(...), never with CALL.",
            )
        proc = self.procedures.get(name)
        if proc is None:
            raise PseudocodeError(
                stmt.line, f"'{name}' is used here but no PROCEDURE with that name was defined."
            )
        local_scope = self._bind_arguments(name, "PROCEDURE", proc.params, stmt.args, stmt.line)
        self._call_frame(proc.body, local_scope)

    def _call_function(self, name, arg_nodes, line, column, end_column):
        """Evaluate a call to a user-defined FUNCTION from within an
        expression (FR-10.3, FR-10.4). Called from _eval_call, which has
        already confirmed `name` isn't a built-in or a PROCEDURE."""
        func = self.functions[name]
        local_scope = self._bind_arguments(name, "FUNCTION", func.params, arg_nodes, line)
        result = self._call_frame(func.body, local_scope)
        if result is None:
            raise PseudocodeError(
                line,
                f"FUNCTION '{name}' finished without executing a RETURN statement; a FUNCTION "
                f"must return exactly one {func.return_type} value.",
                column=column,
                end_column=end_column,
            )
        return self._coerce_for_type(func.return_type, result, line, f"{name}'s return value", column, end_column)

    def _bind_arguments(self, name, kind, params, arg_nodes, call_line):
        """Evaluate a CALL/function-call's argument expressions against the
        callable's declared parameter list (FR-10.2) and build the fresh
        local scope the call runs in. Arguments are matched to parameters by
        position. Every parameter is scalar, so every argument is coerced
        exactly like an ordinary assignment (so an INTEGER argument widens
        into a REAL parameter, and so on) and passed by value -- arrays
        cannot be passed as arguments at all (see the parser's _param)."""
        if len(arg_nodes) != len(params):
            want, got = len(params), len(arg_nodes)
            want_word = "parameter" if want == 1 else "parameters"
            raise PseudocodeError(call_line, f"{kind} '{name}' expects {want} {want_word}, but got {got}.")
        for param in params:
            existing = self._global_scope.get(param.name)
            if existing is not None and existing.is_constant:
                raise PseudocodeError(
                    call_line,
                    f"Parameter '{param.name}' in {kind} '{name}' has the same name as the "
                    f"global CONSTANT '{param.name}'; choose a different parameter name.",
                )
        local_scope = {}
        for param, arg_node in zip(params, arg_nodes):
            value = self._eval(arg_node)
            value = self._coerce_for_type(
                param.data_type, value, call_line, param.name, arg_node.column, arg_node.end_column
            )
            local_scope[param.name] = Symbol(param.data_type, value, is_constant=False)
        return local_scope

    def _call_frame(self, body, params_scope):
        """Run a PROCEDURE/FUNCTION body in a fresh local scope and always
        restore the caller's scope afterwards, whether the body finishes
        normally, hits RETURN, or raises. Returns the RETURNed value, or
        None if the body ran off the end without one (a PROCEDURE always
        does; a FUNCTION doing so is reported by the caller -- see
        _call_function).

        Milestone 8 scoping decision (see this module's docstring): the new
        scope starts with the caller's global CONSTANTs (read-only, so safe
        to share) plus this call's own parameters -- nothing else from the
        caller's scope carries over, matching how procedures/functions are
        otherwise self-contained in the reference syntax guide's examples.
        """
        if self._call_depth >= MAX_CALL_DEPTH:
            raise PseudocodeError(
                self._current_line,
                f"Too many nested or recursive PROCEDURE/FUNCTION calls (limit: {MAX_CALL_DEPTH}). "
                f"This usually means a recursive call is missing its base case.",
            )
        local_scope = dict(self._global_constants)
        local_scope.update(params_scope)
        caller_scope = self.symbols
        self.symbols = local_scope
        self._call_depth += 1
        try:
            for s in body:
                self._exec_statement(s)
            return None
        except _ReturnSignal as signal:
            return signal.value
        finally:
            self._call_depth -= 1
            self._array_elements -= self._local_array_element_count(local_scope)
            self.symbols = caller_scope

    @staticmethod
    def _local_array_element_count(scope) -> int:
        """How many array elements a call frame's local scope OWNS, so they
        can be released from the MAX_ARRAY_ELEMENTS budget once the call
        returns -- otherwise a function that DECLAREs an array and is called
        repeatedly (in a loop, or recursively) would eventually hit the cap
        even though every earlier call's array is long gone. Every array
        Symbol in a local scope is one this call frame DECLAREd itself
        (parameters are always scalar), so all of them are counted here."""
        total = 0
        for sym in scope.values():
            if sym.is_array:
                count = 1
                for lower, upper in sym.dimensions:
                    count *= upper - lower + 1
                total += count
        return total

    def _exec_return(self, stmt: ast.Return):
        raise _ReturnSignal(self._eval(stmt.value))

    # ---- file handling (FR-9.1 - FR-9.4) -----------------------------------

    def _eval_file_identifier(self, node):
        """Evaluate a `file_expr` (see ast_nodes.py's module docstring) and
        check it's a usable file name. CHAR is accepted alongside STRING
        since both are Python `str` here and a single-character file name
        is a perfectly ordinary (if unusual) one."""
        value = self._eval(node)
        if not isinstance(value, str):
            raise PseudocodeError(
                node.line,
                f"A file identifier must be a STRING value, but got {self._type_name(value)}.",
                column=node.column,
                end_column=node.end_column,
            )
        if not value:
            raise PseudocodeError(
                node.line,
                "A file identifier cannot be an empty STRING.",
                column=node.column,
                end_column=node.end_column,
            )
        return value

    def _resolve_file_path(self, name, line):
        """Turn a file identifier into an actual path inside `self._file_root`
        (NFR-4: "shall not allow a pseudocode program to access arbitrary
        locations on the host file system"). Every example in the SRS is a
        plain file name, so anything that looks like it's trying to reach
        outside the current directory -- a path separator, or '..' -- is
        rejected outright rather than silently resolved."""
        if "/" in name or "\\" in name or name in (".", ".."):
            raise PseudocodeError(
                line,
                f"'{name}' is not a valid file name. File access is limited to plain file "
                f"names (no folders or '..') in the program's own working directory.",
            )
        return os.path.join(self._file_root, name)

    def _require_open_file(self, name, needed_mode, action, line):
        entry = self._open_files.get(name)
        if entry is None:
            raise PseudocodeError(
                line,
                f"'{name}' is not open. Use OPENFILE \"{name}\" FOR {needed_mode} before using {action}.",
            )
        if entry["mode"] != needed_mode:
            raise PseudocodeError(
                line,
                f"'{name}' is open for {entry['mode']}, but {action} needs it open for {needed_mode}.",
            )
        return entry

    def _exec_openfile(self, stmt: ast.OpenFile):
        """OPENFILE <file identifier> FOR <file mode>   (FR-9.1)"""
        name = self._eval_file_identifier(stmt.file_expr)
        if name in self._open_files:
            raise PseudocodeError(
                stmt.line,
                f"'{name}' is already open. Close it with CLOSEFILE before opening it again.",
            )
        path = self._resolve_file_path(name, stmt.line)
        if stmt.mode == "READ":
            try:
                handle = open(path, "r", encoding="utf-8")
            except FileNotFoundError:
                raise PseudocodeError(
                    stmt.line, f"'{name}' could not be opened for READ: the file does not exist."
                ) from None
            except OSError:
                raise PseudocodeError(stmt.line, f"'{name}' could not be opened for READ.") from None
        else:  # "WRITE" -- creates the file, or overwrites it if it already exists (FR-9.1)
            try:
                handle = open(path, "w", encoding="utf-8", newline="\n")
            except OSError:
                raise PseudocodeError(stmt.line, f"'{name}' could not be opened for WRITE.") from None
        self._open_files[name] = {"mode": stmt.mode, "handle": handle}

    def _exec_readfile(self, stmt: ast.ReadFile):
        """READFILE <file identifier>, <identifier>   (FR-9.2)"""
        name = self._eval_file_identifier(stmt.file_expr)
        entry = self._require_open_file(name, "READ", "READFILE", stmt.line)
        raw = entry["handle"].readline()
        if raw == "":
            raise PseudocodeError(stmt.line, f"READFILE tried to read past the end of '{name}'.")
        text = raw[:-1] if raw.endswith("\n") else raw  # drop the trailing newline, keep the rest

        target = stmt.target
        symbol = self.symbols.get(target.name)
        if symbol is None:
            raise PseudocodeError(
                stmt.line,
                f"'{target.name}' is used here but was never declared with DECLARE.",
                column=target.column,
                end_column=target.end_column,
            )
        self._ensure_scalar(symbol, target.name, stmt.line, target.column, target.end_column)
        if symbol.is_constant:
            raise PseudocodeError(
                stmt.line,
                f"'{target.name}' is a CONSTANT and cannot be reassigned.",
                column=target.column,
                end_column=target.end_column,
            )
        try:
            value = self._coerce_input(text, symbol.data_type)
        except ValueError:
            raise PseudocodeError(
                stmt.line,
                f"Couldn't read '{text}' from '{name}' as {_with_article(symbol.data_type)} "
                f"value for '{target.name}'.",
                column=target.column,
                end_column=target.end_column,
            )
        symbol.value = value

    def _exec_writefile(self, stmt: ast.WriteFile):
        """WRITEFILE <file identifier>, <value>   (FR-9.3)"""
        name = self._eval_file_identifier(stmt.file_expr)
        entry = self._require_open_file(name, "WRITE", "WRITEFILE", stmt.line)
        if isinstance(stmt.value, ast.Identifier):
            symbol = self.symbols.get(stmt.value.name)
            if symbol is not None and symbol.is_array:
                raise PseudocodeError(
                    stmt.line,
                    f"'{stmt.value.name}' is an array, so it can't be written to a file as a "
                    f"whole. Write each element separately using its index, e.g. WRITEFILE "
                    f"\"{name}\", {stmt.value.name}[1].",
                )
        value = self._eval(stmt.value)
        entry["handle"].write(self._format_value(value) + "\n")

    def _exec_closefile(self, stmt: ast.CloseFile):
        """CLOSEFILE <file identifier>   (FR-9.4)"""
        name = self._eval_file_identifier(stmt.file_expr)
        entry = self._open_files.pop(name, None)
        if entry is None:
            raise PseudocodeError(stmt.line, f"'{name}' is not currently open, so it can't be closed.")
        entry["handle"].close()

    # ---- expression evaluation --------------------------------------------

    def _eval(self, node):
        # Same reasoning as _exec_statement above: every expression node
        # always has `line`, and this is called for every subexpression of
        # every statement evaluated.
        self._current_line = node.line
        method = self._EXPR_HANDLERS.get(type(node))
        if method is None:
            raise PseudocodeError(
                node.line,
                "This expression is not supported yet.",
            )
        return method(self, node)

    def _eval_literal(self, node: ast.Literal):
        return node.value

    def _eval_identifier(self, node: ast.Identifier):
        symbol = self.symbols.get(node.name)
        if symbol is None:
            raise PseudocodeError(
                node.line,
                f"'{node.name}' is used here but was never declared with DECLARE.",
                column=node.column,
                end_column=node.end_column,
            )
        self._ensure_scalar(symbol, node.name, node.line, node.column, node.end_column)
        return symbol.value

    def _eval_unary(self, node: ast.UnaryOp):
        value = self._eval(node.operand)
        if node.op == "-":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise PseudocodeError(
                    node.line,
                    "The '-' operator can only be used on INTEGER or REAL values.",
                    column=node.column,
                    end_column=node.end_column,
                )
            return -value
        if node.op == "NOT":
            if not isinstance(value, bool):
                raise PseudocodeError(
                    node.line,
                    f"The NOT operator needs a BOOLEAN value, but got {self._type_name(value)}.",
                    column=node.column,
                    end_column=node.end_column,
                )
            return not value
        raise PseudocodeError(node.line, f"Unknown unary operator '{node.op}'.", column=node.column, end_column=node.end_column)

    def _eval_binary(self, node: ast.BinaryOp):
        left = self._eval(node.left)
        right = self._eval(node.right)
        op = node.op

        if op in ("+", "-", "*", "/", "^"):
            return self._eval_arithmetic(op, left, right, node)
        if op in ("=", "<", "<=", ">", ">=", "<>"):
            return self._eval_relational(op, left, right, node)
        if op in ("AND", "OR"):
            return self._eval_logical(op, left, right, node)
        raise PseudocodeError(node.line, f"Unknown operator '{op}'.", column=node.column, end_column=node.end_column)

    def _eval_logical(self, op, left, right, node):
        line, column, end_column = node.line, node.column, node.end_column
        # Both sides are evaluated (no short-circuiting) — see the parser's
        # module docstring for the reasoning.
        for v in (left, right):
            if not isinstance(v, bool):
                raise PseudocodeError(
                    line,
                    f"The '{op}' operator needs BOOLEAN values on both sides, but got {self._type_name(v)}.",
                    column=column,
                    end_column=end_column,
                )
        return (left and right) if op == "AND" else (left or right)

    def _eval_arithmetic(self, op, left, right, node):
        line, column, end_column = node.line, node.column, node.end_column
        if op == "+" and isinstance(left, str) and isinstance(right, str):
            return left + right  # string concatenation, common in student code
        for v in (left, right):
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise PseudocodeError(
                    line,
                    f"The '{op}' operator needs INTEGER or REAL values on both sides.",
                    column=column,
                    end_column=end_column,
                )
        if op == "+":
            return left + right
        if op == "-":
            return left - right
        if op == "*":
            return left * right
        if op == "/":
            if right == 0:
                raise PseudocodeError(
                    line,
                    "Division by zero: the program tried to divide by zero.",
                    column=column,
                    end_column=end_column,
                )
            result = left / right
            if isinstance(result, float) and not math.isfinite(result):
                raise PseudocodeError(
                    line,
                    "The division produced a number outside the supported REAL range.",
                    column=column,
                    end_column=end_column,
                )
            return result
        if op == "^":
            try:
                result = left ** right
            except ZeroDivisionError:
                raise PseudocodeError(
                    line,
                    "Division by zero: the program tried to divide by zero.",
                    column=column,
                    end_column=end_column,
                ) from None
            except (OverflowError, ValueError):
                raise PseudocodeError(
                    line,
                    "The power calculation produced a number outside the supported range.",
                    column=column,
                    end_column=end_column,
                ) from None
            if isinstance(result, complex):
                raise PseudocodeError(
                    line,
                    "The '^' operator must produce an INTEGER or REAL value.",
                    column=column,
                    end_column=end_column,
                )
            if isinstance(result, float) and not math.isfinite(result):
                raise PseudocodeError(
                    line,
                    "The power calculation produced a number outside the supported REAL range.",
                    column=column,
                    end_column=end_column,
                )
            return result

    def _eval_relational(self, op, left, right, node):
        line, column, end_column = node.line, node.column, node.end_column
        try:
            if op == "=":
                return left == right
            if op == "<":
                return left < right
            if op == "<=":
                return left <= right
            if op == ">":
                return left > right
            if op == ">=":
                return left >= right
            if op == "<>":
                return left != right
        except TypeError:
            raise PseudocodeError(
                line,
                f"Can't compare {self._type_name(left)} and {self._type_name(right)} with '{op}'.",
                column=column,
                end_column=end_column,
            )

    def _eval_call(self, node: ast.Call):
        """name(arg1, ...) -- a built-in (FR-4.3 etc.) or user-defined
        FUNCTION call (FR-10.3). A FUNCTION is only ever invoked this way,
        as part of an expression, per FR-10.4; CALLing one is rejected in
        _exec_procedure_call instead."""
        name = node.name
        if name in BUILTIN_FUNCTIONS:
            args = [self._eval(a) for a in node.args]
            return self._BUILTIN_HANDLERS[name](self, args, node.line)
        if name in self.procedures:
            raise PseudocodeError(
                node.line,
                f"'{name}' is a PROCEDURE, not a FUNCTION, so it can't be used in an expression. "
                f"Use CALL {name}(...) as its own statement instead.",
                column=node.column,
                end_column=node.end_column,
            )
        if name not in self.functions:
            raise PseudocodeError(
                node.line,
                f"'{name}(...)' isn't a recognized built-in or user-defined function.",
                column=node.column,
                end_column=node.end_column,
            )
        return self._call_function(name, node.args, node.line, node.column, node.end_column)

    # ---- library functions (FR-4.3, FR-4.4, FR-5.2, FR-5.3, FR-5.5-5.8) ---

    def _expect_arg_count(self, name, args, expected, line):
        if len(args) != expected:
            word = "argument" if expected == 1 else "arguments"
            raise PseudocodeError(
                line, f"{name}(...) needs {expected} {word}, but got {len(args)}."
            )

    def _expect_numeric(self, name, value, line, which="argument"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise PseudocodeError(
                line, f"{name}'s {which} must be INTEGER or REAL, but got {self._type_name(value)}."
            )

    def _expect_integer(self, name, value, line, which="argument", column=None, end_column=None):
        """Return `value` as an int, or raise.

        A REAL that is a whole number (5.0, as produced by 10 / 2 or
        ROUND(2.4, 0)) is accepted, because "/" always yields a REAL even when
        the quotient is whole -- the same reasoning as narrowing a REAL into an
        INTEGER variable. A REAL with a fractional part (2.5) is still an
        error, since silently truncating it here would hide a real mistake.

        Messages read "<name>'s <which> must be INTEGER ..."; pass name=None to
        use `which` on its own as the whole subject ("The index for 'a' must be
        INTEGER ...")."""
        subject = f"{name}'s {which}" if name else which
        if isinstance(value, bool):
            raise PseudocodeError(
                line,
                f"{subject} must be INTEGER, but got {self._type_name(value)}.",
                column=column,
                end_column=end_column,
            )
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            if value.is_integer():
                return int(value)
            hint = "" if name == "ROUND" else " (DIV gives a whole-number quotient.)"
            raise PseudocodeError(
                line,
                f"{subject} must be INTEGER, but got the REAL value "
                f"{self._format_real(value)}, which is not a whole number.{hint}",
                column=column,
                end_column=end_column,
            )
        raise PseudocodeError(
            line,
            f"{subject} must be INTEGER, but got {self._type_name(value)}.",
            column=column,
            end_column=end_column,
        )

    def _expect_string(self, name, value, line, which="argument"):
        if not isinstance(value, str):
            raise PseudocodeError(
                line, f"{name}'s {which} must be STRING or CHAR, but got {self._type_name(value)}."
            )

    def _builtin_round(self, args, line):
        self._expect_arg_count("ROUND", args, 2, line)
        value, places = args
        self._expect_numeric("ROUND", value, line, "first argument")
        places = self._expect_integer("ROUND", places, line, "second argument (places)")
        try:
            result = _round_half_up(value, places)
        except (ArithmeticError, ValueError):
            raise PseudocodeError(
                line,
                "ROUND could not represent the requested result within the supported range.",
            ) from None
        if isinstance(result, float) and not math.isfinite(result):
            raise PseudocodeError(
                line,
                "ROUND produced a number outside the supported REAL range.",
            )
        return result

    def _builtin_random(self, args, line):
        self._expect_arg_count("RANDOM", args, 0, line)
        # Python's random.random() gives [0, 1) — 1.0 itself is only ever
        # reached in the limit, never actually returned. Close enough to
        # the spec's "0 and 1 inclusive" for practical/educational use.
        return random.random()

    def _truncating_divmod(self, name, args, line):
        """Shared DIV/MOD helper: truncated-toward-zero division (matching
        "the fractional part discarded"), computed with plain integer
        arithmetic so large dividends never lose precision going through
        a float, unlike Python's own floor-based // and %."""
        self._expect_arg_count(name, args, 2, line)
        dividend, divisor = args
        dividend = self._expect_integer(name, dividend, line, "first argument (dividend)")
        divisor = self._expect_integer(name, divisor, line, "second argument (divisor)")
        if divisor == 0:
            raise PseudocodeError(line, f"{name}: division by zero.")
        quotient = abs(dividend) // abs(divisor)
        if (dividend < 0) != (divisor < 0):
            quotient = -quotient
        remainder = dividend - divisor * quotient
        return quotient, remainder

    def _builtin_div(self, args, line):
        quotient, _ = self._truncating_divmod("DIV", args, line)
        return quotient

    def _builtin_mod(self, args, line):
        _, remainder = self._truncating_divmod("MOD", args, line)
        return remainder

    def _builtin_length(self, args, line):
        self._expect_arg_count("LENGTH", args, 1, line)
        (value,) = args
        self._expect_string("LENGTH", value, line)
        return len(value)

    def _builtin_lcase(self, args, line):
        self._expect_arg_count("LCASE", args, 1, line)
        (value,) = args
        self._expect_string("LCASE", value, line)
        return value.lower()

    def _builtin_ucase(self, args, line):
        self._expect_arg_count("UCASE", args, 1, line)
        (value,) = args
        self._expect_string("UCASE", value, line)
        return value.upper()

    def _builtin_substring(self, args, line):
        self._expect_arg_count("SUBSTRING", args, 3, line)
        text, start, length = args
        self._expect_string("SUBSTRING", text, line, "first argument")
        start = self._expect_integer("SUBSTRING", start, line, "second argument (start)")
        length = self._expect_integer("SUBSTRING", length, line, "third argument (length)")
        if start < 1 or length < 1:
            raise PseudocodeError(
                line, "SUBSTRING's start and length must both be positive integers."
            )
        if start - 1 + length > len(text):
            raise PseudocodeError(
                line,
                f"SUBSTRING's start ({start}) and length ({length}) go past the end "
                f"of a {len(text)}-character value.",
            )
        return text[start - 1 : start - 1 + length]

    def _eval_index(self, node: ast.Index):
        """<identifier>[<index>...]   (array element read; the write side
        is _exec_array_assignment)."""
        symbol, index_tuple = self._resolve_array_element(
            node.name, node.indices, node.line, node.column, node.end_column
        )
        return symbol.value[index_tuple]

    # ---- type checking -----------------------------------------------

    def _infer_type(self, value, line, name):
        if isinstance(value, bool):
            return "BOOLEAN"
        if isinstance(value, int):
            return "INTEGER"
        if isinstance(value, float):
            return "REAL"
        if isinstance(value, str) and len(value) == 1:
            return "CHAR"
        if isinstance(value, str):
            return "STRING"
        raise PseudocodeError(
            line,
            f"Couldn't determine a supported pseudocode data type for '{name}'.",
        )

    def _check_assignable(self, data_type, value, line, name, column=None, end_column=None):
        valid_types = _PYTHON_TYPES_FOR[data_type]
        # bool is a subclass of int in Python — keep BOOLEAN and INTEGER distinct.
        if data_type != "BOOLEAN" and isinstance(value, bool):
            raise PseudocodeError(
                line,
                f"Can't assign a BOOLEAN value to '{name}', which is declared as {data_type}.",
                column=column,
                end_column=end_column,
            )
        if data_type == "BOOLEAN" and not isinstance(value, bool):
            raise PseudocodeError(
                line,
                f"Can't assign {_with_article(self._type_name(value))} value to '{name}', "
                f"which is declared as BOOLEAN.",
                column=column,
                end_column=end_column,
            )
        if not isinstance(value, valid_types):
            raise PseudocodeError(
                line,
                f"Can't assign {_with_article(self._type_name(value))} value to '{name}', "
                f"which is declared as {data_type}.",
                column=column,
                end_column=end_column,
            )
        if data_type == "CHAR" and isinstance(value, str) and len(value) != 1:
            raise PseudocodeError(
                line,
                f"Can't assign a STRING value to '{name}', which is declared as CHAR "
                f"(CHAR holds exactly one character).",
                column=column,
                end_column=end_column,
            )

    def _type_name(self, value) -> str:
        return format_type_name(value)

    def _coerce_input(self, raw: str, data_type: str):
        if not isinstance(raw, str):
            raise ValueError(raw)
        if data_type == "INTEGER":
            return int(raw.strip())
        if data_type == "REAL":
            value = float(raw.strip())
            if not math.isfinite(value):
                raise ValueError(raw)
            return value
        if data_type == "BOOLEAN":
            if raw.strip().upper() == "TRUE":
                return True
            if raw.strip().upper() == "FALSE":
                return False
            raise ValueError(raw)
        if data_type == "CHAR":
            if len(raw) != 1:
                raise ValueError(raw)
            return raw
        return raw  # STRING

    def _format_value(self, value) -> str:
        if isinstance(value, bool):
            return "TRUE" if value else "FALSE"
        if isinstance(value, float):
            return self._format_real(value)
        return str(value)

    def _format_real(self, value: float) -> str:
        """REAL values print with up to 5 decimal places, trimming
        insignificant trailing zeros (3.14 -> "3.14", not "3.14000")."""
        text = f"{round(value, 5):.5f}".rstrip("0").rstrip(".")
        return text if text not in ("", "-") else "0"

    _STATEMENT_HANDLERS = {}
    _EXPR_HANDLERS = {}
    _BUILTIN_HANDLERS = {}


Interpreter._STATEMENT_HANDLERS = {
    ast.Declare: Interpreter._exec_declare,
    ast.ArrayDeclare: Interpreter._exec_array_declare,
    ast.Constant: Interpreter._exec_constant,
    ast.Assignment: Interpreter._exec_assignment,
    ast.Input: Interpreter._exec_input,
    ast.Output: Interpreter._exec_output,
    ast.If: Interpreter._exec_if,
    ast.Case: Interpreter._exec_case,
    ast.ForLoop: Interpreter._exec_for,
    ast.RepeatLoop: Interpreter._exec_repeat,
    ast.WhileLoop: Interpreter._exec_while,
    ast.ProcedureDecl: Interpreter._exec_procedure_decl,
    ast.FunctionDecl: Interpreter._exec_function_decl,
    ast.ProcedureCall: Interpreter._exec_procedure_call,
    ast.Return: Interpreter._exec_return,
    ast.OpenFile: Interpreter._exec_openfile,
    ast.ReadFile: Interpreter._exec_readfile,
    ast.WriteFile: Interpreter._exec_writefile,
    ast.CloseFile: Interpreter._exec_closefile,
}

Interpreter._EXPR_HANDLERS = {
    ast.Literal: Interpreter._eval_literal,
    ast.Identifier: Interpreter._eval_identifier,
    ast.UnaryOp: Interpreter._eval_unary,
    ast.BinaryOp: Interpreter._eval_binary,
    ast.Call: Interpreter._eval_call,
    ast.Index: Interpreter._eval_index,
}

Interpreter._BUILTIN_HANDLERS = {
    "ROUND": Interpreter._builtin_round,
    "RANDOM": Interpreter._builtin_random,
    "DIV": Interpreter._builtin_div,
    "MOD": Interpreter._builtin_mod,
    "LENGTH": Interpreter._builtin_length,
    "LCASE": Interpreter._builtin_lcase,
    "UCASE": Interpreter._builtin_ucase,
    "SUBSTRING": Interpreter._builtin_substring,
}


def run(
    program: ast.Program,
    input_fn=None,
    output_fn=None,
    max_execution_seconds=None,
    file_root=None,
) -> list[str]:
    """Convenience wrapper: run a full Program and return its output lines."""
    return Interpreter(
        input_fn=input_fn,
        output_fn=output_fn,
        max_execution_seconds=max_execution_seconds,
        file_root=file_root,
    ).run(program)
