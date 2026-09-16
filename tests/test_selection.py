import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from engine.lexer import tokenize
from engine.parser import parse
from engine.interpreter import Interpreter
from engine.errors import PseudocodeError
from engine import ast_nodes as ast


def run_src(src: str, inputs=None):
    program = parse(tokenize(src))
    queue = list(inputs or [])
    interp = Interpreter(input_fn=lambda: queue.pop(0) if queue else "")
    output = interp.run(program)
    return output, interp


def parse_src(src: str):
    return parse(tokenize(src))


# ---- IF parsing (FR-7.1, FR-7.2) -------------------------------------------

def test_if_without_else_parses():
    prog = parse_src("IF Flag\nTHEN\nX <- 1\nENDIF")
    stmt = prog.statements[0]
    assert isinstance(stmt, ast.If)
    assert len(stmt.then_body) == 1
    assert stmt.else_body == []


def test_if_with_else_parses():
    prog = parse_src("IF Flag\nTHEN\nX <- 1\nELSE\nX <- 2\nENDIF")
    stmt = prog.statements[0]
    assert len(stmt.then_body) == 1
    assert len(stmt.else_body) == 1


def test_missing_endif_is_clear_error():
    with pytest.raises(PseudocodeError, match="ENDIF"):
        parse_src("IF Flag\nTHEN\nX <- 1")


def test_nested_if_inside_if():
    src = (
        "IF A\n"
        "THEN\n"
        " IF B\n"
        " THEN\n"
        "  X <- 1\n"
        " ENDIF\n"
        "ENDIF"
    )
    prog = parse_src(src)
    outer = prog.statements[0]
    inner = outer.then_body[0]
    assert isinstance(inner, ast.If)


# ---- IF execution -----------------------------------------------------

def test_srs_if_else_example():
    src = (
        "DECLARE Answer : INTEGER\n"
        "DECLARE CorrectAnswer : INTEGER\n"
        "DECLARE Score : INTEGER\n"
        "Answer <- 5\n"
        "CorrectAnswer <- 5\n"
        "Score <- 0\n"
        "IF Answer = CorrectAnswer\n"
        "THEN\n"
        " Score <- Score + 1\n"
        "ELSE\n"
        ' OUTPUT "Wrong Answer!"\n'
        "ENDIF\n"
        "OUTPUT Score"
    )
    output, interp = run_src(src)
    assert interp.symbols["Score"].value == 1
    assert output == ["1"]


def test_srs_if_else_example_wrong_answer_branch():
    src = (
        "DECLARE Answer : INTEGER\n"
        "DECLARE CorrectAnswer : INTEGER\n"
        "Answer <- 3\n"
        "CorrectAnswer <- 5\n"
        "IF Answer = CorrectAnswer\n"
        "THEN\n"
        " OUTPUT \"Correct!\"\n"
        "ELSE\n"
        ' OUTPUT "Wrong Answer!"\n'
        "ENDIF"
    )
    output, _ = run_src(src)
    assert output == ["Wrong Answer!"]


def test_if_without_else_skips_when_false():
    output, interp = run_src(
        "DECLARE X : INTEGER\nX <- 0\nIF X = 1\nTHEN\nX <- 99\nENDIF\nOUTPUT X"
    )
    assert output == ["0"]


def test_if_condition_must_be_boolean():
    with pytest.raises(PseudocodeError, match="BOOLEAN"):
        run_src("DECLARE X : INTEGER\nX <- 5\nIF X\nTHEN\nOUTPUT \"hi\"\nENDIF")


# ---- CASE OF (FR-7.3, FR-7.4) ------------------------------------------

def test_srs_case_of_example_each_direction():
    src = (
        "DECLARE Movement : CHAR\n"
        "DECLARE xcord : INTEGER\n"
        "DECLARE ycord : INTEGER\n"
        "xcord <- 0\n"
        "ycord <- 0\n"
        "Movement <- 'w'\n"
        "CASE OF Movement\n"
        " 'w' : ycord <- ycord + 1\n"
        " 'a' : xcord <- xcord - 1\n"
        " 's' : ycord <- ycord - 1\n"
        " 'd' : xcord <- xcord + 1\n"
        ' OTHERWISE OUTPUT "Invalid choice!"\n'
        "ENDCASE\n"
        "OUTPUT xcord, ycord"
    )
    output, interp = run_src(src)
    assert interp.symbols["ycord"].value == 1
    assert interp.symbols["xcord"].value == 0
    assert output == ["01"]


def test_case_of_falls_to_otherwise_when_no_match():
    src = (
        "DECLARE Movement : CHAR\n"
        "Movement <- 'z'\n"
        "CASE OF Movement\n"
        " 'w' : OUTPUT \"up\"\n"
        ' OTHERWISE OUTPUT "Invalid choice!"\n'
        "ENDCASE"
    )
    output, _ = run_src(src)
    assert output == ["Invalid choice!"]


def test_case_of_only_first_matching_branch_runs():
    # subject matches 'w'; only that branch's statement should execute
    src = (
        "DECLARE Movement : CHAR\n"
        "DECLARE Counter : INTEGER\n"
        "Counter <- 0\n"
        "Movement <- 'w'\n"
        "CASE OF Movement\n"
        " 'w' : Counter <- Counter + 1\n"
        " 'a' : Counter <- Counter + 100\n"
        "ENDCASE"
    )
    _, interp = run_src(src)
    assert interp.symbols["Counter"].value == 1


def test_case_of_with_no_otherwise_and_no_match_does_nothing():
    output, _ = run_src(
        "DECLARE Movement : CHAR\nMovement <- 'z'\nCASE OF Movement\n 'w' : OUTPUT \"up\"\nENDCASE"
    )
    assert output == []


def test_missing_endcase_is_clear_error():
    with pytest.raises(PseudocodeError, match="ENDCASE"):
        parse_src("CASE OF X\n 1 : OUTPUT \"one\"")


def test_case_of_integer_subject():
    output, _ = run_src(
        "DECLARE Grade : INTEGER\nGrade <- 2\n"
        "CASE OF Grade\n 1 : OUTPUT \"A\"\n 2 : OUTPUT \"B\"\n 3 : OUTPUT \"C\"\nENDCASE"
    )
    assert output == ["B"]


def test_case_boolean_does_not_match_integer_branch():
    # A BOOLEAN subject should not accidentally match an INTEGER 1 branch
    # (Python's True == 1, but pseudocode BOOLEAN and INTEGER stay distinct).
    output, _ = run_src(
        "DECLARE Flag : BOOLEAN\nFlag <- TRUE\n"
        "CASE OF Flag\n 1 : OUTPUT \"one\"\nENDCASE"
    )
    assert output == []
