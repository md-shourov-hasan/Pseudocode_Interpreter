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


# ---- multi-identifier DECLARE ------------------------------------------

def test_declare_multiple_identifiers_creates_all_with_defaults():
    _, interp = run_src("DECLARE a, b, c : INTEGER")
    assert interp.symbols["a"].value == 0
    assert interp.symbols["b"].value == 0
    assert interp.symbols["c"].value == 0
    for name in ("a", "b", "c"):
        assert interp.symbols[name].data_type == "INTEGER"


def test_declare_multiple_identifiers_are_independent():
    _, interp = run_src("DECLARE a, b, c : INTEGER\na <- 1\nb <- 2\nc <- 3")
    assert interp.symbols["a"].value == 1
    assert interp.symbols["b"].value == 2
    assert interp.symbols["c"].value == 3


def test_declare_multiple_identifiers_rejects_duplicate_in_same_statement():
    with pytest.raises(PseudocodeError, match="already been declared"):
        run_src("DECLARE a, b, a : INTEGER")


def test_declare_multiple_identifiers_rejects_redeclare_across_statements():
    with pytest.raises(PseudocodeError, match="already been declared"):
        run_src("DECLARE a : INTEGER\nDECLARE b, a : REAL")


# ---- INTEGER <- REAL narrowing (division truncates instead of erroring) ---

def test_integer_variable_truncates_division_result_no_error():
    output, interp = run_src("DECLARE sum : INTEGER\nsum <- (10 + 20) / 3\nOUTPUT sum")
    assert interp.symbols["sum"].value == 10
    assert output == ["10"]


def test_integer_variable_truncates_non_exact_division_toward_zero():
    _, interp = run_src("DECLARE X : INTEGER\nX <- 22 / 7")
    assert interp.symbols["X"].value == 3  # 3.142857... truncates to 3


def test_integer_variable_truncates_negative_division_toward_zero():
    _, interp = run_src("DECLARE X : INTEGER\nX <- -22 / 7")
    assert interp.symbols["X"].value == -3  # truncation, not floor (-4)


def test_real_variable_still_keeps_full_value():
    _, interp = run_src("DECLARE X : REAL\nX <- 22 / 7")
    assert interp.symbols["X"].value == pytest.approx(22 / 7)


def test_non_numeric_type_mismatch_still_errors():
    # narrowing only applies to REAL -> INTEGER; other mismatches still error
    with pytest.raises(PseudocodeError):
        run_src('DECLARE X : INTEGER\nX <- "hello"')


# ---- REAL output formatting (up to 5 decimal places) -----------------

def test_real_output_trims_trailing_zeros():
    output, _ = run_src("DECLARE X : REAL\nX <- 10 / 4\nOUTPUT X")  # 2.5
    assert output == ["2.5"]


def test_real_output_rounds_to_five_decimal_places():
    output, _ = run_src("DECLARE X : REAL\nX <- 22 / 7\nOUTPUT X")
    assert output == ["3.14286"]  # 22/7 = 3.142857142857... rounded to 5dp


def test_real_output_whole_number_prints_without_decimal():
    output, _ = run_src("DECLARE X : REAL\nX <- 500\nOUTPUT X")
    assert output == ["500"]


# ---- AND / OR / NOT (extension) ----------------------------------------

def test_not_on_boolean_identifier():
    output, _ = run_src(
        "DECLARE IsSorted : BOOLEAN\nIsSorted <- FALSE\nIF NOT IsSorted\nTHEN\nOUTPUT \"needs sorting\"\nENDIF"
    )
    assert output == ["needs sorting"]


def test_not_requires_boolean_operand():
    with pytest.raises(PseudocodeError, match="NOT"):
        run_src('DECLARE X : INTEGER\nX <- 5\nIF NOT X\nTHEN\nOUTPUT "no"\nENDIF')


def test_and_both_true():
    output, _ = run_src(
        "DECLARE A : BOOLEAN\nDECLARE B : BOOLEAN\nA <- TRUE\nB <- TRUE\n"
        'IF A AND B\nTHEN\nOUTPUT "both"\nENDIF'
    )
    assert output == ["both"]


def test_and_short_circuits_are_not_required_but_result_is_correct_when_false():
    output, _ = run_src(
        "DECLARE A : BOOLEAN\nA <- FALSE\n"
        'IF A AND (1 = 1)\nTHEN\nOUTPUT "yes"\nELSE\nOUTPUT "no"\nENDIF'
    )
    assert output == ["no"]


def test_or_true_when_either_true():
    output, _ = run_src(
        'IF (1 = 2) OR (2 = 2)\nTHEN\nOUTPUT "yes"\nELSE\nOUTPUT "no"\nENDIF'
    )
    assert output == ["yes"]


def test_and_or_not_needs_boolean_operands():
    with pytest.raises(PseudocodeError, match="AND"):
        run_src("DECLARE X : INTEGER\nX <- 5\nIF X AND TRUE\nTHEN\nOUTPUT \"y\"\nENDIF")


def test_complex_condition_with_parentheses_and_precedence():
    # IsSorted = TRUE AND (value = 10 OR number <> 3)
    src = (
        "DECLARE IsSorted : BOOLEAN\n"
        "DECLARE value : INTEGER\n"
        "DECLARE number : INTEGER\n"
        "IsSorted <- TRUE\n"
        "value <- 99\n"
        "number <- 3\n"
        "IF IsSorted = TRUE AND (value = 10 OR number <> 3)\n"
        "THEN\n"
        ' OUTPUT "match"\n'
        "ELSE\n"
        ' OUTPUT "no match"\n'
        "ENDIF"
    )
    output, _ = run_src(src)
    # IsSorted=TRUE -> True; value=10 -> False; number<>3 -> False; False OR False -> False
    # True AND False -> False
    assert output == ["no match"]


def test_complex_condition_matches_when_or_branch_true():
    src = (
        "DECLARE IsSorted : BOOLEAN\n"
        "DECLARE value : INTEGER\n"
        "DECLARE number : INTEGER\n"
        "IsSorted <- TRUE\n"
        "value <- 10\n"
        "number <- 3\n"
        "IF IsSorted = TRUE AND (value = 10 OR number <> 3)\n"
        "THEN\n"
        ' OUTPUT "match"\n'
        "ELSE\n"
        ' OUTPUT "no match"\n'
        "ENDIF"
    )
    output, _ = run_src(src)
    assert output == ["match"]


def test_double_not_cancels_out():
    output, _ = run_src(
        "DECLARE Flag : BOOLEAN\nFlag <- TRUE\n"
        'IF NOT NOT Flag\nTHEN\nOUTPUT "still true"\nENDIF'
    )
    assert output == ["still true"]


def test_and_has_higher_precedence_than_or_without_parens():
    # TRUE OR TRUE AND FALSE => TRUE OR (TRUE AND FALSE) => TRUE
    output, _ = run_src(
        'IF TRUE OR TRUE AND FALSE\nTHEN\nOUTPUT "yes"\nELSE\nOUTPUT "no"\nENDIF'
    )
    assert output == ["yes"]


# ---- INPUT into a CONSTANT ----------------------------------------------

def test_input_cannot_overwrite_a_constant():
    with pytest.raises(PseudocodeError, match="CONSTANT and cannot be reassigned"):
        run_src("CONSTANT Pi <- 3\nINPUT Pi", inputs=["99"])


# ---- lexer/parser never leak a raw Python exception ---------------------

def test_non_ascii_digit_is_an_unexpected_character():
    with pytest.raises(PseudocodeError, match="Unexpected character"):
        run_src("DECLARE X : INTEGER\nX <- ²")


def test_ascii_digits_followed_by_non_ascii_digit_is_reported():
    with pytest.raises(PseudocodeError):
        run_src("DECLARE X : INTEGER\nX <- 1²")


def test_deeply_nested_brackets_report_a_pseudocode_error():
    with pytest.raises(PseudocodeError, match="nested too deeply"):
        run_src("OUTPUT " + "(" * 3000 + "1" + ")" * 3000)


# ---- "=" / "<>" between unrelated types ---------------------------------

@pytest.mark.parametrize("expr", ['TRUE = 1', '"a" = 1', '"a" <> 1', "FALSE <> 0", '"TRUE" = TRUE'])
def test_equality_between_unrelated_types_is_an_error(expr):
    with pytest.raises(PseudocodeError, match="Can't compare"):
        run_src(f"OUTPUT {expr}")


def test_equality_still_works_within_a_type_group():
    output, _ = run_src('OUTPUT 1 = 1.0, "a" = \'a\', TRUE = TRUE, 2 <> 3')
    assert output == ["TRUETRUETRUETRUE"]


# ---- INTEGER too large to print -----------------------------------------

def test_output_of_huge_integer_gives_a_clear_message():
    with pytest.raises(PseudocodeError, match="too large to display"):
        run_src("OUTPUT 10 ^ 5000")
