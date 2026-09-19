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


# ---- '<--' typo detection -------------------------------------------

def test_double_dash_assignment_is_a_clear_error():
    with pytest.raises(PseudocodeError, match="typo"):
        tokenize("X <-- 5")


def test_double_dash_assignment_error_reports_correct_line():
    with pytest.raises(PseudocodeError) as exc_info:
        tokenize("DECLARE X : INTEGER\nX <-- 5")
    assert exc_info.value.line == 2


def test_triple_dash_is_still_caught():
    with pytest.raises(PseudocodeError, match="typo"):
        tokenize("X <--- 5")


def test_double_dash_into_array_element_is_caught_too():
    with pytest.raises(PseudocodeError, match="typo"):
        tokenize("nums[1] <-- 6")


def test_negative_assignment_with_a_space_still_works():
    # The fix must not break legitimate "assign a negative literal".
    output, interp = run_src("DECLARE X : INTEGER\nX <- -5\nOUTPUT X")
    assert interp.symbols["X"].value == -5
    assert output == ["-5"]


def test_subtraction_of_two_negatives_elsewhere_is_unaffected():
    # "A - -B" has nothing to do with assignment and must keep working.
    _, interp = run_src("DECLARE X : INTEGER\nX <- 5 - -3\nOUTPUT X")
    assert interp.symbols["X"].value == 8


def test_the_reported_bubble_sort_typo_is_now_caught():
    src = (
        "DECLARE arrayLength : INTEGER\n"
        "arrayLength <-- 5\n"
    )
    with pytest.raises(PseudocodeError, match="typo"):
        run_src(src)