"""
AST node definitions.

Kept as plain dataclasses with no behaviour — the interpreter (Milestone
3+) is what gives these meaning. Every node carries `line` so runtime
errors can be reported against the original source line (NFR-10).

Node coverage in this milestone (Milestone 2):
    Program, Declare, Constant, Assignment,
    Literal, Identifier, UnaryOp, BinaryOp, Call, Index

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
    e.g. DECLARE a, b, c : INTEGER)."""
    identifiers: list
    data_type: str   # "INTEGER" | "REAL" | "CHAR" | "STRING" | "BOOLEAN"
    line: int


@dataclass
class Constant:
    """CONSTANT <identifier> <- <value>   (FR-3.2)"""
    identifier: str
    value: object    # expression node
    line: int


@dataclass
class Input:
    """INPUT <identifier>   (FR-4.1)"""
    identifier: str
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
    """<identifier> <- <value>   (FR-3.3)

    `target` is an Identifier node for a plain variable in this
    milestone. Milestone 7 extends this to Index targets for array
    element assignment (e.g. Grade[16, 3] <- 'A').
    """
    target: object
    value: object
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
