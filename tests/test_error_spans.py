import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from engine.lexer import tokenize
from engine.parser import parse
from engine.interpreter import Interpreter
from engine.errors import PseudocodeError


def run_and_catch(src: str, inputs=None) -> PseudocodeError:
    program = parse(tokenize(src))
    queue = list(inputs or [])
    interp = Interpreter(input_fn=lambda: queue.pop(0) if queue else "")
    with pytest.raises(PseudocodeError) as exc_info:
        interp.run(program)
    return exc_info.value


def span_text(src: str, error: PseudocodeError) -> str:
    """The exact substring the reported span covers, for readable assertions."""
    line_text = src.split("\n")[error.line - 1]
    return line_text[error.column - 1 : error.end_column]


# ---- lexer/token columns -----------------------------------------------

def test_token_columns_basic():
    tokens = tokenize('Score <- "hello"')
    assert [(t.type.name, t.column) for t in tokens[:3]] == [
        ("IDENTIFIER", 1),
        ("ASSIGN", 7),
        ("STRING_LITERAL", 10),
    ]
    assert tokens[2].end_column == 16  # the closing quote


def test_token_columns_reset_after_newline():
    tokens = tokenize("X <- 1\nY <- 2")
    y_tok = next(t for t in tokens if t.lexeme == "Y")
    assert y_tok.line == 2
    assert y_tok.column == 1


# ---- category 1: undeclared identifier ---------------------------------

def test_undeclared_identifier_underlines_the_identifier():
    src = "DECLARE X : INTEGER\nX <- Y + 1"
    err = run_and_catch(src)
    assert err.column is not None
    assert span_text(src, err) == "Y"


def test_undeclared_identifier_as_assignment_target_has_span():
    src = "Y <- 5"
    err = run_and_catch(src)
    assert span_text(src, err) == "Y"


# ---- category 2: type mismatch on assignment (the reported example) ----

def test_type_mismatch_underlines_the_value_expression():
    src = 'DECLARE Score : INTEGER\nScore <- "hello"'
    err = run_and_catch(src)
    assert span_text(src, err) == '"hello"'
    assert err.line == 2


def test_type_mismatch_on_array_element_underlines_the_value_expression():
    src = 'DECLARE Numbers : ARRAY[1:5] OF INTEGER\nNumbers[1] <- "hello"'
    err = run_and_catch(src)
    assert span_text(src, err) == '"hello"'


def test_type_mismatch_underlines_whole_compound_expression():
    src = 'DECLARE X : BOOLEAN\nX <- 5 + 3'
    err = run_and_catch(src)
    assert span_text(src, err) == "5 + 3"


# ---- category 3: division by zero --------------------------------------

def test_division_by_zero_underlines_the_whole_expression():
    src = "DECLARE X : REAL\nX <- 5 / 0"
    err = run_and_catch(src)
    assert span_text(src, err) == "5 / 0"


def test_division_by_zero_inside_parentheses_widens_to_include_parens():
    # The span covers the whole binary expression (left operand through
    # right operand), not just the divisor — "10 / (2 - 2)" in full.
    src = "DECLARE X : REAL\nX <- 10 / (2 - 2)"
    err = run_and_catch(src)
    assert span_text(src, err) == "10 / (2 - 2)"


# ---- category 4: array bounds errors -----------------------------------

def test_array_bounds_error_underlines_the_bad_index():
    src = "DECLARE Numbers : ARRAY[1:5] OF INTEGER\nNumbers[10] <- 1"
    err = run_and_catch(src)
    assert span_text(src, err) == "10"


def test_2d_array_bounds_error_underlines_only_the_bad_index():
    src = "DECLARE Grid : ARRAY[1:3, 1:3] OF INTEGER\nGrid[1, 9] <- 1"
    err = run_and_catch(src)
    assert span_text(src, err) == "9"


def test_array_index_computed_expression_span_covers_whole_expression():
    src = "DECLARE Numbers : ARRAY[1:5] OF INTEGER\nDECLARE I : INTEGER\nI <- 10\nOUTPUT Numbers[I + 1]"
    err = run_and_catch(src)
    assert span_text(src, err) == "I + 1"


# ---- category 5: condition must be BOOLEAN -----------------------------

def test_if_condition_not_boolean_underlines_condition():
    src = "DECLARE X : INTEGER\nX <- 5\nIF X\nTHEN\nOUTPUT 1\nENDIF"
    err = run_and_catch(src)
    assert err.line == 3
    assert span_text(src, err) == "X"


def test_while_condition_not_boolean_underlines_condition():
    src = "DECLARE X : INTEGER\nX <- 5\nWHILE X DO\nENDWHILE"
    err = run_and_catch(src)
    assert span_text(src, err) == "X"


def test_repeat_until_condition_not_boolean_underlines_condition():
    src = "DECLARE X : INTEGER\nX <- 5\nREPEAT\nUNTIL X"
    err = run_and_catch(src)
    assert span_text(src, err) == "X"


def test_complex_boolean_condition_span_covers_whole_condition():
    # An arithmetic (non-relational) expression used directly as a
    # condition — the whole expression is what's blamed, not a sub-part.
    src = "DECLARE X : INTEGER\nX <- 5\nIF X + 1\nTHEN\nOUTPUT 1\nENDIF"
    err = run_and_catch(src)
    assert span_text(src, err) == "X + 1"


# ---- structural errors deliberately have no span -----------------------

def test_missing_endif_has_no_column_span():
    with pytest.raises(PseudocodeError) as exc_info:
        parse(tokenize("IF TRUE\nTHEN\nOUTPUT 1"))
    assert exc_info.value.column is None
    assert exc_info.value.end_column is None


def test_pseudocode_error_to_dict_includes_span_fields():
    src = 'DECLARE X : INTEGER\nX <- "hi"'
    err = run_and_catch(src)
    d = err.to_dict()
    assert "column" in d and "end_column" in d
    assert d["column"] is not None
