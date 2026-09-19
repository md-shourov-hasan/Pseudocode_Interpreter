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


# ---- INPUT into an array element ---------------------------------------

def test_input_parses_with_index_target():
    prog = parse_src("INPUT MyArray[3]")
    stmt = prog.statements[0]
    assert isinstance(stmt, ast.Input)
    assert isinstance(stmt.target, ast.Index)
    assert stmt.target.name == "MyArray"


def test_input_into_1d_array_element():
    _, interp = run_src(
        "DECLARE MyArray : ARRAY[1:5] OF INTEGER\nINPUT MyArray[3]",
        inputs=["42"],
    )
    assert interp.symbols["MyArray"].value[(3,)] == 42


def test_input_into_2d_array_element():
    _, interp = run_src(
        "DECLARE Grid : ARRAY[1:3, 1:3] OF INTEGER\nINPUT Grid[2, 2]",
        inputs=["7"],
    )
    assert interp.symbols["Grid"].value[(2, 2)] == 7


def test_input_into_array_element_with_computed_index():
    _, interp = run_src(
        "DECLARE MyArray : ARRAY[1:5] OF INTEGER\nDECLARE I : INTEGER\nI <- 2\nINPUT MyArray[I + 1]",
        inputs=["99"],
    )
    assert interp.symbols["MyArray"].value[(3,)] == 99


def test_input_into_array_element_still_type_checks():
    with pytest.raises(PseudocodeError):
        run_src(
            "DECLARE MyArray : ARRAY[1:5] OF INTEGER\nINPUT MyArray[1]",
            inputs=["not a number"],
        )


def test_input_into_array_element_still_bounds_checks():
    with pytest.raises(PseudocodeError, match="out of bounds"):
        run_src(
            "DECLARE MyArray : ARRAY[1:5] OF INTEGER\nINPUT MyArray[10]",
            inputs=["1"],
        )


def test_input_still_works_for_plain_scalar_variables():
    # Regression check: the ordinary (non-array) INPUT path must be unaffected.
    _, interp = run_src("DECLARE X : INTEGER\nINPUT X", inputs=["5"])
    assert interp.symbols["X"].value == 5


def test_input_into_undeclared_array_is_clear_error():
    with pytest.raises(PseudocodeError, match="never declared"):
        run_src("INPUT MyArray[1]", inputs=["1"])


# ---- OUTPUT of a whole array (bare identifier) -----------------------

def test_output_1d_array_prints_one_element_per_line():
    output, _ = run_src(
        "DECLARE MyArray : ARRAY[1:5] OF INTEGER\n"
        "MyArray[1] <- 10\nMyArray[2] <- 20\nMyArray[3] <- 30\nMyArray[4] <- 40\nMyArray[5] <- 50\n"
        "OUTPUT MyArray"
    )
    assert output == ["10", "20", "30", "40", "50"]


def test_output_1d_array_with_non_default_bounds():
    output, _ = run_src(
        "DECLARE Ages : ARRAY[5:7] OF INTEGER\nAges[5] <- 1\nAges[6] <- 2\nAges[7] <- 3\nOUTPUT Ages"
    )
    assert output == ["1", "2", "3"]


def test_output_2d_array_prints_row_major_one_per_line():
    output, _ = run_src(
        "DECLARE Grid : ARRAY[1:2, 1:2] OF INTEGER\n"
        "Grid[1, 1] <- 1\nGrid[1, 2] <- 2\nGrid[2, 1] <- 3\nGrid[2, 2] <- 4\n"
        "OUTPUT Grid"
    )
    assert output == ["1", "2", "3", "4"]


def test_output_array_of_strings():
    output, _ = run_src(
        'DECLARE Names : ARRAY[1:2] OF STRING\nNames[1] <- "Alice"\nNames[2] <- "Bob"\nOUTPUT Names'
    )
    assert output == ["Alice", "Bob"]


def test_output_array_uses_default_values_if_unset():
    output, _ = run_src("DECLARE Numbers : ARRAY[1:3] OF INTEGER\nOUTPUT Numbers")
    assert output == ["0", "0", "0"]


def test_output_indexed_element_is_unaffected_by_array_output_change():
    # OUTPUT MyArray[i] must remain an ordinary single-line scalar read.
    output, _ = run_src(
        "DECLARE MyArray : ARRAY[1:3] OF INTEGER\nMyArray[2] <- 99\nOUTPUT MyArray[2]"
    )
    assert output == ["99"]


def test_output_scalar_values_unaffected_by_array_output_change():
    # Regression check: OUTPUT with several ordinary (non-array) values
    # must still be joined onto a single line, as before.
    output, _ = run_src(
        "DECLARE A : INTEGER\nDECLARE B : INTEGER\nA <- 1\nB <- 2\nOUTPUT A, B"
    )
    assert output == ["12"]


def test_output_mixing_text_and_a_whole_array():
    # A prefix, followed by the array's elements each on their own line.
    output, _ = run_src(
        "DECLARE Numbers : ARRAY[1:3] OF INTEGER\n"
        "Numbers[1] <- 1\nNumbers[2] <- 2\nNumbers[3] <- 3\n"
        'OUTPUT "Numbers:", Numbers'
    )
    assert output == ["Numbers:", "1", "2", "3"]