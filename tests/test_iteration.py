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


# ---- FOR loop (FR-6.1, FR-6.2, FR-6.3) -------------------------------------

def test_for_loop_srs_example_no_step():
    output, _ = run_src(
        "DECLARE Index : INTEGER\n"
        "FOR Index <- 1 TO 5\n"
        " OUTPUT Index\n"
        "NEXT Index"
    )
    assert output == ["1", "2", "3", "4", "5"]


def test_for_loop_srs_example_with_step():
    output, _ = run_src(
        "DECLARE Index : INTEGER\n"
        "FOR Index <- 1 TO 30 STEP 5\n"
        " OUTPUT Index\n"
        "NEXT Index"
    )
    assert output == ["1", "6", "11", "16", "21", "26"]


def test_for_loop_start_equals_finish_runs_once():
    output, _ = run_src(
        "DECLARE I : INTEGER\nFOR I <- 5 TO 5\n OUTPUT I\nNEXT I"
    )
    assert output == ["5"]


def test_for_loop_start_greater_than_finish_runs_zero_times():
    output, _ = run_src(
        "DECLARE I : INTEGER\nFOR I <- 5 TO 1\n OUTPUT I\nNEXT I"
    )
    assert output == []


def test_for_loop_negative_step_counts_down():
    output, _ = run_src(
        "DECLARE I : INTEGER\nFOR I <- 5 TO 1 STEP -1\n OUTPUT I\nNEXT I"
    )
    assert output == ["5", "4", "3", "2", "1"]


def test_for_loop_negative_step_with_start_less_than_finish_runs_zero_times():
    output, _ = run_src(
        "DECLARE I : INTEGER\nFOR I <- 1 TO 5 STEP -1\n OUTPUT I\nNEXT I"
    )
    assert output == []


def test_for_loop_step_zero_is_clear_error():
    with pytest.raises(PseudocodeError, match="STEP"):
        run_src("DECLARE I : INTEGER\nFOR I <- 1 TO 5 STEP 0\n OUTPUT I\nNEXT I")


def test_for_loop_non_integer_bound_is_clear_error():
    with pytest.raises(PseudocodeError):
        run_src('DECLARE I : INTEGER\nFOR I <- 1 TO "five"\n OUTPUT I\nNEXT I')


def test_for_loop_next_identifier_must_match():
    with pytest.raises(PseudocodeError, match="doesn't match"):
        run_src("DECLARE I : INTEGER\nDECLARE J : INTEGER\nFOR I <- 1 TO 3\n OUTPUT I\nNEXT J")


def test_for_loop_missing_next_is_clear_error():
    with pytest.raises(PseudocodeError, match="NEXT"):
        run_src("DECLARE I : INTEGER\nFOR I <- 1 TO 3\n OUTPUT I")


def test_for_loop_variable_must_be_declared():
    with pytest.raises(PseudocodeError, match="never declared"):
        run_src("FOR I <- 1 TO 3\n OUTPUT I\nNEXT I")


def test_for_loop_variable_cannot_be_constant():
    with pytest.raises(PseudocodeError, match="CONSTANT"):
        run_src("CONSTANT I <- 1\nFOR I <- 1 TO 3\nOUTPUT I\nNEXT I")


def test_for_loop_variable_retains_last_value_after_loop():
    _, interp = run_src("DECLARE I : INTEGER\nFOR I <- 1 TO 5\n OUTPUT I\nNEXT I")
    assert interp.symbols["I"].value == 5


def test_for_loop_variable_widens_into_real():
    _, interp = run_src("DECLARE I : REAL\nFOR I <- 1 TO 3\nNEXT I")
    assert interp.symbols["I"].value == 3.0
    assert isinstance(interp.symbols["I"].value, float)


def test_for_loop_body_can_use_other_statements():
    output, interp = run_src(
        "DECLARE I : INTEGER\nDECLARE Total : INTEGER\nTotal <- 0\n"
        "FOR I <- 1 TO 4\n Total <- Total + I\nNEXT I\nOUTPUT Total"
    )
    assert output == ["10"]


# ---- REPEAT loop (FR-6.4) -----------------------------------------------

def test_repeat_srs_example_password():
    output, interp = run_src(
        "DECLARE InpPassword : STRING\nDECLARE Password : STRING\nPassword <- \"secret\"\n"
        "REPEAT\n INPUT InpPassword\nUNTIL InpPassword = Password",
        inputs=["wrong", "secret"],
    )
    assert interp.symbols["InpPassword"].value == "secret"


def test_repeat_runs_body_at_least_once_even_if_condition_starts_true():
    output, interp = run_src(
        "DECLARE X : INTEGER\nX <- 0\nREPEAT\n X <- X + 1\nUNTIL TRUE"
    )
    assert interp.symbols["X"].value == 1


def test_repeat_loops_until_condition_becomes_true():
    _, interp = run_src(
        "DECLARE X : INTEGER\nX <- 0\nREPEAT\n X <- X + 1\nUNTIL X = 5"
    )
    assert interp.symbols["X"].value == 5


def test_repeat_missing_until_is_clear_error():
    with pytest.raises(PseudocodeError, match="UNTIL"):
        run_src("DECLARE X : INTEGER\nREPEAT\n X <- 1")


def test_repeat_condition_must_be_boolean():
    with pytest.raises(PseudocodeError, match="BOOLEAN"):
        run_src("DECLARE X : INTEGER\nREPEAT\n X <- 1\nUNTIL 5")


# ---- WHILE loop (FR-6.5) -------------------------------------------------

def test_while_srs_example():
    output, _ = run_src(
        "DECLARE Number : INTEGER\nNumber <- 0\n"
        "WHILE Number < 10 DO\n OUTPUT Number\n Number <- Number + 1\nENDWHILE"
    )
    assert output == ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"]


def test_while_condition_false_from_start_runs_zero_times():
    output, _ = run_src(
        "DECLARE X : INTEGER\nX <- 10\nWHILE X < 10 DO\n OUTPUT X\nENDWHILE"
    )
    assert output == []


def test_while_missing_endwhile_is_clear_error():
    with pytest.raises(PseudocodeError, match="ENDWHILE"):
        run_src("DECLARE X : INTEGER\nX <- 0\nWHILE X < 10 DO\n X <- X + 1")


def test_while_condition_must_be_boolean():
    with pytest.raises(PseudocodeError, match="BOOLEAN"):
        run_src("DECLARE X : INTEGER\nX <- 1\nWHILE X DO\n OUTPUT X\nENDWHILE")


# ---- nesting and composition -------------------------------------------

def test_nested_for_loops():
    output, _ = run_src(
        "DECLARE I : INTEGER\nDECLARE J : INTEGER\n"
        "FOR I <- 1 TO 2\n"
        " FOR J <- 1 TO 2\n"
        "  OUTPUT I, J\n"
        " NEXT J\n"
        "NEXT I"
    )
    assert output == ["11", "12", "21", "22"]


def test_while_loop_containing_if():
    output, _ = run_src(
        "DECLARE X : INTEGER\nX <- 0\n"
        "WHILE X < 4 DO\n"
        " IF X = 2\n"
        " THEN\n"
        "  OUTPUT \"two\"\n"
        " ENDIF\n"
        " X <- X + 1\n"
        "ENDWHILE"
    )
    assert output == ["two"]


def test_for_loop_containing_case():
    output, _ = run_src(
        "DECLARE I : INTEGER\n"
        "FOR I <- 1 TO 3\n"
        " CASE OF I\n"
        "  1 : OUTPUT \"one\"\n"
        "  2 : OUTPUT \"two\"\n"
        "  OTHERWISE OUTPUT \"other\"\n"
        " ENDCASE\n"
        "NEXT I"
    )
    assert output == ["one", "two", "other"]