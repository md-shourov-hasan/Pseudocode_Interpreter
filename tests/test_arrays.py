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


# ---- 1D array declaration and assignment (FR-8.1, FR-8.2) -----------------

def test_srs_1d_example():
    _, interp = run_src(
        'DECLARE StudentName : ARRAY[1:30] OF STRING\nStudentName[19] <- "John Doe"'
    )
    symbol = interp.symbols["StudentName"]
    assert symbol.is_array
    assert symbol.value[(19,)] == "John Doe"


def test_1d_array_default_values():
    _, interp = run_src("DECLARE Numbers : ARRAY[1:5] OF INTEGER")
    symbol = interp.symbols["Numbers"]
    for i in range(1, 6):
        assert symbol.value[(i,)] == 0


def test_1d_array_read_back_via_index_expression():
    output, _ = run_src(
        "DECLARE Numbers : ARRAY[1:5] OF INTEGER\n"
        "Numbers[3] <- 42\n"
        "OUTPUT Numbers[3]"
    )
    assert output == ["42"]


def test_1d_array_bounds_need_not_start_at_one():
    _, interp = run_src("DECLARE Ages : ARRAY[5:10] OF INTEGER\nAges[5] <- 1\nAges[10] <- 2")
    assert interp.symbols["Ages"].value[(5,)] == 1
    assert interp.symbols["Ages"].value[(10,)] == 2


def test_1d_array_bound_can_be_a_constant():
    _, interp = run_src(
        "CONSTANT MaxSize <- 5\nDECLARE Numbers : ARRAY[1:MaxSize] OF INTEGER\nNumbers[5] <- 9"
    )
    assert interp.symbols["Numbers"].value[(5,)] == 9


def test_1d_array_index_out_of_bounds_is_clear_error():
    with pytest.raises(PseudocodeError, match="out of bounds"):
        run_src("DECLARE Numbers : ARRAY[1:5] OF INTEGER\nNumbers[6] <- 1")


def test_1d_array_index_below_lower_bound_is_clear_error():
    with pytest.raises(PseudocodeError, match="out of bounds"):
        run_src("DECLARE Numbers : ARRAY[1:5] OF INTEGER\nOUTPUT Numbers[0]")


def test_1d_array_index_must_be_integer():
    with pytest.raises(PseudocodeError):
        run_src('DECLARE Numbers : ARRAY[1:5] OF INTEGER\nNumbers["x"] <- 1')


def test_array_element_type_checked_on_assignment():
    with pytest.raises(PseudocodeError):
        run_src('DECLARE Numbers : ARRAY[1:5] OF INTEGER\nNumbers[1] <- "hello"')


def test_array_element_integer_widens_into_real_array():
    _, interp = run_src("DECLARE Scores : ARRAY[1:3] OF REAL\nScores[1] <- 5")
    assert interp.symbols["Scores"].value[(1,)] == 5.0
    assert isinstance(interp.symbols["Scores"].value[(1,)], float)


def test_array_lower_bound_greater_than_upper_is_clear_error():
    with pytest.raises(PseudocodeError, match="lower bound"):
        run_src("DECLARE X : ARRAY[10:1] OF INTEGER")


# ---- 2D array declaration and assignment (FR-8.3, FR-8.4) -----------------

def test_srs_2d_example():
    _, interp = run_src(
        "DECLARE Grade : ARRAY[1:30, 1:5] OF CHAR\nGrade[16, 3] <- 'A'"
    )
    symbol = interp.symbols["Grade"]
    assert symbol.is_array
    assert symbol.value[(16, 3)] == "A"


def test_2d_array_default_values():
    _, interp = run_src("DECLARE Grid : ARRAY[1:2, 1:2] OF INTEGER")
    symbol = interp.symbols["Grid"]
    for r in (1, 2):
        for c in (1, 2):
            assert symbol.value[(r, c)] == 0


def test_2d_array_read_back():
    output, _ = run_src(
        "DECLARE Grid : ARRAY[1:3, 1:3] OF INTEGER\n"
        "Grid[2, 2] <- 7\n"
        "OUTPUT Grid[2, 2]"
    )
    assert output == ["7"]


def test_2d_array_wrong_number_of_indices_is_clear_error():
    with pytest.raises(PseudocodeError, match="2D array"):
        run_src("DECLARE Grid : ARRAY[1:3, 1:3] OF INTEGER\nGrid[1] <- 5")


def test_1d_array_wrong_number_of_indices_is_clear_error():
    with pytest.raises(PseudocodeError, match="1D array"):
        run_src("DECLARE Numbers : ARRAY[1:5] OF INTEGER\nOUTPUT Numbers[1, 2]")


def test_2d_array_out_of_bounds_row_is_clear_error():
    with pytest.raises(PseudocodeError, match="out of bounds"):
        run_src("DECLARE Grid : ARRAY[1:3, 1:3] OF INTEGER\nGrid[4, 1] <- 1")


def test_2d_array_out_of_bounds_column_is_clear_error():
    with pytest.raises(PseudocodeError, match="out of bounds"):
        run_src("DECLARE Grid : ARRAY[1:3, 1:3] OF INTEGER\nGrid[1, 4] <- 1")


def test_more_than_two_dimensions_is_rejected_by_parser():
    with pytest.raises(PseudocodeError, match="at most 2 dimensions"):
        parse_src("DECLARE Cube : ARRAY[1:2, 1:2, 1:2] OF INTEGER")


# ---- using a whole array where a scalar is expected -----------------------

def test_bare_array_in_output_is_a_clear_error():
    # OUTPUT of a whole array was once an extension (every element, one per
    # line). It has been removed: the SRS has no such statement, so it is an
    # error that points the student to output each element through an index.
    with pytest.raises(PseudocodeError, match="can't be output as a whole"):
        run_src("DECLARE Numbers : ARRAY[1:5] OF INTEGER\nOUTPUT Numbers")


def test_assigning_directly_to_bare_array_identifier_is_clear_error():
    with pytest.raises(PseudocodeError, match="is an array"):
        run_src("DECLARE Numbers : ARRAY[1:5] OF INTEGER\nNumbers <- 5")


def test_indexing_a_non_array_identifier_is_clear_error():
    with pytest.raises(PseudocodeError, match="not an array"):
        run_src("DECLARE X : INTEGER\nX <- 5\nOUTPUT X[1]")


def test_array_cannot_be_used_as_for_loop_variable():
    with pytest.raises(PseudocodeError, match="is an array"):
        run_src("DECLARE Numbers : ARRAY[1:5] OF INTEGER\nFOR Numbers <- 1 TO 5\nNEXT Numbers")


def test_array_cannot_be_input_target_directly():
    with pytest.raises(PseudocodeError, match="is an array"):
        run_src("DECLARE Numbers : ARRAY[1:5] OF INTEGER\nINPUT Numbers")


# ---- redeclaration and multi-identifier arrays -----------------------

def test_multiple_array_identifiers_share_shape_and_type():
    _, interp = run_src(
        "DECLARE A, B : ARRAY[1:3] OF INTEGER\nA[1] <- 1\nB[1] <- 2"
    )
    assert interp.symbols["A"].value[(1,)] == 1
    assert interp.symbols["B"].value[(1,)] == 2
    assert interp.symbols["A"].value[(2,)] == 0  # untouched, still default


def test_redeclaring_an_array_name_is_clear_error():
    with pytest.raises(PseudocodeError, match="already been declared"):
        run_src("DECLARE X : ARRAY[1:3] OF INTEGER\nDECLARE X : ARRAY[1:3] OF INTEGER")


def test_array_name_collides_with_scalar_declare():
    with pytest.raises(PseudocodeError, match="already been declared"):
        run_src("DECLARE X : INTEGER\nDECLARE X : ARRAY[1:3] OF INTEGER")


# ---- arrays composing with loops (a realistic small program) --------------

def test_array_filled_and_summed_with_for_loop():
    output, _ = run_src(
        "DECLARE Numbers : ARRAY[1:5] OF INTEGER\n"
        "DECLARE I : INTEGER\n"
        "DECLARE Total : INTEGER\n"
        "Total <- 0\n"
        "FOR I <- 1 TO 5\n"
        " Numbers[I] <- I * 2\n"
        "NEXT I\n"
        "FOR I <- 1 TO 5\n"
        " Total <- Total + Numbers[I]\n"
        "NEXT I\n"
        "OUTPUT Total"
    )
    assert output == ["30"]  # 2+4+6+8+10


def test_2d_array_filled_with_nested_for_loops():
    output, interp = run_src(
        "DECLARE Grid : ARRAY[1:2, 1:2] OF INTEGER\n"
        "DECLARE R : INTEGER\n"
        "DECLARE C : INTEGER\n"
        "FOR R <- 1 TO 2\n"
        " FOR C <- 1 TO 2\n"
        "  Grid[R, C] <- R * 10 + C\n"
        " NEXT C\n"
        "NEXT R\n"
        "OUTPUT Grid[1, 1], Grid[1, 2], Grid[2, 1], Grid[2, 2]"
    )
    assert output == ["11122122"]