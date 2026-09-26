"""
AST node definitions.

Kept as plain dataclasses with no behaviour — the interpreter (Milestone
3+) is what gives these meaning. Every node carries `line` so runtime
errors can be reported against the original source line (NFR-10).

Node coverage: Program, Declare, ArrayDeclare, Constant, Input, Output,
If, Case, Assignment, ForLoop, RepeatLoop, WhileLoop, ProcedureDecl,
FunctionDecl, ProcedureCall, Return (statements — added across
Milestones 2, 5, 6, 7, 8), and Literal, Identifier, UnaryOp, BinaryOp,
Call, Index (expressions — added in Milestone 2; Index is also used as
an Assignment target as of Milestone 7).

Call is parsed as pure syntax (`name(...)`) from Milestone 2 onward,
but is given meaning gradually: built-in functions in Milestone 4, and
user-defined FUNCTION calls in Milestone 8 (Call.name is looked up
against both namespaces at interpretation time — see
Interpreter._eval_call). Index is likewise pure syntax until array
semantics arrive in Milestone 7.

ProcedureDecl/FunctionDecl (FR-10.1, FR-10.3) are parsed only at the
very top of a program, before any other statement — see the parser's
module docstring. ProcedureCall (FR-10.2) is the `CALL <identifier>
(...)` statement form; a FUNCTION is instead invoked through the
ordinary Call expression node above, per FR-10.4.
"""

from dataclasses import dataclass, field


# ---- Program -------------------------------------------------------------

@dataclass(slots=True)
class Program:
    statements: list


# ---- Statements (Milestone 2 subset) --------------------------------------

@dataclass(slots=True)
class Declare:
    """DECLARE <identifier list> : <data type>   (FR-3.1, extended to
    allow multiple comma-separated identifiers sharing one data type,
    e.g. DECLARE a, b, c : INTEGER). Array declarations use ArrayDeclare
    instead — see below."""
    identifiers: list
    data_type: str   # "INTEGER" | "REAL" | "CHAR" | "STRING" | "BOOLEAN"
    line: int


@dataclass(slots=True)
class ArrayDeclare:
    """DECLARE <identifier list> : ARRAY[<l>:<u>] OF <data type>   (FR-8.1)
    or the 2D form ARRAY[<lr>:<ur>, <lc>:<uc>] OF <data type>   (FR-8.3).

    `dimensions` is a list of (lower_expr, upper_expr) pairs — one pair
    for a 1D array, two for a 2D array — evaluated when the DECLARE
    runs (so a bound can be a CONSTANT, not just a literal). Like
    Declare, `identifiers` may name several arrays that all share the
    same shape and element type.
    """
    identifiers: list
    dimensions: list
    element_type: str
    line: int


@dataclass(slots=True)
class Constant:
    """CONSTANT <identifier> <- <value>   (FR-3.2)"""
    identifier: str
    value: object    # expression node
    line: int


@dataclass(slots=True)
class Input:
    """INPUT <identifier>   (FR-4.1), or INPUT <identifier>[<index>...]
    to read directly into an array element.

    `target` is an Identifier node for a plain variable, or an Index
    node for an array element — mirrors Assignment.target.
    """
    target: object
    line: int


@dataclass(slots=True)
class Output:
    """OUTPUT <value(s)>, comma-separated   (FR-4.2)"""
    values: list
    line: int


@dataclass(slots=True)
class If:
    """IF <condition> THEN ... [ELSE ...] ENDIF   (FR-7.1, FR-7.2)"""
    condition: object
    then_body: list
    else_body: list  # empty list if there is no ELSE clause
    line: int


@dataclass(slots=True)
class Case:
    """CASE OF <identifier> ... [OTHERWISE ...] ENDCASE   (FR-7.3, FR-7.4)

    `branches` is a list of (value_node, statement) pairs, tested in
    order; the first matching value's statement runs. `otherwise` is a
    single statement (or None) that runs only if nothing matched.
    """
    subject: str
    branches: list
    otherwise: object
    line: int


@dataclass(slots=True)
class Assignment:
    """<identifier> <- <value>   (FR-3.3), or <identifier>[<index>...] <- <value>
    for an array element (FR-8.2, FR-8.4).

    `target` is an Identifier node for a plain variable, or an Index
    node for an array element.
    """
    target: object
    value: object
    line: int


@dataclass(slots=True)
class ForLoop:
    """FOR <identifier> <- <start> TO <finish> [STEP <step>] ... NEXT <identifier>
    (FR-6.1, FR-6.2, FR-6.3). `step` is None when no STEP clause was
    written (the interpreter defaults it to 1)."""
    variable: str
    start: object
    finish: object
    step: object
    body: list
    line: int


@dataclass(slots=True)
class RepeatLoop:
    """REPEAT ... UNTIL <condition>   (FR-6.4) — post-conditional: the
    body always runs at least once, then stops once condition is TRUE."""
    body: list
    until_condition: object
    line: int


@dataclass(slots=True)
class WhileLoop:
    """WHILE <condition> DO ... ENDWHILE   (FR-6.5) — pre-conditional:
    the condition is tested before every iteration, including the first."""
    condition: object
    body: list
    line: int


@dataclass(slots=True)
class Param:
    """One `<identifier> : <data type>` entry in a PROCEDURE/FUNCTION
    parameter list (FR-10.1, FR-10.3). A parameter is always scalar and
    passed by value -- arrays cannot be passed as PROCEDURE/FUNCTION
    parameters (see this file's module docstring)."""
    name: str
    data_type: str


@dataclass(slots=True)
class ProcedureDecl:
    """PROCEDURE <identifier> [(<param> (',' <param>)*)] ... ENDPROCEDURE
    (FR-10.1). Only ever appears at the top of Program.statements — the
    parser accepts PROCEDURE/FUNCTION definitions solely before the
    first ordinary statement (SRS 3.10: "always defined at the top of
    the program")."""
    name: str
    params: list  # list[Param]
    body: list
    line: int


@dataclass(slots=True)
class FunctionDecl:
    """FUNCTION <identifier> [(<param> (',' <param>)*)] RETURNS <data type>
    ... ENDFUNCTION (FR-10.3). Placement rules mirror ProcedureDecl."""
    name: str
    params: list  # list[Param]
    return_type: str
    body: list
    line: int


@dataclass(slots=True)
class ProcedureCall:
    """CALL <identifier> or CALL <identifier>(<val1>, ...)   (FR-10.2).
    A statement, unlike a FUNCTION call, which is the `Call` expression
    node below used inside an expression (FR-10.4)."""
    name: str
    args: list
    line: int


@dataclass(slots=True)
class Return:
    """RETURN <expression>   (FR-10.3). Only valid inside a FUNCTION
    body — enforced structurally by the parser, which tracks whether it
    is currently inside a PROCEDURE or a FUNCTION."""
    value: object
    line: int


# ---- Expressions -----------------------------------------------------
#
# Every expression node also carries `column`/`end_column`: a 1-based,
# inclusive character span on `line` covering exactly the source text this
# node came from (e.g. a BinaryOp's span runs from its left operand's start
# through its right operand's end; a parenthesised expression's span is
# widened to include the parentheses). The interpreter attaches these spans
# to PseudocodeError so the frontend can underline the offending text --
# see engine/errors.py. They play no role in evaluation.


@dataclass(slots=True)
class Literal:
    value: object     # the Python value: int / float / str / bool
    data_type: str    # "INTEGER" | "REAL" | "CHAR" | "STRING" | "BOOLEAN"
    line: int
    column: int
    end_column: int


@dataclass(slots=True)
class Identifier:
    name: str
    line: int
    column: int
    end_column: int


@dataclass(slots=True)
class UnaryOp:
    op: str           # "-" | "NOT"
    operand: object
    line: int
    column: int
    end_column: int


@dataclass(slots=True)
class BinaryOp:
    op: str           # "+" "-" "*" "/" "^" "=" "<" "<=" ">" ">=" "<>" "AND" "OR"
    left: object
    right: object
    line: int
    column: int
    end_column: int


@dataclass(slots=True)
class Call:
    """name(arg1, arg2, ...) — a built-in or user function call."""
    name: str
    args: list
    line: int
    column: int
    end_column: int


@dataclass(slots=True)
class Index:
    """name[idx1] or name[idx1, idx2] — 1D/2D array element access."""
    name: str
    indices: list
    line: int
    column: int
    end_column: int