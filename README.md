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
│   ├── test_error_handling.py         Milestone 10 cross-stage error contract and runtime edge cases
│   └── test_web_error_handling.py     Web API validation/error boundary checks
├── Procfile                Deployment entry point (gunicorn)
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

**Deploying:** a `Procfile` (`web: gunicorn webapp.app:app`) is
included for platforms like Heroku/Render that run a `Procfile`
directly.

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
| 12 | Web interface | 🟡 Local test slice done (see note below) |
| 8 | Procedures & functions | ⏳ Not started |
| 9 | File handling (OPENFILE/READFILE/WRITEFILE/CLOSEFILE) | ⏳ Not started |
| 10 | Error handling pass (consistency audit across all features) | ✅ Done |
| 11 | Runtime safety (hard execution timeout / infinite-loop protection) | ✅ Done |

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

### Known limitations

- **No persistent saved-program backend yet**; the current web interface
  remains an in-memory/local execution tool rather than a multi-user
  account system.
- **No user-defined procedures/functions yet** (Milestone 8) — calling
  anything that isn't one of the built-in library functions gives a
  clear "not supported yet" error rather than failing silently.
- **No file handling yet** (Milestone 9).
- **Arrays are used one element at a time**, following the SRS. A whole
  array can't be assigned, copied or output: `MyArray <- [1, 2, 3]`,
  `B <- A` and `OUTPUT MyArray` are all reported as errors that say how
  to use an index instead (`MyArray[1] <- value`, `OUTPUT MyArray[1]`).
- Array storage is a simple dict keyed by index tuple, eagerly filled
  with default values at `DECLARE` time — fine at student-program
  scale. A program may hold at most 1,000,000 array elements in total;
  a larger `DECLARE` is refused with an error.
