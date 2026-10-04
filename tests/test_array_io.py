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


# ---- OUTPUT of a whole array is refused ---------------------------------
# An array's elements are output one at a time through an index. A bare array
# name is not a value, so OUTPUT MyArray is an error that says how to do it.

WHOLE_ARRAY_OUTPUT_CASES = [
    "DECLARE MyArray : ARRAY[1:5] OF INTEGER\nMyArray[1] <- 10\nOUTPUT MyArray",
    "DECLARE MyArray : ARRAY[5:7] OF INTEGER\nOUTPUT MyArray",
    "DECLARE MyArray : ARRAY[1:2, 1:2] OF INTEGER\nOUTPUT MyArray",
    'DECLARE MyArray : ARRAY[1:2] OF STRING\nMyArray[1] <- "Alice"\nOUTPUT MyArray',
    "DECLARE MyArray : ARRAY[1:3] OF INTEGER\nOUTPUT MyArray",
]


@pytest.mark.parametrize("src", WHOLE_ARRAY_OUTPUT_CASES)
def test_output_of_a_whole_array_is_an_error_that_explains_what_to_do(src):
    with pytest.raises(PseudocodeError) as info:
        run_src(src)
    assert info.value.line == src.count("\n") + 1  # the OUTPUT line
    assert info.value.message == (
        "'MyArray' is an array, so it can't be output as a whole. "
        "Output each element separately using its index, e.g. OUTPUT MyArray[1]."
    )


@pytest.mark.parametrize(
    "output_statement",
    ['OUTPUT "Numbers:", Numbers', 'OUTPUT Numbers, " are the numbers"', 'OUTPUT 1, Numbers, 2'],
)
def test_a_whole_array_among_other_values_prints_nothing_at_all(output_statement):
    printed = []
    interp = Interpreter(output_fn=printed.append)
    program = parse_src("DECLARE Numbers : ARRAY[1:3] OF INTEGER\n" + output_statement)
    with pytest.raises(PseudocodeError, match="can't be output as a whole"):
        interp.run(program)
    assert printed == []


def test_outputting_each_element_by_index_is_the_way_to_show_a_1d_array():
    output, _ = run_src(
        "DECLARE Numbers : ARRAY[1:3] OF INTEGER\nDECLARE i : INTEGER\n"
        "Numbers[1] <- 10\nNumbers[2] <- 20\nNumbers[3] <- 30\n"
        "FOR i <- 1 TO 3\n  OUTPUT Numbers[i]\nNEXT i"
    )
    assert output == ["10", "20", "30"]


def test_outputting_each_element_by_index_is_the_way_to_show_a_2d_array():
    output, _ = run_src(
        "DECLARE Grid : ARRAY[1:2, 1:2] OF INTEGER\nDECLARE r, c : INTEGER\n"
        "Grid[1, 1] <- 1\nGrid[1, 2] <- 2\nGrid[2, 1] <- 3\nGrid[2, 2] <- 4\n"
        "FOR r <- 1 TO 2\n  FOR c <- 1 TO 2\n    OUTPUT Grid[r, c]\n  NEXT c\nNEXT r"
    )
    assert output == ["1", "2", "3", "4"]


def test_output_indexed_element_is_an_ordinary_read():
    # OUTPUT MyArray[i] is a normal single-line scalar read.
    output, _ = run_src(
        "DECLARE MyArray : ARRAY[1:3] OF INTEGER\nMyArray[2] <- 99\nOUTPUT MyArray[2]"
    )
    assert output == ["99"]


def test_output_scalar_values_are_joined_onto_one_line():
    # OUTPUT with several ordinary (non-array) values is joined onto a single
    # line, with no separator.
    output, _ = run_src(
        "DECLARE A : INTEGER\nDECLARE B : INTEGER\nA <- 1\nB <- 2\nOUTPUT A, B"
    )
    assert output == ["12"]
