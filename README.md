# Pseudocode Interpreter

An interpreter for the pseudocode notation used in the Cambridge
IGCSE / O Level Computer Science (0478) syllabus, with a browser-based
editor for writing and running programs.

Students write pseudocode exactly as it appears in the syllabus
(`DECLARE`, `IF ... THEN ... ENDIF`, `FOR ... NEXT`, arrays, procedures,
file handling) and the interpreter runs it, prompting for `INPUT` live and
reporting mistakes in plain English with the line, and usually the exact
text, that caused them.

The project has two parts:

- **`engine/`**: the language itself. A pure-Python lexer, parser and
  tree-walking interpreter with no dependencies outside the standard library.
- **`webapp/`**: a Flask app that serves a Monaco-based editor and runs
  each program in its own sandboxed process. It is deployed publicly and
  embedded in the SudoLab site as an iframe.

The behaviour follows the accompanying
[Software Requirements Specification](Software%20Requirements%20Specification.pdf);
the `FR-x.y` / `NFR-x` references in the source comments point to it.

## Example

```
FUNCTION Square(N : INTEGER) RETURNS INTEGER
    RETURN N * N
ENDFUNCTION

DECLARE Marks : ARRAY[1:3] OF INTEGER
DECLARE Total, i : INTEGER

Total <- 0
FOR i <- 1 TO 3
    INPUT Marks[i]
    Total <- Total + Square(Marks[i])
NEXT i

OUTPUT "Sum of squares: ", Total
OUTPUT "Average: ", Total / 3
```

With the inputs `1`, `2` and `4` this prints:

```
Sum of squares: 21
Average: 7
```

A mistake is reported against the source rather than as a Python traceback:

```
Score <- "hello"
         ^^^^^^^
Line 2  Can't assign a STRING value to 'Score', which is declared as INTEGER.
```

## Getting started

Requires Python 3.10 or newer (developed on 3.14).

```bash
git clone https://github.com/md-shourov-hasan/Pseudocode_Interpreter.git
cd Pseudocode_Interpreter
pip install -r requirements.txt
python webapp/app.py
```

Then open **http://127.0.0.1:5000**. Write pseudocode in the left pane and
press **Run**. `OUTPUT` appears in the right pane as it is produced. When
the program reaches `INPUT`, a prompt appears under the console; type a
value and press **Send** to continue. Errors are shown in red with their
line number, and the offending text is underlined in the editor.

### Using the engine from Python

The engine can be used on its own, without the web app:

```python
from engine.lexer import tokenize
from engine.parser import parse
from engine.interpreter import Interpreter
from engine.errors import PseudocodeError

source = 'DECLARE Name : STRING\nINPUT Name\nOUTPUT "Hello, ", Name\n'

try:
    interpreter = Interpreter(input_fn=lambda: "Ada")
    print(interpreter.run(parse(tokenize(source))))   # ['Hello, Ada']
except PseudocodeError as error:
    print(error.line, error.message)
```

`Interpreter` takes four optional arguments:

| Argument | Purpose |
|---|---|
| `input_fn` | Called with no arguments for each `INPUT`; returns the text entered. Defaults to `input()`. |
| `output_fn` | Called with each finished `OUTPUT` line. By default lines are collected and returned by `run()`. |
| `max_execution_seconds` | A time limit checked between statements and loop iterations. Off by default. |
| `file_root` | The directory that file statements read and write in. Defaults to the current working directory. |

Every error from any stage is a `PseudocodeError` with `line`, `message`
and, where the error points at specific text, a 1-based inclusive
`column` / `end_column` span.

## Language reference

Keywords are upper case and case-sensitive. Statements are separated by
line breaks. `//` starts a comment that runs to the end of the line.
Assignment is written `<-` or `←`.

| Area | Supported |
|---|---|
| Data types | `INTEGER`, `REAL`, `CHAR`, `STRING`, `BOOLEAN` |
| Declarations | `DECLARE <name> : <type>`, `CONSTANT <name> <- <value>` |
| Input / output | `INPUT <name>`, `OUTPUT <value>, <value>, ...` |
| Arithmetic | `+` `-` `*` `/` `^`, unary `-`, parentheses |
| Comparison | `=` `<>` `<` `<=` `>` `>=` |
| Logic | `AND`, `OR`, `NOT` |
| Selection | `IF ... THEN ... ELSE ... ENDIF`, `CASE OF ... OTHERWISE ... ENDCASE` |
| Iteration | `FOR ... TO ... STEP ... NEXT`, `REPEAT ... UNTIL`, `WHILE ... DO ... ENDWHILE` |
| Arrays | 1D and 2D: `DECLARE <name> : ARRAY[1:10] OF INTEGER`, `ARRAY[1:3, 1:3] OF CHAR` |
| Routines | `PROCEDURE ... ENDPROCEDURE`, `FUNCTION ... RETURNS <type> ... ENDFUNCTION`, `CALL`, `RETURN` |
| Files | `OPENFILE <file> FOR READ` / `WRITE`, `READFILE`, `WRITEFILE`, `CLOSEFILE` |
| Library functions | `ROUND`, `RANDOM`, `DIV`, `MOD`, `LENGTH`, `LCASE`, `UCASE`, `SUBSTRING` |

### Behaviour worth knowing

**Types and values**

- A declared variable starts at `0`, `0.0`, an empty string or `FALSE`.
- `/` always produces a `REAL`. An `INTEGER` value widens into a `REAL`
  variable, and a `REAL` assigned to an `INTEGER` variable is truncated
  toward zero.
- `OUTPUT` joins its values with no separator. A `REAL` is shown with at
  most 5 decimal places and no trailing zeros, so `21 / 3` prints `7`.
  A `BOOLEAN` prints as `TRUE` or `FALSE`.
- `+` also joins two `STRING` / `CHAR` values.
- A `CONSTANT` takes its type from its value and cannot be reassigned.

**Expressions**

- Precedence, loosest to tightest: `OR`, `AND`, `NOT`, comparison, `+ -`,
  `* /`, unary `-`, `^`. `^` is right-associative, so `2 ^ 3 ^ 2` is `512`.
- `AND` and `OR` always evaluate both sides.
- Comparisons do not chain: `1 < X < 10` is a syntax error. Write
  `1 < X AND X < 10`.

**Library functions**

- `ROUND(value, places)` rounds a tie away from zero, so `ROUND(2.5, 0)`
  is `3`.
- `DIV` and `MOD` truncate toward zero: `DIV(-7, 2)` is `-3` and
  `MOD(-7, 2)` is `-1`.
- `SUBSTRING(text, start, length)` is 1-based, and reading past the end of
  the text is an error.
- `RANDOM()` returns a `REAL` from 0 up to, but not including, 1.

**Control flow**

- `FOR` bounds and `STEP` must be whole numbers, `STEP` may be negative
  but not zero, and `NEXT` must name the loop variable.
- `CASE OF` takes a plain variable. Each branch value is a literal and
  each branch holds a single statement.

**Arrays**

- Bounds can be any `INTEGER` expression, such as a `CONSTANT`, and every
  access is bounds-checked.
- Arrays are used one element at a time. `MyArray <- [1, 2, 3]`, `B <- A`
  and `OUTPUT MyArray` are errors that explain how to use an index instead.
- A program can hold at most 1,000,000 array elements in total.

**Procedures and functions**

- Definitions must come at the top of the program, before any other
  statement, and cannot be nested. They can call each other, and
  themselves, in any order.
- Parameters are scalar and passed by value. An array cannot be passed as
  a parameter.
- Each call runs in its own scope holding only its parameters, its own
  declarations and the program's global `CONSTANT`s. Global variables are
  not visible inside a routine.
- A `FUNCTION` must reach a `RETURN` and can only be used in an
  expression. A `PROCEDURE` can only be used with `CALL`.
- Calls can nest 200 deep; beyond that the program is stopped with a
  "missing base case" error.

**Files**

- `OPENFILE ... FOR WRITE` creates the file or empties an existing one.
  `FOR READ` requires the file to exist. A file can be open in only one
  mode at a time.
- `READFILE` reads one line and converts it to the target variable's type
  the same way `INPUT` does. Reading past the last line is an error.
- A file name must be a plain name with no `/`, `\` or `..`, so a program
  cannot reach outside its working directory.
- Files left open when a program ends are closed automatically.

### Additions to the syllabus syntax

These go beyond the grammar in the SRS:

- `AND` / `OR` / `NOT` in conditions.
- Several names in one statement: `DECLARE a, b, c : INTEGER`.
- `INPUT` straight into an array element: `INPUT Marks[3]`.
- File names and `WRITEFILE` values can be any expression, not only a
  quoted literal or a bare identifier:
  `WRITEFILE Filename, Name + ": " + Message`.
- `X <-- 5` is reported as a likely typo for `<-` instead of being read as
  `X <- -5`.

## How it works

```
Source text
    |
    v
+---------+   tokens   +----------+   AST   +---------------+
|  Lexer  | ---------> |  Parser  | ------> |  Interpreter  | --> output / errors
+---------+            +----------+         +---------------+
                                                    |
                                               symbol table
                                         (scopes, arrays, open files)
```

- **Lexer** ([engine/lexer.py](engine/lexer.py)) turns source text into
  tokens, each carrying its line and column span. Comments are dropped.
- **Parser** ([engine/parser.py](engine/parser.py)) is a recursive-descent
  parser that builds the AST defined in
  [engine/ast_nodes.py](engine/ast_nodes.py). Its module docstring holds
  the full grammar. It tracks which blocks are open so that a missing
  `ENDIF` or `NEXT` is reported against the block that was never closed.
- **Interpreter** ([engine/interpreter.py](engine/interpreter.py)) walks
  the AST, keeps the symbol table, enforces types and runs each statement.
- **Errors** ([engine/errors.py](engine/errors.py)) defines the one
  `PseudocodeError` type that all three stages raise. Unexpected Python
  exceptions are converted to it too, so a traceback never reaches a
  student.

### Web interface

- **Editor**: Monaco, loaded from a CDN, with a pseudocode language
  definition in
  [webapp/static/pseudocode-monaco.js](webapp/static/pseudocode-monaco.js)
  that provides syntax highlighting, auto-indentation and context-aware
  completion. Completion offers only what the grammar allows at the cursor,
  such as declared variables of a fitting type or the closing keyword of
  the innermost open block. The Python engine remains the only judge of
  whether a program is valid.
- **Running a program**: each Run starts a child process
  ([webapp/run_session.py](webapp/run_session.py)) so the server can
  force-stop a program that loops forever. The process gets a temporary
  directory for its files, which is deleted when the run ends, so runs
  cannot see each other's files and nothing persists between runs.
- **Live input**: the browser long-polls for events. When the program
  reaches `INPUT`, the worker blocks and the page shows a prompt. The
  execution timer is paused while a program waits for input.

| Route | Purpose |
|---|---|
| `GET /` | The editor page |
| `POST /api/run` | Start a program; returns `{run_id}` |
| `GET /api/run/<id>/poll?wait=<seconds>` | Fetch queued events and the run's state |
| `POST /api/run/<id>/input` | Supply the value for a pending `INPUT` |
| `POST /api/run/<id>/cancel` | Stop a run |
| `GET /api/health` | Wake-up check polled by the SudoLab site |

## Project structure

```
Pseudocode_Interpreter/
├── engine/
│   ├── tokens.py          Token types, keyword table, built-in function names
│   ├── lexer.py           Source text -> tokens
│   ├── ast_nodes.py       AST node dataclasses
│   ├── parser.py          Tokens -> AST (recursive descent)
│   ├── interpreter.py     AST -> execution (tree-walking)
│   └── errors.py          PseudocodeError and message helpers
├── webapp/
│   ├── app.py             Flask routes and request validation
│   ├── run_session.py     Per-run worker processes, timeouts and run limits
│   ├── templates/
│   │   └── index.html     Editor page
│   └── static/
│       ├── app.js                 Run / poll / input flow, error rendering
│       ├── pseudocode-monaco.js   Monaco language definition and completion
│       ├── style.css
│       └── favicon.png
├── Software Requirements Specification.pdf
├── Procfile               Deployment entry point (gunicorn)
├── gunicorn.conf.py       One worker process, 16 threads
└── requirements.txt
```

## Deployment

The `Procfile` starts the app with:

```bash
gunicorn webapp.app:app --config gunicorn.conf.py
```

Runs are tracked in memory in a single process, so the server must run
**exactly one worker process**. `gunicorn.conf.py` sets one worker with 16
threads; do not pass `--workers` / `-w` in the host's start command.

### Limits

Because the app is public and every Run is a separate process, the server
limits what a run and a client can use. The defaults are sized for Render's
free plan (512 MB RAM, 0.1 CPU).

| Limit | Default | Environment variable |
|---|---|---|
| Active execution time per run (paused while waiting for `INPUT`) | 10 s | `PSEUDOCODE_MAX_EXECUTION_SECONDS` |
| Longest wait at one `INPUT` prompt | 300 s | `PSEUDOCODE_MAX_INPUT_WAIT_SECONDS` |
| Run stopped after this long with no polling (page closed) | 150 s | `PSEUDOCODE_ABANDONED_RUN_SECONDS` |
| Ended runs forgotten after | 120 s | `PSEUDOCODE_RESULT_RETENTION_SECONDS` |
| Active runs, whole server | 6 | `PSEUDOCODE_MAX_ACTIVE_RUNS` |
| Active runs per client IP | 3 | `PSEUDOCODE_MAX_ACTIVE_RUNS_PER_CLIENT` |
| Runs started per client IP per minute | 30 | `PSEUDOCODE_MAX_RUN_STARTS_PER_MINUTE` |
| `OUTPUT` per run | 5,000 lines / 500,000 characters | `PSEUDOCODE_MAX_OUTPUT_LINES`, `PSEUDOCODE_MAX_OUTPUT_CHARS` |
| Worker memory (Linux only) | 64 MB | `PSEUDOCODE_WORKER_MEMORY_LIMIT_MB` |
| Program size / one `INPUT` value | 100,000 / 10,000 characters | constants in `webapp/app.py` |

On a larger instance, raise `PSEUDOCODE_MAX_ACTIVE_RUNS`, keeping
active runs × `PSEUDOCODE_WORKER_MEMORY_LIMIT_MB` below the instance's RAM
minus about 100 MB.

Other settings:

| Variable | Purpose |
|---|---|
| `PORT` | Port for `python webapp/app.py` (default 5000) |
| `TRUSTED_PROXY_COUNT` | How many `X-Forwarded-For` hops to trust. Defaults to 1 on Render (detected through `RENDER`) and 0 elsewhere. |
| `SUDOLAB_ORIGIN` | Origin allowed to fetch `/api/health` cross-origin (default `*`) |

Notes for operators:

- Clients are identified by IP address, because cookies are often blocked
  inside a third-party iframe. A classroom behind one school network
  shares an IP, so raise the per-client limits for that kind of use.
- On Linux, workers are forked from a preloaded fork server and run at a
  lower CPU priority than the web server. The memory cap and the priority
  change do not apply on Windows.
- The page tells the server to stop its run when it is closed, using
  `navigator.sendBeacon` on `pagehide`.

## Tests

The test suite is written with pytest and covers the lexer, parser,
interpreter, file handling, runtime safety and the web API. Run it with:

```bash
python -m pytest tests/ -v
```

## Known limitations

- Files do not persist between runs in the web interface; each run gets a
  fresh temporary directory.
- There is no way to save or share a program; the editor starts from the
  same sample each time the page loads.
- `READFILE` reads into a plain variable only, not an array element.
- The engine has no command-line entry point. Run programs through the web
  interface or the Python API above.
- Array elements are stored eagerly in a dictionary, which is simple and
  adequate for student programs but not memory-efficient.

## License

Copyright (C) 2026 MD SHOUROV HASAN

This project is licensed under the
[GNU Affero General Public License v3.0](LICENSE). You are free to use,
study, modify and share it, including in schools and classrooms. If you
distribute a modified version, or run one as a web service that other
people use, you must make your modified source code available under the
same license.
