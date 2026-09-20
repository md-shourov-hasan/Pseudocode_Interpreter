"""
AST node definitions.

Kept as plain dataclasses with no behaviour — the interpreter (Milestone
3+) is what gives these meaning. Every node carries `line` so runtime
errors can be reported against the original source line (NFR-10).

Node coverage: Program, Declare, ArrayDeclare, Constant, Input, Output,
If, Case, Assignment, ForLoop, RepeatLoop, WhileLoop (statements —
added across Milestones 2, 5, 6, 7), and Literal, Identifier, UnaryOp,
BinaryOp, Call, Index (expressions — added in Milestone 2; Index is
also used as an Assignment target as of Milestone 7), plus ArrayLiteral
(the [v1, v2, ...] list that fills a whole array; only ever the value of
an Assignment).

Call and Index are parsed now (they're pure syntax: `name(...)` /
`name[...]`) but not yet given meaning — built-in functions arrive in
Milestone 4, array semantics in Milestone 7, user procedures/functions
in Milestone 8.
"""

from dataclasses import dataclass, field


# ---- Program -------------------------------------------------------------

@dataclass
class Program:
    statements: list


# ---- Statements (Milestone 2 subset) --------------------------------------

@dataclass
class Declare:
    """DECLARE <identifier list> : <data type>   (FR-3.1, extended to
    allow multiple comma-separated identifiers sharing one data type,
    e.g. DECLARE a, b, c : INTEGER). Array declarations use ArrayDeclare
    instead — see below."""
    identifiers: list
    data_type: str   # "INTEGER" | "REAL" | "CHAR" | "STRING" | "BOOLEAN"
    line: int


@dataclass
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


@dataclass
class Constant:
    """CONSTANT <identifier> <- <value>   (FR-3.2)"""
    identifier: str
    value: object    # expression node
    line: int


@dataclass
class Input:
    """INPUT <identifier>   (FR-4.1), or INPUT <identifier>[<index>...]
    to read directly into an array element.

    `target` is an Identifier node for a plain variable, or an Index
    node for an array element — mirrors Assignment.target.
    """
    target: object
    line: int


@dataclass
class Output:
    """OUTPUT <value(s)>, comma-separated   (FR-4.2)"""
    values: list
    line: int


@dataclass
class If:
    """IF <condition> THEN ... [ELSE ...] ENDIF   (FR-7.1, FR-7.2)"""
    condition: object
    then_body: list
    else_body: list  # empty list if there is no ELSE clause
    line: int


@dataclass
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


@dataclass
class Assignment:
    """<identifier> <- <value>   (FR-3.3), or <identifier>[<index>...] <- <value>
    for an array element (FR-8.2, FR-8.4).

    `target` is an Identifier node for a plain variable, or an Index
    node for an array element.
    """
    target: object
    value: object
    line: int


@dataclass
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


@dataclass
class RepeatLoop:
    """REPEAT ... UNTIL <condition>   (FR-6.4) — post-conditional: the
    body always runs at least once, then stops once condition is TRUE."""
    body: list
    until_condition: object
    line: int


@dataclass
class WhileLoop:
    """WHILE <condition> DO ... ENDWHILE   (FR-6.5) — pre-conditional:
    the condition is tested before every iteration, including the first."""
    condition: object
    body: list
    line: int


# ---- Expressions -----------------------------------------------------

@dataclass
class Literal:
    value: object     # the Python value: int / float / str / bool
    data_type: str    # "INTEGER" | "REAL" | "CHAR" | "STRING" | "BOOLEAN"
    line: int


@dataclass
class Identifier:
    name: str
    line: int


@dataclass
class UnaryOp:
    op: str           # "-" | "NOT"
    operand: object
    line: int


@dataclass
class BinaryOp:
    op: str           # "+" "-" "*" "/" "^" "=" "<" "<=" ">" ">=" "<>" "AND" "OR"
    left: object
    right: object
    line: int


@dataclass
class Call:
    """name(arg1, arg2, ...) — a built-in or user function call."""
    name: str
    args: list
    line: int


@dataclass
class Index:
    """name[idx1] or name[idx1, idx2] — 1D/2D array element access."""
    name: str
    indices: list
    line: int


@dataclass
class ArrayLiteral:
    """[value, value, ...] — a list of values that fills a whole array in one
    assignment:  MyArray <- ["Cat", "Dog", "Rayan"].

    `elements` holds expression nodes. For a 2D array each element is itself an
    ArrayLiteral (one per row): Grid <- [[1, 2], [3, 4]]. An ArrayLiteral is
    only ever the `value` of an Assignment whose target is a whole array; the
    interpreter checks it against the array's declared shape and element type.
    """
    elements: list
    line: int
