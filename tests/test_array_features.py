"""
Tests for the array work:

  * Whole-array fill from a list:  MyArray <- ["Cat", "Dog", "Rayan"]
    (a list of rows, [[1, 2], [3, 4]], for a 2D array).
  * Array bug fixes: an unbounded DECLARE can no longer exhaust memory; error
    messages name the element ('a[2]'), read "an INTEGER", and explain how to
    fill or index an array; CASE OF an array element explains itself.
"""

import os
import random
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from engine.lexer import tokenize
from engine.parser import parse
from engine.interpreter import Interpreter, MAX_ARRAY_ELEMENTS
from engine.errors import PseudocodeError


def run_src(src: str, inputs=None):
    program = parse(tokenize(src))
    queue = list(inputs or [])
    interp = Interpreter(input_fn=lambda: queue.pop(0) if queue else "")
    output = interp.run(program)
    return output, interp


def error_of(src: str, inputs=None) -> PseudocodeError:
    with pytest.raises(PseudocodeError) as info:
        run_src(src, inputs)
    return info.value


def values_of(interp, name):
    """An array's contents as {index tuple: value}."""
    return dict(interp.symbols[name].value)


# ---- LENGTH measures strings only ----------------------------------------
# (LENGTH(array) was tried and deliberately removed: the language's LENGTH
# function is defined for strings, so an array is not a valid argument.)

def test_length_of_a_string_and_string_variable_still_work():
    output, _ = run_src('DECLARE s : STRING\ns <- "Shourov"\nOUTPUT LENGTH(s)\nOUTPUT LENGTH("Cat")')
    assert output == ["7", "3"]


def test_length_of_a_string_element_is_the_strings_length():
    src = 'DECLARE n : ARRAY[1:2] OF STRING\nn <- ["Cat", "Rayan"]\nOUTPUT LENGTH(n[2])'
    assert run_src(src)[0] == ["5"]


def test_length_of_undeclared_name_is_still_an_undeclared_error():
    assert "never declared" in error_of("OUTPUT LENGTH(nope)").message


@pytest.mark.parametrize(
    "declaration",
    ["ARRAY[1:5] OF INTEGER", "ARRAY[1:2] OF STRING", "ARRAY[1:2, 1:3] OF REAL"],
)
def test_length_does_not_accept_a_whole_array(declaration):
    err = error_of(f"DECLARE a : {declaration}\nOUTPUT LENGTH(a)")
    assert "'a' is an array" in err.message


# ---- filling an array from a list ---------------------------------------

def test_fill_a_string_array_in_one_line():
    src = (
        "DECLARE MyArray : ARRAY[1:5] OF STRING\n"
        'MyArray <- ["Cat", "Dog", "Shourov", "Liyana", "Rayan"]\n'
        "OUTPUT MyArray"
    )
    output, interp = run_src(src)
    assert output == ["Cat", "Dog", "Shourov", "Liyana", "Rayan"]
    assert values_of(interp, "MyArray") == {
        (1,): "Cat", (2,): "Dog", (3,): "Shourov", (4,): "Liyana", (5,): "Rayan",
    }


def test_filled_elements_can_be_read_individually():
    src = 'DECLARE a : ARRAY[1:3] OF STRING\na <- ["x", "y", "z"]\nOUTPUT a[1], a[2], a[3]'
    assert run_src(src)[0] == ["xyz"]


def test_list_values_may_be_expressions():
    src = (
        "DECLARE a : ARRAY[1:3] OF INTEGER\nDECLARE x : INTEGER\n"
        'x <- 4\na <- [x * 2, x + 1, LENGTH("abc")]\nOUTPUT a'
    )
    assert run_src(src)[0] == ["8", "5", "3"]


def test_fill_follows_the_arrays_own_bounds():
    output, _ = run_src("DECLARE a : ARRAY[-1:1] OF INTEGER\na <- [5, 6, 7]\nOUTPUT a[-1], a[0], a[1]")
    assert output == ["567"]


def test_real_array_widens_integer_values():
    _, interp = run_src("DECLARE r : ARRAY[1:2] OF REAL\nr <- [1, 2.5]")
    values = values_of(interp, "r")
    assert values == {(1,): 1.0, (2,): 2.5}
    assert isinstance(values[(1,)], float)


def test_integer_array_narrows_a_real_value_like_a_single_element_assignment_does():
    _, interp = run_src("DECLARE a : ARRAY[1:2] OF INTEGER\na <- [7 / 2, 2.9]")
    assert values_of(interp, "a") == {(1,): 3, (2,): 2}


def test_boolean_and_char_arrays():
    output, _ = run_src(
        "DECLARE b : ARRAY[1:2] OF BOOLEAN\nDECLARE c : ARRAY[1:2] OF CHAR\n"
        "b <- [TRUE, 1 > 2]\nc <- ['a', 'b']\nOUTPUT b\nOUTPUT c"
    )
    assert output == ["TRUE", "FALSE", "a", "b"]


def test_list_may_span_lines_and_contain_comments():
    src = 'DECLARE n : ARRAY[1:3] OF STRING\nn <- [\n  "a", // first\n  "b",\n  "c"\n]\nOUTPUT n'
    assert run_src(src)[0] == ["a", "b", "c"]


def test_refilling_replaces_every_element():
    _, interp = run_src("DECLARE a : ARRAY[1:2] OF INTEGER\na <- [1, 2]\na <- [3, 4]")
    assert values_of(interp, "a") == {(1,): 3, (2,): 4}


def test_values_are_all_worked_out_before_any_is_stored():
    # If elements were stored one by one, this would not reverse the array.
    src = "DECLARE a : ARRAY[1:3] OF INTEGER\na <- [1, 2, 3]\na <- [a[3], a[2], a[1]]\nOUTPUT a"
    assert run_src(src)[0] == ["3", "2", "1"]


def test_fill_works_inside_control_structures():
    src = (
        "DECLARE a : ARRAY[1:2] OF INTEGER\nDECLARE i : INTEGER\n"
        "FOR i <- 1 TO 2\n  IF i = 2 THEN\n    a <- [i, i]\n  ENDIF\nNEXT i\nOUTPUT a"
    )
    assert run_src(src)[0] == ["2", "2"]


def test_fill_a_2d_array_with_a_list_of_rows():
    src = "DECLARE g : ARRAY[1:2, 1:3] OF INTEGER\ng <- [[1, 2, 3], [4, 5, 6]]\nOUTPUT g[2, 1], g[1, 3]\nOUTPUT g"
    output, _ = run_src(src)
    assert output == ["43", "1", "2", "3", "4", "5", "6"]


def test_2d_fill_respects_non_default_bounds():
    _, interp = run_src("DECLARE g : ARRAY[0:1, 5:6] OF INTEGER\ng <- [[1, 2], [3, 4]]")
    assert values_of(interp, "g") == {(0, 5): 1, (0, 6): 2, (1, 5): 3, (1, 6): 4}


# ---- a bad list is refused, with a clear message, and changes nothing ------

def test_too_few_values_is_reported_with_both_counts():
    err = error_of('DECLARE a : ARRAY[1:5] OF STRING\na <- ["x", "y"]')
    assert err.line == 2
    assert "'a' holds 5 elements (1 to 5), but the list has 2." in err.message


def test_too_many_values_is_reported():
    err = error_of('DECLARE a : ARRAY[1:2] OF STRING\na <- ["x", "y", "z"]')
    assert "holds 2 elements" in err.message and "the list has 3" in err.message


def test_empty_list_does_not_fill_an_array():
    assert "the list has 0" in error_of("DECLARE a : ARRAY[1:2] OF INTEGER\na <- []").message


def test_single_element_array_message_is_grammatical():
    assert "holds 1 element (1 to 1)" in error_of("DECLARE a : ARRAY[1:1] OF INTEGER\na <- [1, 2]").message


def test_wrong_element_type_names_the_offending_element():
    err = error_of('DECLARE a : ARRAY[1:3] OF INTEGER\na <- [1, 2, "three"]')
    assert "'a[3]'" in err.message and "declared as INTEGER" in err.message


def test_a_bad_list_leaves_the_array_exactly_as_it_was():
    src = 'DECLARE a : ARRAY[1:3] OF INTEGER\na <- [1, 2, 3]\na <- [9, 9, "x"]'
    program = parse(tokenize(src))
    interp = Interpreter()
    with pytest.raises(PseudocodeError):
        interp.run(program)
    assert values_of(interp, "a") == {(1,): 1, (2,): 2, (3,): 3}


def test_a_runtime_error_inside_the_list_leaves_the_array_unchanged():
    src = "DECLARE a : ARRAY[1:3] OF INTEGER\na <- [1, 2, 3]\na <- [7, 8, 5 / 0]"
    interp = Interpreter()
    with pytest.raises(PseudocodeError):
        interp.run(parse(tokenize(src)))
    assert values_of(interp, "a") == {(1,): 1, (2,): 2, (3,): 3}


def test_a_wrong_count_leaves_the_array_unchanged():
    src = "DECLARE a : ARRAY[1:3] OF INTEGER\na <- [1, 2, 3]\na <- [7, 8]"
    interp = Interpreter()
    with pytest.raises(PseudocodeError):
        interp.run(parse(tokenize(src)))
    assert values_of(interp, "a") == {(1,): 1, (2,): 2, (3,): 3}


@pytest.mark.parametrize(
    "src, fragment",
    [
        ("DECLARE x : INTEGER\nx <- [1, 2]", "'x' is not an array"),
        ("q <- [1, 2]", "never declared"),
        ("CONSTANT c <- 5\nc <- [1]", "'c' is not an array"),
        ("DECLARE a : ARRAY[1:3] OF INTEGER\na[1] <- [1, 2]", "not the single element"),
        ("DECLARE a : ARRAY[1:2] OF INTEGER\na <- [[1], [2]]", "1D array, so its list can't contain another list"),
        ("DECLARE g : ARRAY[1:2, 1:2] OF INTEGER\ng <- [1, 2, 3, 4]", "needs one inner list per row"),
        ("DECLARE g : ARRAY[1:2, 1:2] OF INTEGER\ng <- [[1, 2]]", "'g' has 2 rows (1 to 2), but the list has 1 inner list."),
        ("DECLARE g : ARRAY[1:2, 1:3] OF INTEGER\ng <- [[1, 2, 3], [4, 5]]", "Row 2 of the list has 2 values, but 'g' has 3 columns"),
        ("DECLARE g : ARRAY[1:2, 1:2] OF INTEGER\ng <- [[[1]]]", "nested two levels deep"),
        ("DECLARE a : ARRAY[1:2] OF INTEGER\na <- [1, 2", "missing its closing ']'"),
        ("DECLARE a : ARRAY[1:2] OF INTEGER\na <- [1 2]", "Expected ',' or ']'"),
        ("DECLARE a : ARRAY[1:2] OF INTEGER\na <- [1, 2,]", "Expected a value"),
    ],
)
def test_misuse_of_lists_gets_a_clear_error(src, fragment):
    assert fragment in error_of(src).message


@pytest.mark.parametrize(
    "src",
    [
        "OUTPUT [1, 2]",
        "DECLARE a : ARRAY[1:2] OF INTEGER\nOUTPUT [1, 2] + 1",
        "CONSTANT c <- [1, 2]",
        "DECLARE x : INTEGER\nx <- 5 + [1]",
        "DECLARE a : ARRAY[1:2] OF INTEGER\nIF [1] = 1 THEN\n  OUTPUT 1\nENDIF",
    ],
)
def test_a_list_anywhere_but_a_whole_array_assignment_explains_what_it_is_for(src):
    err = error_of(src)
    assert "can only be used on its own to fill a whole array" in err.message


def test_assigning_a_plain_value_to_a_whole_array_explains_both_options():
    err = error_of("DECLARE a : ARRAY[1:2] OF INTEGER\na <- 5")
    assert "a[1] <- value" in err.message and "a <- [value1, value2, ...]" in err.message


def test_a_list_can_be_randomly_generated_and_always_matches_element_by_element_assignment():
    rng = random.Random(4242)
    literals = {
        "INTEGER": lambda: str(rng.randint(-50, 50)),
        "REAL": lambda: rng.choice([str(rng.randint(-9, 9)), f"{rng.randint(-9, 9)}.{rng.randint(0, 99)}"]),
        "STRING": lambda: '"' + "".join(rng.choice("abcxyz ") for _ in range(rng.randint(0, 6))) + '"',
        "BOOLEAN": lambda: rng.choice(["TRUE", "FALSE"]),
    }
    for _ in range(300):
        element_type = rng.choice(list(literals))
        low = rng.randint(-3, 3)
        size = rng.randint(1, 8)
        items = [literals[element_type]() for _ in range(size)]
        decl = f"DECLARE a : ARRAY[{low}:{low + size - 1}] OF {element_type}\n"
        by_list = decl + "a <- [" + ", ".join(items) + "]\n"
        by_element = decl + "".join(f"a[{low + k}] <- {v}\n" for k, v in enumerate(items))
        _, via_list = run_src(by_list)
        _, via_elements = run_src(by_element)
        assert values_of(via_list, "a") == values_of(via_elements, "a"), by_list


# ---- array bug fixes ----------------------------------------------------

@pytest.mark.parametrize(
    "declaration",
    [
        "a : ARRAY[1:100000000] OF INTEGER",
        "a : ARRAY[1:20000, 1:20000] OF INTEGER",
        f"a : ARRAY[1:{MAX_ARRAY_ELEMENTS + 1}] OF INTEGER",
        "a, b, c : ARRAY[1:400000] OF INTEGER",
    ],
)
def test_an_oversized_array_is_refused_instead_of_exhausting_memory(declaration):
    err = error_of(f"DECLARE {declaration}")
    assert err.line == 1
    assert "array elements" in err.message and f"{MAX_ARRAY_ELEMENTS:,}" in err.message


def test_an_oversized_array_is_refused_before_anything_is_allocated():
    interp = Interpreter()
    with pytest.raises(PseudocodeError):
        interp.run(parse(tokenize("DECLARE a : ARRAY[1:100000000] OF INTEGER")))
    assert "a" not in interp.symbols


def test_the_size_limit_counts_every_array_in_the_program():
    err = error_of("DECLARE a : ARRAY[1:600000] OF INTEGER\nDECLARE b : ARRAY[1:600000] OF INTEGER")
    assert err.line == 2
    assert "total to 1,200,000" in err.message


def test_an_array_of_exactly_the_limit_is_allowed():
    last = MAX_ARRAY_ELEMENTS
    output, _ = run_src(f"DECLARE a : ARRAY[1:{last}] OF INTEGER\na[{last}] <- 7\nOUTPUT a[{last}]")
    assert output == ["7"]


def test_ordinary_sized_arrays_are_unaffected():
    output, _ = run_src("DECLARE a : ARRAY[1:30, 1:5] OF CHAR\na[30, 5] <- 'z'\nOUTPUT a[30, 5]")
    assert output == ["z"]


def test_type_errors_say_an_integer_not_a_integer():
    err = error_of('DECLARE s : STRING\ns <- 5')
    assert "Can't assign an INTEGER value" in err.message
    assert "a INTEGER" not in err.message


def test_type_errors_name_the_array_element():
    err = error_of('DECLARE a : ARRAY[1:3] OF INTEGER\na[2] <- "hello"')
    assert "'a[2]'" in err.message


def test_type_errors_name_the_2d_array_element():
    err = error_of("DECLARE g : ARRAY[1:2, 1:2] OF BOOLEAN\ng[2, 1] <- 5")
    assert "'g[2, 1]'" in err.message and "an INTEGER" in err.message


def test_input_errors_name_the_element_and_say_an_integer():
    err = error_of("DECLARE a : ARRAY[1:3] OF INTEGER\nINPUT a[3]", ["abc"])
    assert err.message == "Couldn't read 'abc' as an INTEGER value for 'a[3]'."


def test_input_error_for_a_plain_variable_says_an_integer():
    err = error_of("DECLARE n : INTEGER\nINPUT n", ["abc"])
    assert err.message == "Couldn't read 'abc' as an INTEGER value for 'n'."


def test_other_types_keep_the_article_a():
    assert "as a REAL value" in error_of("DECLARE r : REAL\nINPUT r", ["x"]).message
    assert "as a BOOLEAN value" in error_of("DECLARE b : BOOLEAN\nINPUT b", ["x"]).message


def test_array_index_and_bound_messages_read_naturally():
    assert error_of("DECLARE a : ARRAY[1:3] OF INTEGER\nOUTPUT a[TRUE]").message == (
        "The index for 'a' must be INTEGER, but got BOOLEAN."
    )
    assert "An array's upper bound must be INTEGER" in error_of('DECLARE a : ARRAY[1:"x"] OF INTEGER').message


def test_fractional_array_index_is_still_refused():
    err = error_of("DECLARE a : ARRAY[1:3] OF INTEGER\nOUTPUT a[2.5]")
    assert err.message.startswith("The index for 'a' must be INTEGER, but got the REAL value 2.5")


def test_case_of_an_array_element_explains_what_to_do_instead():
    src = "DECLARE a : ARRAY[1:3] OF INTEGER\nCASE OF a[1]\n  1 : OUTPUT 1\nENDCASE"
    err = error_of(src)
    assert err.line == 2
    assert "CASE OF needs a plain variable" in err.message
    assert "Choice <- a[1]" in err.message


def test_case_of_a_plain_variable_still_works():
    src = "DECLARE x : INTEGER\nx <- 2\nCASE OF x\n  1 : OUTPUT \"one\"\n  2 : OUTPUT \"two\"\nENDCASE"
    assert run_src(src)[0] == ["two"]