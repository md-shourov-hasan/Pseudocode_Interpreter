import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from engine.lexer import tokenize
from engine.parser import parse
from engine.interpreter import Interpreter
from engine.errors import PseudocodeError


def run_src(src: str, inputs=None):
    """Run pseudocode source and return (output_lines, interpreter)."""
    program = parse(tokenize(src))
    queue = list(inputs or [])
    interp = Interpreter(input_fn=lambda: queue.pop(0))
    output = interp.run(program)
    return output, interp


# ---- DECLARE / types (FR-2.x, FR-3.1) --------------------------------------

def test_declare_gives_default_value():
    _, interp = run_src("DECLARE X : INTEGER")
    assert interp.symbols["X"].value == 0
    assert interp.symbols["X"].data_type == "INTEGER"


def test_redeclaring_identifier_is_error():
    with pytest.raises(PseudocodeError):
        run_src("DECLARE X : INTEGER\nDECLARE X : REAL")


# ---- assignment + type checking (FR-3.3, FR-3.4, FR-11.2, FR-11.3) --------

def test_assignment_stores_value():
    _, interp = run_src("DECLARE X : INTEGER\nX <- 5")
    assert interp.symbols["X"].value == 5


def test_assignment_to_undeclared_identifier_is_error():
    with pytest.raises(PseudocodeError, match="never declared"):
        run_src("X <- 5")


def test_reading_undeclared_identifier_is_error():
    with pytest.raises(PseudocodeError, match="never declared"):
        run_src("DECLARE X : INTEGER\nX <- Y + 1")


def test_incompatible_type_assignment_is_error():
    with pytest.raises(PseudocodeError):
        run_src('DECLARE X : INTEGER\nX <- "hello"')


def test_integer_widens_into_real():
    _, interp = run_src("DECLARE X : REAL\nX <- 5")
    assert interp.symbols["X"].value == 5.0
    assert isinstance(interp.symbols["X"].value, float)


def test_boolean_is_distinct_from_integer():
    with pytest.raises(PseudocodeError):
        run_src("DECLARE X : INTEGER\nX <- TRUE")
    with pytest.raises(PseudocodeError):
        run_src("DECLARE Flag : BOOLEAN\nFlag <- 1")


def test_char_must_be_single_character():
    _, interp = run_src("DECLARE C : CHAR\nC <- 'x'")
    assert interp.symbols["C"].value == "x"


# ---- CONSTANT (FR-3.2) ------------------------------------------------

def test_constant_stores_value_and_infers_type():
    _, interp = run_src("CONSTANT UpperBound <- 15")
    assert interp.symbols["UpperBound"].value == 15
    assert interp.symbols["UpperBound"].data_type == "INTEGER"


def test_constant_cannot_be_reassigned():
    with pytest.raises(PseudocodeError, match="CONSTANT"):
        run_src("CONSTANT UpperBound <- 15\nUpperBound <- 20")


# ---- expressions / operators (FR-5.1, FR-5.4) ------------------------------

def test_arithmetic_precedence_end_to_end():
    _, interp = run_src("DECLARE X : INTEGER\nX <- 2 + 3 * 4")
    assert interp.symbols["X"].value == 14


def test_actual_score_example_from_srs():
    _, interp = run_src(
        "DECLARE Score : INTEGER\nDECLARE ActualScore : REAL\nScore <- 5\nActualScore <- Score * 100"
    )
    assert interp.symbols["ActualScore"].value == 500.0


def test_division_by_zero_is_error():
    with pytest.raises(PseudocodeError, match="[Dd]ivision"):
        run_src("DECLARE X : REAL\nX <- 5 / 0")


def test_relational_expression_produces_boolean():
    _, interp = run_src("DECLARE Same : BOOLEAN\nSame <- (5 = 5)")
    assert interp.symbols["Same"].value is True


def test_power_operator():
    _, interp = run_src("DECLARE X : INTEGER\nX <- 2 ^ 10")
    assert interp.symbols["X"].value == 1024


def test_string_concatenation_with_plus():
    _, interp = run_src('DECLARE S : STRING\nS <- "Happy" + " " + "Days"')
    assert interp.symbols["S"].value == "Happy Days"


# ---- INPUT / OUTPUT (FR-4.1, FR-4.2) --------------------------------------

def test_output_single_value():
    output, _ = run_src('OUTPUT "Hello"')
    assert output == ["Hello"]


def test_output_multiple_comma_separated_values_same_statement():
    output, _ = run_src(
        "DECLARE AvgScore : INTEGER\nDECLARE TotalScore : INTEGER\n"
        "AvgScore <- 10\nTotalScore <- 20\n"
        "OUTPUT AvgScore, TotalScore"
    )
    assert output == ["1020"]  # concatenated per FR-4.2 (no separator specified)


def test_output_boolean_formats_as_true_false():
    output, _ = run_src("DECLARE Flag : BOOLEAN\nFlag <- TRUE\nOUTPUT Flag")
    assert output == ["TRUE"]


def test_input_reads_and_assigns():
    output, interp = run_src(
        "DECLARE Answer : INTEGER\nINPUT Answer\nOUTPUT Answer", inputs=["42"]
    )
    assert interp.symbols["Answer"].value == 42
    assert output == ["42"]


def test_input_type_mismatch_is_error():
    with pytest.raises(PseudocodeError):
        run_src("DECLARE Answer : INTEGER\nINPUT Answer", inputs=["not a number"])


# ---- not-yet-implemented features fail clearly, not silently -------------

def test_calling_an_unknown_function_is_a_clear_not_yet_error():
    # ROUND itself is a real built-in as of Milestone 4 (see
    # test_library_functions.py); user-defined FUNCTIONs are real as of
    # Milestone 8 (see test_procedures_functions.py). This checks the
    # fallback path for a name that is neither.
    with pytest.raises(PseudocodeError, match="isn't a recognized built-in or user-defined function"):
        run_src("DECLARE X : REAL\nX <- MYSTERYFUNC(3.14159, 2)")


def test_indexing_an_undeclared_name_is_a_clear_error():
    # Real array indexing is exercised in test_arrays.py (Milestone 7);
    # this just checks the "never declared" path still fires for indexing.
    with pytest.raises(PseudocodeError, match="never declared"):
        run_src("DECLARE X : INTEGER\nX <- Numbers[1]")