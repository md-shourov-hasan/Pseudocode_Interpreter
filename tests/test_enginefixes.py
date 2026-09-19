"""
Regression tests for three engine fixes:

  1. FR-11.1 / NFR-10: an unterminated block that runs into the closing keyword
     of an ENCLOSING block is reported as *itself* missing its terminator, at
     the line of its opening keyword -- not as a stray keyword
     ("NEXT does not have a matching FOR" when a FOR plainly exists).
  2. INTEGER-required positions (FOR bounds/STEP, array bounds and indices,
     DIV/MOD/SUBSTRING/ROUND arguments) accept a REAL that is a whole number
     (5.0, as produced by 10 / 2), and still reject one with a fractional part.
  3. FR-4.3: ROUND rounds a tie away from zero on the number's decimal text,
     instead of Python's round-half-to-even on the binary float.
"""

import os
import subprocess
import sys

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


def error_of(src: str) -> PseudocodeError:
    with pytest.raises(PseudocodeError) as info:
        run_src(src)
    return info.value


# ---- 1. missing terminators are attributed to the right block ------------

NESTED_MISSING = [
    # (id, source, construct blamed, its terminator, blamed line, keyword reached, line reached)
    (
        "if-inside-for",
        "DECLARE i : INTEGER\nFOR i <- 1 TO 3\n  IF i = 1 THEN\n    OUTPUT i\nNEXT i",
        "IF", "ENDIF", 3, "NEXT", 5,
    ),
    (
        "for-inside-while",
        "DECLARE i : INTEGER\nWHILE TRUE DO\n  FOR i <- 1 TO 3\n    OUTPUT i\nENDWHILE",
        "FOR", "NEXT", 3, "ENDWHILE", 5,
    ),
    (
        "while-inside-if",
        "DECLARE i : INTEGER\nIF TRUE THEN\n  WHILE i < 3 DO\n    i <- i + 1\nENDIF",
        "WHILE", "ENDWHILE", 3, "ENDIF", 5,
    ),
    (
        "repeat-inside-if",
        "IF TRUE THEN\n  REPEAT\n    OUTPUT 1\nENDIF",
        "REPEAT", "UNTIL", 2, "ENDIF", 4,
    ),
    (
        "else-reached-inside-while",
        "DECLARE i : INTEGER\nIF TRUE THEN\n  WHILE i < 3 DO\n    i <- i + 1\nELSE\n  OUTPUT 0\nENDIF",
        "WHILE", "ENDWHILE", 3, "ELSE", 5,
    ),
    (
        "if-inside-case-branch",
        "DECLARE x : INTEGER\nCASE OF x\n  1 : IF TRUE THEN\n    OUTPUT 1\nENDCASE",
        "IF", "ENDIF", 3, "ENDCASE", 5,
    ),
    (
        "case-inside-while",
        "DECLARE x : INTEGER\nWHILE TRUE DO\n  CASE OF x\n    1 : OUTPUT 1\nENDWHILE",
        "CASE OF", "ENDCASE", 3, "ENDWHILE", 5,
    ),
]


@pytest.mark.parametrize(
    "src, construct, terminator, line, reached, reached_line",
    [case[1:] for case in NESTED_MISSING],
    ids=[case[0] for case in NESTED_MISSING],
)
def test_unterminated_inner_block_reports_its_own_missing_terminator(
    src, construct, terminator, line, reached, reached_line
):
    err = error_of(src)
    assert err.line == line  # the opening keyword's line
    assert f"This {construct} statement is missing its matching {terminator}." in err.message
    assert f"'{reached}' on line {reached_line}" in err.message
    assert "does not have a matching" not in err.message


def test_missing_endcase_before_an_ordinary_statement_is_reported():
    err = error_of("DECLARE x : INTEGER\nCASE OF x\n  1 : OUTPUT 1\nOUTPUT 2")
    assert err.line == 2
    assert "This CASE OF statement is missing its matching ENDCASE." in err.message


def test_missing_endcase_before_an_assignment_is_reported():
    err = error_of("DECLARE x, y : INTEGER\nCASE OF x\n  1 : y <- 1\ny <- 2")
    assert err.line == 2
    assert "missing its matching ENDCASE" in err.message


def test_nested_if_else_missing_inner_endif_is_not_called_a_duplicate_else():
    src = (
        "IF TRUE THEN\n"
        "  IF FALSE THEN\n"
        "    OUTPUT 1\n"
        "  ELSE\n"
        "    OUTPUT 2\n"
        "ELSE\n"
        "  OUTPUT 3\n"
        "ENDIF"
    )
    err = error_of(src)
    assert err.line == 2
    assert "missing its matching ENDIF" in err.message


def test_genuine_second_else_is_still_reported_as_such():
    err = error_of("IF TRUE THEN\n  OUTPUT 1\nELSE\n  OUTPUT 2\nELSE\n  OUTPUT 3\nENDIF")
    assert err.line == 5
    assert "already has an ELSE" in err.message


# -- controls: messages that must not change --

def test_stray_terminator_with_nothing_open_keeps_its_message():
    err = error_of("ENDIF")
    assert (err.line, err.message) == (1, "ENDIF does not have a matching IF statement.")


def test_terminator_of_a_kind_that_is_not_open_is_still_a_stray_keyword():
    # An IF is open, but no FOR is: NEXT really has nothing to match.
    err = error_of("IF TRUE THEN\n  OUTPUT 1\nNEXT i\nENDIF")
    assert err.line == 3
    assert err.message == "NEXT does not have a matching FOR statement."


@pytest.mark.parametrize(
    "src, message",
    [
        ("IF TRUE THEN\n  OUTPUT 1", "This IF statement is missing its matching ENDIF."),
        ("DECLARE i : INTEGER\nFOR i <- 1 TO 2\n  OUTPUT i", "This FOR statement is missing its matching NEXT."),
        ("REPEAT\n  OUTPUT 1", "This REPEAT statement is missing its matching UNTIL."),
        ("WHILE TRUE DO\n  OUTPUT 1", "This WHILE statement is missing its matching ENDWHILE."),
        ("DECLARE x : INTEGER\nCASE OF x\n  1 : OUTPUT 1", "This CASE OF statement is missing its matching ENDCASE."),
    ],
)
def test_terminator_missing_at_end_of_program_keeps_its_exact_message(src, message):
    assert error_of(src).message == message  # nothing appended when the program simply ends


def test_bad_case_branch_value_keeps_its_message():
    err = error_of("DECLARE x, Total : INTEGER\nCASE OF x\n  Total : OUTPUT 1\nENDCASE")
    assert "Expected a literal value for this CASE branch" in err.message


def test_wrong_next_variable_keeps_its_message():
    err = error_of("DECLARE i, j : INTEGER\nFOR i <- 1 TO 2\nNEXT j")
    assert "doesn't match the loop variable 'i'" in err.message


def test_correctly_nested_program_still_runs():
    src = (
        "DECLARE i, x : INTEGER\n"
        "x <- 1\n"
        "FOR i <- 1 TO 2\n"
        "  IF i = 1 THEN\n"
        "    WHILE FALSE DO\n"
        "      OUTPUT 0\n"
        "    ENDWHILE\n"
        "    CASE OF x\n"
        "      1 : OUTPUT \"one\"\n"
        "      OTHERWISE OUTPUT \"other\"\n"
        "    ENDCASE\n"
        "  ELSE\n"
        "    REPEAT\n"
        "      OUTPUT \"r\"\n"
        "    UNTIL TRUE\n"
        "  ENDIF\n"
        "NEXT i"
    )
    output, _ = run_src(src)
    assert output == ["one", "r"]


# ---- 2. whole-valued REALs are accepted where an INTEGER is required -----

def test_for_bound_from_division_is_accepted():
    output, _ = run_src("DECLARE i : INTEGER\nFOR i <- 1 TO 10 / 2\n  OUTPUT i\nNEXT i")
    assert output == ["1", "2", "3", "4", "5"]


def test_for_step_from_division_is_accepted():
    output, _ = run_src("DECLARE i : INTEGER\nFOR i <- 1 TO 5 STEP 4 / 2\n  OUTPUT i\nNEXT i")
    assert output == ["1", "3", "5"]


def test_for_loop_variable_stays_an_integer_when_bounds_came_from_division():
    _, interp = run_src("DECLARE i : INTEGER\nFOR i <- 1 TO 6 / 2\nNEXT i")
    assert interp.symbols["i"].value == 3
    assert isinstance(interp.symbols["i"].value, int)


def test_loop_over_half_the_length_of_a_string():
    src = 'DECLARE i : INTEGER\nDECLARE s : STRING\ns <- "abcd"\nFOR i <- 1 TO LENGTH(s) / 2\n  OUTPUT i\nNEXT i'
    output, _ = run_src(src)
    assert output == ["1", "2"]


def test_array_index_from_division_is_accepted():
    output, _ = run_src("DECLARE a : ARRAY[1:5] OF INTEGER\na[10 / 2] <- 7\nOUTPUT a[5]")
    assert output == ["7"]


def test_array_bound_from_division_is_accepted():
    output, _ = run_src("DECLARE a : ARRAY[1:10 / 2] OF INTEGER\na[5] <- 1\nOUTPUT a[5]")
    assert output == ["1"]


def test_round_result_can_be_used_as_an_array_index():
    output, _ = run_src("DECLARE a : ARRAY[1:5] OF INTEGER\na[ROUND(2.4, 0)] <- 7\nOUTPUT a[2]")
    assert output == ["7"]


def test_substring_arguments_from_division_are_accepted():
    output, _ = run_src('OUTPUT SUBSTRING("abcd", 1, 4 / 2)')
    assert output == ["ab"]


def test_div_and_mod_accept_whole_valued_real_arguments():
    output, _ = run_src("OUTPUT DIV(10 / 2, 3)\nOUTPUT MOD(10 / 2, 3)")
    assert output == ["1", "2"]


@pytest.mark.parametrize(
    "src",
    [
        "DECLARE i : INTEGER\nFOR i <- 1 TO 10 / 4\nNEXT i",
        "DECLARE i : INTEGER\nFOR i <- 1 TO 3.5\nNEXT i",
        "DECLARE i : INTEGER\nFOR i <- 1 TO 5 STEP 0.5\nNEXT i",
        "DECLARE a : ARRAY[1:5] OF INTEGER\nOUTPUT a[2.5]",
        "DECLARE a : ARRAY[1:2.5] OF INTEGER",
        'OUTPUT SUBSTRING("abcd", 1, 1.5)',
        "OUTPUT DIV(5.5, 2)",
        "OUTPUT MOD(7, 2.5)",
        "OUTPUT ROUND(3.14, 1.5)",
    ],
)
def test_a_real_with_a_fractional_part_is_still_rejected(src):
    err = error_of(src)
    assert "must be INTEGER" in err.message
    assert "not a whole number" in err.message


def test_fractional_error_names_the_offending_value():
    err = error_of("DECLARE i : INTEGER\nFOR i <- 1 TO 10 / 4\nNEXT i")
    assert "2.5" in err.message


def test_division_tip_is_not_shown_for_round_places():
    assert "DIV" in error_of("OUTPUT DIV(5.5, 2)").message
    assert "DIV" not in error_of("OUTPUT ROUND(3.14, 1.5)").message


@pytest.mark.parametrize("src", ["FOR i <- 1 TO TRUE", 'FOR i <- 1 TO "five"'])
def test_booleans_and_strings_are_still_rejected_as_bounds(src):
    err = error_of("DECLARE i : INTEGER\n" + src + "\nNEXT i")
    assert "must be INTEGER" in err.message


def test_narrowing_a_real_into_an_integer_variable_is_unchanged():
    # The deliberate "INTEGER variable <- REAL" truncation (see test_bugfixes.py).
    output, _ = run_src("DECLARE x : INTEGER\nx <- 22 / 7\nOUTPUT x\nx <- -22 / 7\nOUTPUT x")
    assert output == ["3", "-3"]


# ---- 3. ROUND ------------------------------------------------------------

@pytest.mark.parametrize(
    "expr, expected",
    [
        ("ROUND(3.1415, 1)", "3.1"),        # the SRS example (FR-4.3)
        ("ROUND(0.5, 0)", "1"),
        ("ROUND(1.5, 0)", "2"),
        ("ROUND(2.5, 0)", "3"),             # Python's round() gives 2
        ("ROUND(3.5, 0)", "4"),
        ("ROUND(-0.5, 0)", "-1"),
        ("ROUND(-2.5, 0)", "-3"),           # ties go away from zero
        ("ROUND(2.4, 0)", "2"),
        ("ROUND(2.6, 0)", "3"),
        ("ROUND(-2.6, 0)", "-3"),
        ("ROUND(2.675, 2)", "2.68"),        # Python's round() gives 2.67
        ("ROUND(1.005, 2)", "1.01"),        # Python's round() gives 1.0
        ("ROUND(0.125, 2)", "0.13"),
        ("ROUND(2.345, 2)", "2.35"),
        ("ROUND(5, 2)", "5"),
        ("ROUND(1234, -2)", "1200"),
        ("ROUND(1250, -2)", "1300"),        # Python's round() gives 1200
        ("ROUND(-1250, -2)", "-1300"),
    ],
)
def test_round_rounds_ties_away_from_zero(expr, expected):
    output, _ = run_src(f"OUTPUT {expr}")
    assert output == [expected]


@pytest.mark.parametrize("expr", ["ROUND(-0.4, 0)", "ROUND(-0.001, 2)", "ROUND(-0.0, 1)"])
def test_round_never_produces_negative_zero(expr):
    output, _ = run_src(f"OUTPUT {expr}")
    assert output == ["0"]


def test_round_of_an_integer_stays_an_integer():
    _, interp = run_src("DECLARE X : INTEGER\nX <- ROUND(1250, -2)")
    assert interp.symbols["X"].value == 1300
    assert isinstance(interp.symbols["X"].value, int)


def test_round_of_a_real_into_a_real_variable():
    _, interp = run_src("DECLARE X : REAL\nX <- ROUND(2.675, 2)")
    assert interp.symbols["X"].value == pytest.approx(2.68)


@pytest.mark.parametrize(
    "expr, expected",
    [
        ("ROUND(5, -1000000000)", "0"),
        ("ROUND(3.14, -1000000000)", "0"),
        ("ROUND(3.14, 1000000000)", "3.14"),
        ("ROUND(5, 1000000000)", "5"),
    ],
)
def test_round_with_absurd_places_returns_immediately(expr, expected):
    # Python's round(5, -10**9) computes 10**(10**9) and never returns; because
    # that is a single C-level call holding the GIL, an in-process timeout cannot
    # interrupt it. Run in a subprocess so a regression fails this test in 10 s
    # instead of freezing the whole suite.
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    code = (
        "import sys\n"
        f"sys.path.insert(0, {root!r})\n"
        "from engine.lexer import tokenize\n"
        "from engine.parser import parse\n"
        "from engine.interpreter import Interpreter\n"
        f"print(Interpreter().run(parse(tokenize('OUTPUT {expr}')))[0])\n"
    )
    try:
        done = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, timeout=10
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"{expr} did not finish within 10 seconds")
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == expected


@pytest.mark.parametrize("places", [-400, -351, -350, 350, 351, 400])
@pytest.mark.parametrize("value", ["0.0", "1.5", "10 ^ 300", "(10 ^ 308) * 1.5", "5 * 10 ^ -300"])
def test_round_at_the_edges_of_the_float_range_never_leaks_a_python_error(value, places):
    try:
        run_src(f"OUTPUT ROUND({value}, {places})")
    except PseudocodeError:
        pass  # a clean language error is acceptable; anything else fails the test