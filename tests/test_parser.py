import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from engine.lexer import tokenize
from engine.parser import parse
from engine.errors import PseudocodeError
from engine import ast_nodes as ast


def parse_src(src: str) -> ast.Program:
    return parse(tokenize(src))


# ---- DECLARE / CONSTANT / assignment (FR-3.x) -----------------------------

def test_declare_statement():
    prog = parse_src("DECLARE NumTeams : INTEGER")
    stmt = prog.statements[0]
    assert isinstance(stmt, ast.Declare)
    assert stmt.identifiers == ["NumTeams"]
    assert stmt.data_type == "INTEGER"


def test_declare_multiple_identifiers_same_type():
    prog = parse_src("DECLARE a, b, c : INTEGER")
    stmt = prog.statements[0]
    assert isinstance(stmt, ast.Declare)
    assert stmt.identifiers == ["a", "b", "c"]
    assert stmt.data_type == "INTEGER"


def test_declare_rejects_missing_colon():
    with pytest.raises(PseudocodeError):
        parse_src("DECLARE NumTeams INTEGER")


def test_declare_rejects_unknown_type():
    with pytest.raises(PseudocodeError):
        parse_src("DECLARE NumTeams : NUMBER")


def test_constant_statement():
    prog = parse_src("CONSTANT UpperBound <- 15")
    stmt = prog.statements[0]
    assert isinstance(stmt, ast.Constant)
    assert stmt.identifier == "UpperBound"
    assert isinstance(stmt.value, ast.Literal)
    assert stmt.value.value == 15


def test_assignment_with_identifier_value():
    prog = parse_src("MaxAttempt <- 4")
    stmt = prog.statements[0]
    assert isinstance(stmt, ast.Assignment)
    assert stmt.target.name == "MaxAttempt"
    assert stmt.value.value == 4


def test_assignment_with_expression_value():
    prog = parse_src("ActualScore <- Score * 100")
    stmt = prog.statements[0]
    assert isinstance(stmt.value, ast.BinaryOp)
    assert stmt.value.op == "*"
    assert isinstance(stmt.value.left, ast.Identifier) and stmt.value.left.name == "Score"
    assert stmt.value.right.value == 100


def test_multiple_statements_across_lines():
    src = "DECLARE NumTeams : INTEGER\nCONSTANT UpperBound <- 15\nMaxAttempt <- 4"
    prog = parse_src(src)
    assert len(prog.statements) == 3
    assert isinstance(prog.statements[0], ast.Declare)
    assert isinstance(prog.statements[1], ast.Constant)
    assert isinstance(prog.statements[2], ast.Assignment)


def test_blank_lines_between_statements_are_skipped():
    src = "DECLARE X : INTEGER\n\n\nX <- 5"
    prog = parse_src(src)
    assert len(prog.statements) == 2


def test_array_declare_not_yet_supported_gives_clear_error():
    with pytest.raises(PseudocodeError, match="supported yet"):
        parse_src("DECLARE Grade : ARRAY[1:30] OF CHAR")


def test_indexed_assignment_not_yet_supported_gives_clear_error():
    with pytest.raises(PseudocodeError, match="supported yet"):
        parse_src("Grade[16] <- 'A'")


def test_statement_must_end_at_newline():
    # two statements glued on one line with no separator is a syntax error
    with pytest.raises(PseudocodeError):
        parse_src("X <- 5 Y <- 6")


# ---- expression precedence (FR-5.1, FR-5.4) --------------------------------

def _expr(src: str):
    """Parse a bare expression by wrapping it in an assignment."""
    prog = parse_src(f"Result <- {src}")
    return prog.statements[0].value


def test_arithmetic_precedence_mul_before_add():
    # 2 + 3 * 4 => 2 + (3 * 4)
    e = _expr("2 + 3 * 4")
    assert isinstance(e, ast.BinaryOp) and e.op == "+"
    assert e.left.value == 2
    assert isinstance(e.right, ast.BinaryOp) and e.right.op == "*"


def test_left_associativity_of_addition():
    # 1 - 2 - 3 => (1 - 2) - 3
    e = _expr("1 - 2 - 3")
    assert e.op == "-"
    assert isinstance(e.left, ast.BinaryOp) and e.left.op == "-"
    assert e.right.value == 3


def test_power_is_right_associative():
    # 2 ^ 3 ^ 2 => 2 ^ (3 ^ 2)
    e = _expr("2 ^ 3 ^ 2")
    assert e.op == "^"
    assert e.left.value == 2
    assert isinstance(e.right, ast.BinaryOp) and e.right.op == "^"


def test_unary_minus_binds_looser_than_power():
    # -2 ^ 2 => -(2 ^ 2)   (matches Python's own -2**2 == -4 convention)
    e = _expr("-2 ^ 2")
    assert isinstance(e, ast.UnaryOp) and e.op == "-"
    assert isinstance(e.operand, ast.BinaryOp) and e.operand.op == "^"


def test_power_exponent_can_be_unary():
    # 2 ^ -2 => 2 ^ (-2)
    e = _expr("2 ^ -2")
    assert e.op == "^"
    assert isinstance(e.right, ast.UnaryOp) and e.right.op == "-"


def test_parentheses_override_precedence():
    # (2 + 3) * 4
    e = _expr("(2 + 3) * 4")
    assert e.op == "*"
    assert isinstance(e.left, ast.BinaryOp) and e.left.op == "+"


def test_relational_operator_produces_binaryop():
    e = _expr("Answer = CorrectAnswer")
    assert isinstance(e, ast.BinaryOp) and e.op == "="
    assert e.left.name == "Answer"
    assert e.right.name == "CorrectAnswer"


def test_procedure_call_example_expression():
    # (RawScore/60) * 100  -- from the SRS CalculateScore example
    e = _expr("(RawScore/60) * 100")
    assert e.op == "*"
    assert isinstance(e.left, ast.BinaryOp) and e.left.op == "/"
    assert e.right.value == 100


def test_function_call_parses_as_call_node():
    e = _expr("ROUND(3.1415, 1)")
    assert isinstance(e, ast.Call)
    assert e.name == "ROUND"
    assert len(e.args) == 2
    assert e.args[0].value == 3.1415
    assert e.args[1].value == 1


def test_array_index_parses_as_index_node_1d():
    e = _expr("Numbers[Index]")
    assert isinstance(e, ast.Index)
    assert e.name == "Numbers"
    assert len(e.indices) == 1


def test_array_index_parses_as_index_node_2d():
    e = _expr("Grade[16, 3]")
    assert isinstance(e, ast.Index)
    assert e.name == "Grade"
    assert len(e.indices) == 2


def test_sumsquare_function_body_expression():
    # Num1 ^ 2 + Num2 ^ 2  -- from the SRS SumSquare example
    e = _expr("Num1 ^ 2 + Num2 ^ 2")
    assert e.op == "+"
    assert e.left.op == "^" and e.left.left.name == "Num1"
    assert e.right.op == "^" and e.right.left.name == "Num2"
