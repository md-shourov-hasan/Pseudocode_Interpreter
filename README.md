# Pseudocode Interpreter

An interpreter for the pseudocode notation defined by the Cambridge
IGCSE / O Level Computer Science (0478) syllabus, built from an
accompanying Software Requirements Specification (SRS), plus a small
local web interface for trying programs out in the browser.

## Overview

You write pseudocode (`DECLARE`, `IF`/`THEN`/`ELSE`, `FOR`/`NEXT`,
arrays, etc.) either as a `.pseudo`-style source string or directly in
the browser editor, and the interpreter tokenizes, parses, and runs it,
producing `OUTPUT` and prompting for `INPUT` exactly as the syllabus
describes.

## Architecture

Classic three-stage pipeline, kept as separable modules so the grammar
can be extended without touching unrelated code:

```
Source Text
    |
    v
+-------------+   tokens   +-------------+   AST   +--------------+
|    Lexer    | ---------> |    Parser   | ------> |  Interpreter |  --> Output / Errors
+-------------+            +-------------+         +--------------+
                                                          |
                                                    Symbol Table
                                                 (scopes, arrays, types)
```

- **Lexer** (`engine/lexer.py`) — turns raw text into tokens: keywords,
  identifiers, literals, operators. Comments are stripped. Every token
  carries its source line number for error reporting.
- **Parser** (`engine/parser.py`) — recursive-descent, builds an AST
  (`engine/ast_nodes.py`). This is where syntax errors are caught, with
  a line number and a plain-English message.
- **Interpreter** (`engine/interpreter.py`) — a tree-walking evaluator.
  Maintains a symbol table (variables, constants, arrays), enforces
  types, and executes statements in order.
- **Error reporting** (`engine/errors.py`) — one shared
  `PseudocodeError(line, message)` type threaded through all three
  stages, phrased for students, never a raw Python traceback.
- **Web interface** (`webapp/`) — a small Flask app that serves a
  browser-based editor and runs programs interactively, including live
  `INPUT` prompts (see "Web interface" below).

## Project structure

```
Pseudocode_Interpreter/
├── engine/
│   ├── __init__.py
│   ├── tokens.py         Token types + keyword table
│   ├── errors.py         Shared PseudocodeError type (line + message)
│   ├── lexer.py          Source text -> tokens
│   ├── ast_nodes.py      AST node dataclasses
│   ├── parser.py         Tokens -> AST (recursive descent)
│   └── interpreter.py    AST -> execution (tree-walking)
├── webapp/
│   ├── app.py             Flask routes: serve the editor, run/poll/input API
│   ├── run_session.py     Threaded run manager — lets INPUT block for a real browser response
│   ├── templates/
│   │   └── index.html     Editor page
│   └── static/
│       ├── style.css      Dark, code-editor-style UI
│       └── app.js         Editor behaviour: gutter, auto-indent, run/poll/input flow
├── tests/
│   ├── test_lexer.py                 Lexer fundamentals
│   ├── test_parser.py                Statements + expression precedence
│   ├── test_interpreter.py           Types, errors, INPUT/OUTPUT
│   ├── test_selection.py             IF/ELSE/ENDIF, CASE OF/OTHERWISE/ENDCASE
│   ├── test_bugfixes.py              Multi-identifier DECLARE, INTEGER/REAL narrowing, AND/OR/NOT
│   ├── test_library_functions.py     ROUND, RANDOM, DIV, MOD, LENGTH, LCASE, UCASE, SUBSTRING
│   ├── test_iteration.py             FOR/NEXT, REPEAT/UNTIL, WHILE/DO/ENDWHILE
│   ├── test_arrays.py                1D and 2D array declaration, indexing, bounds checking
│   ├── test_array_io.py              INPUT into an array element; OUTPUT of a whole array is refused
│   ├── test_lexer_typo_detection.py  Catches the "<--" typo instead of misparsing it
│   ├── test_procedures_functions.py  PROCEDURE/FUNCTION/CALL/RETURN, scoping, recursion
│   ├── test_array_parameters.py      Array parameters passed by reference (extension)
│   ├── test_file_handling.py         OPENFILE/READFILE/WRITEFILE/CLOSEFILE, sandboxing
│   ├── test_error_handling.py         Milestone 10 cross-stage error contract and runtime edge cases
│   ├── test_runtime_safety.py         Milestone 11 execution timeout / infinite-loop protection
│   └── test_web_error_handling.py     Web server limits, run lifecycle, API validation
├── Procfile                Deployment entry point (gunicorn)
├── gunicorn.conf.py        One worker process, threaded (required by the in-memory run store)
├── requirements.txt
└── README.md
```

## Running it

```bash
pip install -r requirements.txt
```

**Run the tests:**

```bash
python -m pytest tests/ -v
```

**Run the web interface locally:**

```bash
python webapp/app.py
```

Then open **http://127.0.0.1:5000**. Type or edit pseudocode in the
left pane and click **Run**. `OUTPUT` streams into the right pane as
it's produced; if the program hits `INPUT`, a prompt appears at the
bottom of the console so you can type a value and continue — no need
to pre-supply every input up front. Errors show up in red with the
line number they relate to.

**Deploying:** start the app with `gunicorn webapp.app:app` from the
repository root (the `Procfile` does this). Gunicorn picks up
`gunicorn.conf.py` automatically, which runs **exactly one worker
process** with 16 threads. Runs are tracked in memory in that one
process, so don't pass `--workers`/`-w` in the host's start command.

### Web server limits

The interpreter is public and embedded in the SudoLab site as an
iframe, and every Run is its own process, so the server protects itself
with these limits. Each one can be changed with an environment variable.
The defaults are sized for Render's free plan (512 MB RAM, 0.1 CPU) and
were checked under a simulated free-plan CPU and memory cap: six
simultaneous memory-hungry runs peaked at ~140 MB in total and the server
stayed responsive. On a bigger plan, raise `PSEUDOCODE_MAX_ACTIVE_RUNS`,
keeping active runs × `PSEUDOCODE_WORKER_MEMORY_LIMIT_MB` below the
instance's RAM minus ~100 MB.

| Limit | Default | Environment variable |
|---|---|---|
| Active execution time per run (paused while waiting for `INPUT`) | 10 s | `PSEUDOCODE_MAX_EXECUTION_SECONDS` |
| Longest wait at one `INPUT` prompt | 300 s | `PSEUDOCODE_MAX_INPUT_WAIT_SECONDS` |
| Run stopped after this long with no polling (page closed) | 150 s | `PSEUDOCODE_ABANDONED_RUN_SECONDS` |
| Ended runs forgotten after | 120 s | `PSEUDOCODE_RESULT_RETENTION_SECONDS` |
| Active runs, whole server | 6 | `PSEUDOCODE_MAX_ACTIVE_RUNS` |
| Active runs per client IP | 3 | `PSEUDOCODE_MAX_ACTIVE_RUNS_PER_CLIENT` |
| Runs started per client IP per minute | 30 | `PSEUDOCODE_MAX_RUN_STARTS_PER_MINUTE` |
| `OUTPUT` per run | 5,000 lines / 500,000 chars | `PSEUDOCODE_MAX_OUTPUT_LINES`, `PSEUDOCODE_MAX_OUTPUT_CHARS` |
| Worker memory (Linux only) | 64 MB | `PSEUDOCODE_WORKER_MEMORY_LIMIT_MB` |
| Program size / one `INPUT` value | 100,000 / 10,000 chars | (constants in `webapp/app.py`) |

To keep CPU use low, the page long-polls (the server holds each poll for
up to 1.5 s until there's news). On Linux, workers start by forking a
preloaded fork server instead of a fresh Python interpreter, and run at
a lower CPU priority than the web server. The page also tells the server
to stop its run when it's closed, using
`navigator.sendBeacon` on `pagehide`. Clients are identified by IP
address, because cookies are often blocked inside a third-party iframe.
On Render (detected through the `RENDER` variable) the address is read
from the last `X-Forwarded-For` hop. Set `TRUSTED_PROXY_COUNT` to change
how many proxy hops are trusted. A whole classroom behind one school
network shares one IP, so raise the per-client limits if that's how the
interpreter is used.

## Milestones

| # | Milestone | Status |
|---|-----------|--------|
| 0 | Project scaffolding | ✅ Done |
| 1 | Lexer | ✅ Done |
| 2 | Core parser + AST (DECLARE/CONSTANT/assignment/expressions) | ✅ Done |
| 3 | Basic interpreter (types, INPUT/OUTPUT) | ✅ Done |
| 4 | Library functions (ROUND, RANDOM, DIV, MOD, LENGTH, LCASE, UCASE, SUBSTRING) | ✅ Done |
| 5 | Selection (IF/ELSE/ENDIF, CASE OF/OTHERWISE/ENDCASE) | ✅ Done |
| 6 | Iteration (FOR/NEXT, REPEAT/UNTIL, WHILE/DO/ENDWHILE) | ✅ Done |
| 7 | Arrays (1D and 2D, plus INPUT into an element) | ✅ Done |
| 8 | Procedures & functions | ✅ Done |
| 9 | File handling (OPENFILE/READFILE/WRITEFILE/CLOSEFILE) | ✅ Done |
| 10 | Error handling pass (consistency audit across all features) | ✅ Done |
| 11 | Runtime safety (hard execution timeout / infinite-loop protection) | ✅ Done |
| 12 | Web interface | 🟡 Local test slice done (see note below) |

Milestone 12 was pulled forward and scoped down early to make manual
testing easier; it currently covers a working local editor with live
`INPUT`, but not the full interface polish (syntax highlighting,
saved/shareable programs, etc.) a complete Milestone 12 would include.

### Language extensions beyond the reference syntax guide

A few things were added on request that go beyond the SRS's own
grammar. They're implemented but worth knowing about if you're
comparing strictly against the syllabus:

- **`AND` / `OR` / `NOT`** boolean connectives in conditions (e.g.
  `IF NOT IsSorted AND (A = 1 OR B <> 2) THEN`), with `NOT` binding
  tightest, then `AND`, then `OR` — parentheses override as usual.
- **Multiple identifiers per `DECLARE`**: `DECLARE a, b, c : INTEGER`.
- **`INPUT` into an array element**: `INPUT MyArray[3]` reads
  directly into an element.
- **REAL → INTEGER narrowing**: assigning a REAL result (e.g. from
  `/`) into an INTEGER variable truncates toward zero instead of
  raising a type error, since ordinary division always produces a
  float even for exact quotients.
- **REAL output formatting**: `OUTPUT` of a REAL value rounds to at
  most 5 decimal places, trimming insignificant trailing zeros.
- **`<--` typo detection**: `X <-- 5` (an extra dash) raises a clear
  "looks like a typo" error instead of silently parsing as
  `X <- -5`, which was a real bug users hit.
- **Array parameters**: a PROCEDURE/FUNCTION parameter can be declared
  as an array (`ARRAY[1:10] OF INTEGER`) and is passed by reference,
  beyond the SRS's scalar-only, by-value parameter grammar.
- **File identifiers can be expressions, not just literals**: every
  SRS example writes `OPENFILE "Names.txt" FOR READ` with the file
  name as a quoted literal, but `OPENFILE`/`READFILE`/`WRITEFILE`/
  `CLOSEFILE` all accept any STRING/CHAR-valued expression, so a
  variable holding a filename works too (e.g. `OPENFILE Filename FOR
  READ`).
- **`WRITEFILE`'s value is a general expression**: the SRS's own
  example passes a bare identifier (`WRITEFILE "Remarks.txt", Remark`),
  but any expression is accepted, matching how `OUTPUT` already works
  (e.g. `WRITEFILE "Log.txt", Name + ": " + Message`).

### File handling notes (Milestone 9)

- A file can only be open in one mode at a time (FR-9.1): `OPENFILE`
  on a name that's already open is refused until it's `CLOSEFILE`d.
  `OPENFILE ... FOR WRITE` creates the file if needed and truncates it
  if it already exists; `FOR READ` requires the file to already exist.
- `READFILE` reads one line and coerces it into the target identifier's
  declared type exactly the way `INPUT` coerces a typed value — an
  `INTEGER`/`REAL`/`BOOLEAN`/`CHAR` variable parses the line's text
  accordingly, and reading past the last line is a clear error rather
  than silently returning an empty value.
- **Sandboxing (NFR-4, NFR-6)**: a file identifier must be a plain file
  name — no path separators (`/` or `\`) and no `..` — so a program can
  never read or write outside its own working directory. The
  interpreter resolves every file identifier against a `file_root`
  directory (an `Interpreter(..., file_root=...)` constructor argument,
  defaulting to the current working directory); the web interface
  points `file_root` at a fresh temporary directory for every run and
  deletes it once the run finishes, so concurrent runs can't see or
  interfere with each other's files.
- Any files a program leaves open when it finishes (or errors out) are
  closed automatically; a program is never required to `CLOSEFILE`
  everything itself before ending.

### Known limitations

- **No persistent saved-program backend yet**; the current web interface
  remains an in-memory/local execution tool rather than a multi-user
  account system.
- **Files don't persist between runs** in the web interface: each Run
  gets its own temporary working directory that's deleted afterwards
  (see "File handling notes" above), so a file written by one Run
  can't be read back by a later, separate Run.
- **Arrays are used one element at a time**, following the SRS. A whole
  array can't be assigned, copied or output: `MyArray <- [1, 2, 3]`,
  `B <- A` and `OUTPUT MyArray` are all reported as errors that say how
  to use an index instead (`MyArray[1] <- value`, `OUTPUT MyArray[1]`).
- Array storage is a simple dict keyed by index tuple, eagerly filled
  with default values at `DECLARE` time — fine at student-program
  scale. A program may hold at most 1,000,000 array elements in total;
  a larger `DECLARE` is refused with an error.