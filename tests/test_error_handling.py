import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from engine.errors import PseudocodeError
from engine.interpreter import Interpreter
from engine.lexer import tokenize
from engine.parser import parse


def run_src(src: str, inputs=None, output_fn=None):
    program = parse(tokenize(src))
    queue = list(inputs or [])
    interp = Interpreter(
        input_fn=lambda: queue.pop(0),
        output_fn=output_fn,
    )
    return interp.run(program)


# ---- One error contract across lexer / parser / interpreter -----------------

@pytest.mark.parametrize(
    "source, line, expected",
    [
        ("DECLARE X : INTEGER\nX <- 1 @ 2", 2, "Unexpected character"),
        ("DECLARE X : INTEGER\nX <- \"missing", 2, "missing a closing"),
        ("DECLARE X : INTEGER\nX <- 'ab'", 2, "CHAR literal"),
    ],
)
def test_lexer_errors_are_pseudocode_errors_with_source_lines(source, line, expected):
    with pytest.raises(PseudocodeError) as exc_info:
        tokenize(source)
    error = exc_info.value
    assert error.line == line
    assert expected in error.message


def test_parser_does_not_expose_internal_eof_token_name():
    with pytest.raises(PseudocodeError) as exc_info:
        parse(tokenize("OUTPUT"))
    error = exc_info.value
    assert error.line == 1
    assert "end of the program" in error.message
    assert "EOF" not in error.message


def test_parser_does_not_expose_internal_newline_token_name():
    with pytest.raises(PseudocodeError) as exc_info:
        parse(tokenize("OUTPUT\n"))
    error = exc_info.value
    assert error.line == 1
    assert "end of the line" in error.message
    assert "NEWLINE" not in error.message


def test_unmatched_closing_keyword_gets_a_specific_error():
    with pytest.raises(PseudocodeError, match="matching IF statement") as exc_info:
        parse(tokenize("OUTPUT 1\nENDIF"))
    assert exc_info.value.line == 2


@pytest.mark.parametrize(
    "source, phrase",
    [
        ("OPENFILE \"data.txt\" FOR READ", "File handling statements are not supported yet"),
        ("PROCEDURE Demo\nENDPROCEDURE", "Procedures are not supported yet"),
        ("FUNCTION Demo RETURNS INTEGER\nENDFUNCTION", "Functions are not supported yet"),
    ],
)
def test_unimplemented_language_features_fail_without_parser_jargon(source, phrase):
    with pytest.raises(PseudocodeError) as exc_info:
        parse(tokenize(source))
    assert phrase in exc_info.value.message
    assert "Token" not in exc_info.value.message


# ---- runtime errors --------------------------------------------------------

def test_negative_power_of_zero_is_a_pseudocode_error():
    with pytest.raises(PseudocodeError, match="divide by zero") as exc_info:
        run_src("DECLARE X : REAL\nX <- 0 ^ -1")
    assert exc_info.value.line == 2


def test_non_real_result_does_not_expose_python_complex_type():
    with pytest.raises(PseudocodeError) as exc_info:
        run_src("DECLARE X : REAL\nX <- (-1) ^ 0.5")
    error = exc_info.value
    assert error.line == 2
    assert "INTEGER or REAL" in error.message
    assert "complex" not in error.message.lower()


def test_case_of_array_is_rejected_instead_of_comparing_array_storage():
    with pytest.raises(PseudocodeError, match="is an array") as exc_info:
        run_src(
            "DECLARE Values : ARRAY[1:2] OF INTEGER\n"
            "CASE OF Values\n"
            "1 : OUTPUT \"one\"\n"
            "ENDCASE"
        )
    assert exc_info.value.line == 2


def test_real_input_rejects_non_finite_values():
    with pytest.raises(PseudocodeError, match="REAL") as exc_info:
        run_src("DECLARE X : REAL\nINPUT X", inputs=["inf"])
    assert exc_info.value.line == 2


def test_real_literal_outside_python_supported_range_is_a_language_error():
    source = "OUTPUT " + ("9" * 400) + ".0"
    with pytest.raises(PseudocodeError, match="outside the supported numeric range") as exc_info:
        tokenize(source)
    assert exc_info.value.line == 1


def test_interpreter_safety_net_hides_python_exception_details():
    def crashing_output(_line):
        raise RuntimeError("secret implementation detail")

    program = parse(tokenize('OUTPUT "hello"'))
    interp = Interpreter(output_fn=crashing_output)
    with pytest.raises(PseudocodeError) as exc_info:
        interp.run(program)

    error = exc_info.value
    assert error.line == 1
    assert "secret implementation detail" not in error.message
    assert "unexpected runtime error" in error.message


def test_pseudocode_error_serialisation_keeps_line_and_message_contract():
    error = PseudocodeError(7, "Something went wrong.")
    assert error.to_dict() == {"line": 7, "message": "Something went wrong."}
