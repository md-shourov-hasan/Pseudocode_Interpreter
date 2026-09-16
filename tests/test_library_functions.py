import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from engine.lexer import tokenize
from engine.parser import parse
from engine.interpreter import Interpreter
from engine.errors import PseudocodeError


def run_src(src: str, inputs=None):
    program = parse(tokenize(src))
    queue = list(inputs or [])
    interp = Interpreter(input_fn=lambda: queue.pop(0) if queue else "")
    output = interp.run(program)
    return output, interp


# ---- ROUND (FR-4.3) ----------------------------------------------------

def test_round_srs_example():
    _, interp = run_src("DECLARE X : REAL\nX <- ROUND(3.1415, 1)")
    assert interp.symbols["X"].value == pytest.approx(3.1)


def test_round_with_integer_value():
    _, interp = run_src("DECLARE X : REAL\nX <- ROUND(5, 2)")
    assert interp.symbols["X"].value == 5.0


def test_round_wrong_arg_count_is_clear_error():
    with pytest.raises(PseudocodeError, match="2 arguments"):
        run_src("DECLARE X : REAL\nX <- ROUND(3.14)")


def test_round_places_must_be_integer():
    with pytest.raises(PseudocodeError):
        run_src('DECLARE X : REAL\nX <- ROUND(3.14, "one")')


# ---- RANDOM (FR-4.4) ----------------------------------------------------

def test_random_returns_value_in_zero_one_range():
    _, interp = run_src("DECLARE X : REAL\nX <- RANDOM()")
    assert 0 <= interp.symbols["X"].value < 1


def test_random_srs_example_scaled():
    output, interp = run_src("DECLARE X : REAL\nX <- RANDOM() * 5")
    assert 0 <= interp.symbols["X"].value < 5


def test_random_rejects_arguments():
    with pytest.raises(PseudocodeError, match="0 arguments"):
        run_src("DECLARE X : REAL\nX <- RANDOM(1)")


# ---- DIV / MOD (FR-5.2, FR-5.3) ----------------------------------------

def test_div_basic():
    _, interp = run_src("DECLARE X : INTEGER\nX <- DIV(17, 5)")
    assert interp.symbols["X"].value == 3


def test_mod_basic():
    _, interp = run_src("DECLARE X : INTEGER\nX <- MOD(17, 5)")
    assert interp.symbols["X"].value == 2


def test_div_mod_negative_dividend_truncates_toward_zero():
    # -17 / 5 = -3.4 -> DIV truncates to -3 (not floor, which would be -4)
    _, interp = run_src("DECLARE X : INTEGER\nX <- DIV(-17, 5)")
    assert interp.symbols["X"].value == -3
    _, interp = run_src("DECLARE Y : INTEGER\nY <- MOD(-17, 5)")
    assert interp.symbols["Y"].value == -2  # -17 = 5*(-3) + (-2)


def test_div_by_zero_is_error():
    with pytest.raises(PseudocodeError, match="zero"):
        run_src("DECLARE X : INTEGER\nX <- DIV(5, 0)")


def test_mod_by_zero_is_error():
    with pytest.raises(PseudocodeError, match="zero"):
        run_src("DECLARE X : INTEGER\nX <- MOD(5, 0)")


def test_div_requires_integer_arguments():
    with pytest.raises(PseudocodeError):
        run_src("DECLARE X : INTEGER\nX <- DIV(5.5, 2)")


# ---- LENGTH / LCASE / UCASE / SUBSTRING (FR-5.5 - FR-5.8) -----------------

def test_length_srs_example():
    _, interp = run_src('DECLARE X : INTEGER\nX <- LENGTH("Good evening")')
    assert interp.symbols["X"].value == 12


def test_lcase_srs_example_on_char():
    _, interp = run_src("DECLARE X : CHAR\nX <- LCASE('H')")
    assert interp.symbols["X"].value == "h"


def test_ucase_srs_example():
    _, interp = run_src('DECLARE X : STRING\nX <- UCASE("A blue bird")')
    assert interp.symbols["X"].value == "A BLUE BIRD"


def test_substring_srs_example():
    _, interp = run_src('DECLARE X : STRING\nX <- SUBSTRING("Happy Days", 1, 5)')
    assert interp.symbols["X"].value == "Happy"


def test_substring_out_of_range_is_clear_error():
    with pytest.raises(PseudocodeError, match="go past the end"):
        run_src('DECLARE X : STRING\nX <- SUBSTRING("Hi", 1, 10)')


def test_substring_requires_positive_start_and_length():
    with pytest.raises(PseudocodeError, match="positive"):
        run_src('DECLARE X : STRING\nX <- SUBSTRING("Hi", 0, 1)')


def test_length_requires_string_argument():
    with pytest.raises(PseudocodeError):
        run_src("DECLARE X : INTEGER\nX <- LENGTH(5)")


# ---- unknown function still gives a clear "not supported" error ----------

def test_unknown_function_call_still_errors_clearly():
    with pytest.raises(PseudocodeError, match="later milestone"):
        run_src("DECLARE X : INTEGER\nX <- MYFUNC(1, 2)")


# ---- functions composing with the rest of the language --------------------

def test_builtin_inside_if_condition():
    output, _ = run_src(
        'IF LENGTH("abc") = 3\nTHEN\nOUTPUT "yes"\nELSE\nOUTPUT "no"\nENDIF'
    )
    assert output == ["yes"]


def test_builtin_nested_calls():
    _, interp = run_src('DECLARE X : STRING\nX <- UCASE(SUBSTRING("Happy Days", 7, 4))')
    assert interp.symbols["X"].value == "DAYS"
