"""
Tests for the array work:

  * Whole-array operations are refused, with guidance. A list cannot be
    assigned (MyArray <- [1, 2, 3]) and a whole array cannot be output
    (OUTPUT MyArray): arrays are filled and shown one element at a time,
    through an index.
  * Array bug fixes: an unbounded DECLARE can no longer exhaust memory; error
    messages name the element ('a[2]'), read "an INTEGER", and explain how to
    index an array; CASE OF an array element explains itself.
"""

import os
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


# ---- LENGTH measures strings only ----------------------------------------
# (LENGTH(array) was tried and deliberately removed: the language's LENGTH
# function is defined for strings, so an array is not a valid argument.)

def test_length_of_a_string_and_string_variable_still_work():
    output, _ = run_src('DECLARE s : STRING\ns <- "Shourov"\nOUTPUT LENGTH(s)\nOUTPUT LENGTH("Cat")')
    assert output == ["7", "3"]


def test_length_of_a_string_element_is_the_strings_length():
    src = 'DECLARE n : ARRAY[1:2] OF STRING\nn[1] <- "Cat"\nn[2] <- "Rayan"\nOUTPUT LENGTH(n[2])'
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


# ---- assigning a list to an array is refused ------------------------------
# "MyArray <- [1, 2, 3]" is not part of the language. It is reported while the
# program is being read (before anything runs), and says how to do it instead.

def list_error(name):
    return (
        f"A list of values can't be assigned to '{name}' in one step. "
        f"An array is filled one element at a time using an index, e.g. {name}[1] <- value."
    )


@pytest.mark.parametrize(
    "src, name, line",
    [
        ('DECLARE MyArray : ARRAY[1:3] OF STRING\nMyArray <- ["Cat", "Dog", "Shourov"]', "MyArray", 2),
        ("MyArray <- [1, 2, 3]", "MyArray", 1),
        ("DECLARE Grid : ARRAY[1:2, 1:2] OF INTEGER\nGrid <- [[1, 2], [3, 4]]", "Grid", 2),
        ("DECLARE a : ARRAY[1:2] OF INTEGER\na <- []", "a", 2),
        ("DECLARE a : ARRAY[1:2] OF INTEGER\na <- [\n  1,\n  2\n]", "a", 2),
        ("DECLARE a : ARRAY[1:3] OF INTEGER\na[1] <- [1, 2]", "a", 2),
        ("DECLARE x : INTEGER\nx <- [1]", "x", 2),
        ("DECLARE a : ARRAY[1:2] OF INTEGER\nOUTPUT 1\nIF TRUE THEN\n  a <- [1, 2]\nENDIF", "a", 4),
    ],
)
def test_assigning_a_list_is_an_error_that_explains_how_to_fill_an_array(src, name, line):
    with pytest.raises(PseudocodeError) as info:
        parse(tokenize(src))  # a syntax error: found before the program runs
    assert info.value.line == line
    assert info.value.message == list_error(name)


def test_a_list_error_stops_the_program_before_anything_runs():
    printed = []
    with pytest.raises(PseudocodeError):
        Interpreter(output_fn=printed.append).run(parse(tokenize('OUTPUT "hello"\nMyArray <- [1]')))
    assert printed == []


@pytest.mark.parametrize(
    "src",
    [
        "OUTPUT [1, 2]",
        "DECLARE x : INTEGER\nx <- 5 + [1]",
        "CONSTANT c <- [1, 2]",
        "DECLARE a : ARRAY[1:2] OF INTEGER\nIF [1] = 1 THEN\n  OUTPUT 1\nENDIF",
    ],
)
def test_a_list_anywhere_else_says_lists_are_not_supported(src):
    err = error_of(src)
    assert "A list such as [1, 2, 3] isn't supported" in err.message
    assert "MyArray[1]" in err.message


def test_indexing_syntax_is_unaffected_by_the_list_error():
    # '[' after a name is an index, as ever; only a '[' that starts a VALUE is refused.
    output, _ = run_src(
        "DECLARE a : ARRAY[1:2] OF INTEGER\nDECLARE g : ARRAY[1:2, 1:2] OF INTEGER\n"
        "a[1] <- 5\ng[2, 1] <- a[1] + 1\nOUTPUT a[1], g[2, 1]"
    )
    assert output == ["56"]


# ---- assigning or outputting a whole array is refused -----------------------

def test_assigning_a_plain_value_to_a_whole_array_explains_how_to_assign_elements():
    err = error_of("DECLARE a : ARRAY[1:2] OF INTEGER\na <- 5")
    assert err.line == 2
    assert err.message == (
        "'a' is an array, so it can't be assigned as a whole. "
        "Assign each element separately using its index, e.g. a[1] <- value."
    )


def test_copying_one_array_into_another_is_still_refused():
    err = error_of("DECLARE a, b : ARRAY[1:2] OF INTEGER\nb <- a")
    assert err.line == 2
    assert "'b' is an array, so it can't be assigned as a whole" in err.message  # the target is checked first


def test_reading_a_whole_array_into_a_variable_is_still_refused():
    err = error_of("DECLARE a : ARRAY[1:2] OF INTEGER\nDECLARE x : INTEGER\nx <- a")
    assert err.message == "'a' is an array — use an index, e.g. a[1], to access an element."


@pytest.mark.parametrize("statement", ["OUTPUT a", 'OUTPUT "x", a', 'OUTPUT a, "x"'])
def test_outputting_a_whole_array_explains_how_to_output_elements(statement):
    err = error_of(f"DECLARE a : ARRAY[1:2] OF INTEGER\n{statement}")
    assert err.line == 2
    assert err.message == (
        "'a' is an array, so it can't be output as a whole. "
        "Output each element separately using its index, e.g. OUTPUT a[1]."
    )


def test_the_recommended_way_fills_and_shows_an_array_element_by_element():
    src = (
        "DECLARE MyArray : ARRAY[1:3] OF STRING\nDECLARE i : INTEGER\n"
        'MyArray[1] <- "Cat"\nMyArray[2] <- "Dog"\nMyArray[3] <- "Shourov"\n'
        "FOR i <- 1 TO 3\n  OUTPUT i, \": \", MyArray[i]\nNEXT i"
    )
    assert run_src(src)[0] == ["1: Cat", "2: Dog", "3: Shourov"]


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