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
    FR-4.1        INPUT reads a value from the user
    FR-4.2        OUTPUT displays one or more values
    FR-5.1        Arithmetic operators (+ - * / ^)
    FR-5.4        Relational operators (= < <= > >= <>)
    FR-7.1        IF ... THEN ... ENDIF (no ELSE)
    FR-7.2        IF ... THEN ... ELSE ... ENDIF
    FR-7.3        CASE OF ... ENDCASE, first matching value wins
    FR-7.4        CASE OF ... OTHERWISE ... ENDCASE
    FR-11.2       Undeclared identifier -> error, not silent execution
    FR-11.3       Incompatible assignment -> error, not silent execution
    (ext)         AND / OR / NOT boolean connectives in conditions,
                  requested beyond the reference syntax guide

Two deliberate deviations from strict type-mismatch behaviour
(requested; see the comments at their call sites):
  - Assigning a REAL value into an INTEGER variable truncates toward
    zero instead of raising an error (division always yields a float
    in the underlying arithmetic, even for exact quotients).
  - OUTPUT of a REAL value is rounded to at most 5 decimal places,
    with insignificant trailing zeros trimmed.

Not yet implemented (later milestones): library functions (M4),
iteration (M6), arrays (M7), procedures/functions (M8), file
handling (M9).

Design: a tree-walking interpreter. `Interpreter.run(program)` executes
every statement in order and returns the list of OUTPUT lines produced
(the web frontend in Milestone 12 will stream these instead of
collecting them, but batching them is simplest for now and for tests).
INPUT is satisfied by an injectable `input_fn` so tests don't need a
real stdin/stdout, and so Milestone 12 can wire it up to a web prompt.
"""

from . import ast_nodes as ast
from .errors import PseudocodeError

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


class Symbol:
    __slots__ = ("data_type", "value", "is_constant")

    def __init__(self, data_type: str, value, is_constant: bool):
        self.data_type = data_type
        self.value = value
        self.is_constant = is_constant


class Interpreter:
    def __init__(self, input_fn=None, output_fn=None):
        """
        input_fn:  callable() -> str, used to satisfy INPUT statements.
                   Defaults to the real `input()`.
        output_fn: callable(str) -> None, called once per OUTPUT statement
                   with the fully-formatted line. Defaults to collecting
                   lines into self.output (and also printing them).
        """
        self.symbols: dict[str, Symbol] = {}
        self.output: list[str] = []
        self._input_fn = input_fn if input_fn is not None else input
        self._output_fn = output_fn if output_fn is not None else self.output.append

    # ---- public API -----------------------------------------------------

    def run(self, program: ast.Program) -> list[str]:
        for stmt in program.statements:
            self._exec_statement(stmt)
        return self.output

    # ---- statement execution --------------------------------------------

    def _exec_statement(self, stmt):
        handler = self._STATEMENT_HANDLERS.get(type(stmt))
        if handler is None:
            raise PseudocodeError(
                getattr(stmt, "line", 0),
                f"This kind of statement isn't supported yet ({type(stmt).__name__}).",
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

    def _exec_constant(self, stmt: ast.Constant):
        if stmt.identifier in self.symbols:
            raise PseudocodeError(
                stmt.line,
                f"'{stmt.identifier}' has already been declared.",
            )
        value = self._eval(stmt.value)
        data_type = self._infer_type(value, stmt.line, stmt.identifier)
        self.symbols[stmt.identifier] = Symbol(data_type, value, is_constant=True)

    def _exec_assignment(self, stmt: ast.Assignment):
        name = stmt.target.name
        symbol = self.symbols.get(name)
        if symbol is None:
            raise PseudocodeError(
                stmt.line,
                f"'{name}' is used here but was never declared with DECLARE.",
            )
        if symbol.is_constant:
            raise PseudocodeError(
                stmt.line,
                f"'{name}' is a CONSTANT and cannot be reassigned.",
            )
        value = self._eval(stmt.value)
        # A REAL result (e.g. from "/") assigned into an INTEGER variable is
        # narrowed by truncating toward zero, rather than treated as a type
        # error — this is a deliberate product decision (requested), since
        # ordinary division always produces a float in the underlying
        # arithmetic even when the mathematical quotient looks INTEGER-like.
        if symbol.data_type == "INTEGER" and isinstance(value, float) and not isinstance(value, bool):
            value = int(value)
        self._check_assignable(symbol.data_type, value, stmt.line, name)
        # INTEGER assigned into a REAL variable is widened, per FR-2.2 semantics.
        if symbol.data_type == "REAL" and isinstance(value, int) and not isinstance(value, bool):
            value = float(value)
        symbol.value = value

    def _exec_input(self, stmt):
        name = stmt.identifier
        symbol = self.symbols.get(name)
        if symbol is None:
            raise PseudocodeError(
                stmt.line,
                f"'{name}' is used here but was never declared with DECLARE.",
            )
        raw = self._input_fn()
        try:
            value = self._coerce_input(raw, symbol.data_type)
        except ValueError:
            raise PseudocodeError(
                stmt.line,
                f"Couldn't read '{raw}' as a {symbol.data_type} value for '{name}'.",
            )
        symbol.value = value

    def _exec_output(self, stmt):
        parts = [self._format_value(self._eval(v)) for v in stmt.values]
        self._output_fn("".join(parts))

    def _exec_if(self, stmt: ast.If):
        condition = self._eval(stmt.condition)
        if not isinstance(condition, bool):
            raise PseudocodeError(
                stmt.line,
                f"The IF condition must evaluate to a BOOLEAN value, but got {self._type_name(condition)}.",
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

    # ---- expression evaluation --------------------------------------------

    def _eval(self, node):
        method = self._EXPR_HANDLERS.get(type(node))
        if method is None:
            raise PseudocodeError(
                getattr(node, "line", 0),
                f"This kind of expression isn't supported yet ({type(node).__name__}).",
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
            )
        return symbol.value

    def _eval_unary(self, node: ast.UnaryOp):
        value = self._eval(node.operand)
        if node.op == "-":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise PseudocodeError(
                    node.line, "The '-' operator can only be used on INTEGER or REAL values."
                )
            return -value
        if node.op == "NOT":
            if not isinstance(value, bool):
                raise PseudocodeError(
                    node.line,
                    f"The NOT operator needs a BOOLEAN value, but got {self._type_name(value)}.",
                )
            return not value
        raise PseudocodeError(node.line, f"Unknown unary operator '{node.op}'.")

    def _eval_binary(self, node: ast.BinaryOp):
        left = self._eval(node.left)
        right = self._eval(node.right)
        op = node.op

        if op in ("+", "-", "*", "/", "^"):
            return self._eval_arithmetic(op, left, right, node.line)
        if op in ("=", "<", "<=", ">", ">=", "<>"):
            return self._eval_relational(op, left, right, node.line)
        if op in ("AND", "OR"):
            return self._eval_logical(op, left, right, node.line)
        raise PseudocodeError(node.line, f"Unknown operator '{op}'.")

    def _eval_logical(self, op, left, right, line):
        # Both sides are evaluated (no short-circuiting) — see the parser's
        # module docstring for the reasoning.
        for v in (left, right):
            if not isinstance(v, bool):
                raise PseudocodeError(
                    line,
                    f"The '{op}' operator needs BOOLEAN values on both sides, but got {self._type_name(v)}.",
                )
        return (left and right) if op == "AND" else (left or right)

    def _eval_arithmetic(self, op, left, right, line):
        if op == "+" and isinstance(left, str) and isinstance(right, str):
            return left + right  # string concatenation, common in student code
        for v in (left, right):
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise PseudocodeError(
                    line,
                    f"The '{op}' operator needs INTEGER or REAL values on both sides.",
                )
        if op == "+":
            return left + right
        if op == "-":
            return left - right
        if op == "*":
            return left * right
        if op == "/":
            if right == 0:
                raise PseudocodeError(line, "Division by zero.")
            result = left / right
            return result
        if op == "^":
            return left ** right

    def _eval_relational(self, op, left, right, line):
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
                line, f"Can't compare {self._type_name(left)} and {self._type_name(right)} with '{op}'."
            )

    def _eval_call(self, node: ast.Call):
        raise PseudocodeError(
            node.line,
            f"'{node.name}(...)' isn't supported yet — built-in functions arrive in a later milestone.",
        )

    def _eval_index(self, node: ast.Index):
        raise PseudocodeError(
            node.line,
            f"Array indexing on '{node.name}' isn't supported yet — arrays arrive in a later milestone.",
        )

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
        raise PseudocodeError(line, f"Couldn't determine a data type for '{name}'.")

    def _check_assignable(self, data_type, value, line, name):
        valid_types = _PYTHON_TYPES_FOR[data_type]
        # bool is a subclass of int in Python — keep BOOLEAN and INTEGER distinct.
        if data_type != "BOOLEAN" and isinstance(value, bool):
            raise PseudocodeError(
                line,
                f"Can't assign a BOOLEAN value to '{name}', which is declared as {data_type}.",
            )
        if data_type == "BOOLEAN" and not isinstance(value, bool):
            raise PseudocodeError(
                line,
                f"Can't assign a {self._type_name(value)} value to '{name}', which is declared as BOOLEAN.",
            )
        if not isinstance(value, valid_types):
            raise PseudocodeError(
                line,
                f"Can't assign a {self._type_name(value)} value to '{name}', which is declared as {data_type}.",
            )
        if data_type == "CHAR" and isinstance(value, str) and len(value) != 1:
            raise PseudocodeError(
                line,
                f"Can't assign a STRING value to '{name}', which is declared as CHAR "
                f"(CHAR holds exactly one character).",
            )

    def _type_name(self, value) -> str:
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
        return type(value).__name__

    def _coerce_input(self, raw: str, data_type: str):
        if data_type == "INTEGER":
            return int(raw)
        if data_type == "REAL":
            return float(raw)
        if data_type == "BOOLEAN":
            if raw.strip().upper() in ("TRUE",):
                return True
            if raw.strip().upper() in ("FALSE",):
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


Interpreter._STATEMENT_HANDLERS = {
    ast.Declare: Interpreter._exec_declare,
    ast.Constant: Interpreter._exec_constant,
    ast.Assignment: Interpreter._exec_assignment,
    ast.Input: Interpreter._exec_input,
    ast.Output: Interpreter._exec_output,
    ast.If: Interpreter._exec_if,
    ast.Case: Interpreter._exec_case,
}

Interpreter._EXPR_HANDLERS = {
    ast.Literal: Interpreter._eval_literal,
    ast.Identifier: Interpreter._eval_identifier,
    ast.UnaryOp: Interpreter._eval_unary,
    ast.BinaryOp: Interpreter._eval_binary,
    ast.Call: Interpreter._eval_call,
    ast.Index: Interpreter._eval_index,
}


def run(program: ast.Program, input_fn=None, output_fn=None) -> list[str]:
    """Convenience wrapper: run a full Program and return its output lines."""
    return Interpreter(input_fn=input_fn, output_fn=output_fn).run(program)
