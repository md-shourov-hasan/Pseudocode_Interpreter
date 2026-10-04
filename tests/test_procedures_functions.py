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


# ---- PROCEDURE parsing (FR-10.1) -------------------------------------------


def test_procedure_without_params_parses():
    prog = parse_src("PROCEDURE Greet\nOUTPUT \"hi\"\nENDPROCEDURE")
    decl = prog.statements[0]
    assert isinstance(decl, ast.ProcedureDecl)
    assert decl.name == "Greet"
    assert decl.params == []
    assert len(decl.body) == 1


def test_procedure_with_params_parses():
    prog = parse_src(
        "PROCEDURE CalculateScore(RawScore:INTEGER)\n"
        " OUTPUT RawScore\n"
        "ENDPROCEDURE"
    )
    decl = prog.statements[0]
    assert [p.name for p in decl.params] == ["RawScore"]
    assert [p.data_type for p in decl.params] == ["INTEGER"]


def test_procedure_with_multiple_params_parses():
    prog = parse_src(
        "PROCEDURE Combine(A:INTEGER, B:REAL, C:STRING)\nOUTPUT A\nENDPROCEDURE"
    )
    decl = prog.statements[0]
    assert [p.name for p in decl.params] == ["A", "B", "C"]
    assert [p.data_type for p in decl.params] == ["INTEGER", "REAL", "STRING"]


def test_missing_endprocedure_is_clear_error():
    with pytest.raises(PseudocodeError, match="ENDPROCEDURE"):
        parse_src("PROCEDURE Foo\nOUTPUT 1")


def test_duplicate_parameter_name_is_rejected():
    with pytest.raises(PseudocodeError, match="repeated"):
        parse_src("PROCEDURE Foo(A:INTEGER, A:REAL)\nENDPROCEDURE")


def test_array_parameter_is_rejected():
    # Arrays cannot be passed as PROCEDURE/FUNCTION parameters -- a
    # parameter is always scalar (FR-10.1, FR-10.3).
    with pytest.raises(PseudocodeError, match="can't be declared as an ARRAY"):
        parse_src("PROCEDURE Foo(A:ARRAY[1:5] OF INTEGER)\nENDPROCEDURE")


def test_endprocedure_without_procedure_is_a_clear_error():
    with pytest.raises(PseudocodeError, match="matching PROCEDURE statement"):
        parse_src("OUTPUT 1\nENDPROCEDURE")


# ---- FUNCTION parsing (FR-10.3) --------------------------------------------


def test_function_without_params_parses():
    prog = parse_src("FUNCTION Answer RETURNS INTEGER\nRETURN 42\nENDFUNCTION")
    decl = prog.statements[0]
    assert isinstance(decl, ast.FunctionDecl)
    assert decl.name == "Answer"
    assert decl.params == []
    assert decl.return_type == "INTEGER"


def test_function_with_params_parses():
    prog = parse_src(
        "FUNCTION SumSquare(Num1:INTEGER, Num2:INTEGER) RETURNS INTEGER\n"
        " RETURN Num1 ^ 2 + Num2 ^ 2\n"
        "ENDFUNCTION"
    )
    decl = prog.statements[0]
    assert [p.name for p in decl.params] == ["Num1", "Num2"]
    assert decl.return_type == "INTEGER"


def test_missing_endfunction_is_clear_error():
    with pytest.raises(PseudocodeError, match="ENDFUNCTION"):
        parse_src("FUNCTION Foo RETURNS INTEGER\nRETURN 1")


def test_function_missing_returns_is_clear_error():
    with pytest.raises(PseudocodeError, match="RETURNS"):
        parse_src("FUNCTION Foo INTEGER\nRETURN 1\nENDFUNCTION")


# ---- RETURN placement (FR-10.3) --------------------------------------------


def test_return_outside_any_callable_is_rejected():
    with pytest.raises(PseudocodeError, match="only valid inside a user-defined FUNCTION"):
        parse_src("RETURN 1")


def test_return_inside_procedure_is_rejected():
    with pytest.raises(PseudocodeError, match="cannot be used inside a PROCEDURE"):
        parse_src("PROCEDURE Foo\nRETURN 1\nENDPROCEDURE")


def test_return_inside_nested_if_within_function_is_allowed():
    prog = parse_src(
        "FUNCTION Foo RETURNS INTEGER\n"
        " IF TRUE THEN\n"
        "  RETURN 1\n"
        " ENDIF\n"
        " RETURN 0\n"
        "ENDFUNCTION"
    )
    decl = prog.statements[0]
    assert isinstance(decl.body[0], ast.If)
    assert isinstance(decl.body[0].then_body[0], ast.Return)


# ---- placement: top of the program only (SRS 3.10) -------------------------


def test_procedure_after_a_statement_is_rejected():
    with pytest.raises(PseudocodeError, match="top of the program"):
        parse_src("OUTPUT 1\nPROCEDURE Foo\nENDPROCEDURE")


def test_function_after_a_statement_is_rejected():
    with pytest.raises(PseudocodeError, match="top of the program"):
        parse_src("DECLARE X : INTEGER\nFUNCTION Foo RETURNS INTEGER\nRETURN 1\nENDFUNCTION")


def test_nested_procedure_definition_is_rejected():
    with pytest.raises(PseudocodeError, match="top of the program"):
        parse_src(
            "PROCEDURE Outer\n"
            " PROCEDURE Inner\n"
            " ENDPROCEDURE\n"
            "ENDPROCEDURE"
        )


def test_multiple_definitions_at_top_are_all_hoisted():
    prog = parse_src(
        "PROCEDURE A\nENDPROCEDURE\n"
        "FUNCTION B RETURNS INTEGER\nRETURN 1\nENDFUNCTION\n"
        "OUTPUT 1"
    )
    assert isinstance(prog.statements[0], ast.ProcedureDecl)
    assert isinstance(prog.statements[1], ast.FunctionDecl)
    assert isinstance(prog.statements[2], ast.Output)


# ---- CALL parsing (FR-10.2) -------------------------------------------------


def test_call_without_parens_parses():
    prog = parse_src("PROCEDURE Foo\nENDPROCEDURE\nCALL Foo")
    call = prog.statements[1]
    assert isinstance(call, ast.ProcedureCall)
    assert call.name == "Foo"
    assert call.args == []


def test_call_with_args_parses():
    prog = parse_src("PROCEDURE Foo(A:INTEGER)\nENDPROCEDURE\nCALL Foo(48)")
    call = prog.statements[1]
    assert len(call.args) == 1


# ---- end-to-end execution: procedures --------------------------------------


def test_call_procedure_with_no_params():
    output, _ = run_src(
        "PROCEDURE Greet\n"
        " OUTPUT \"hi\"\n"
        "ENDPROCEDURE\n"
        "CALL Greet"
    )
    assert output == ["hi"]


def test_call_procedure_substitutes_parameters():
    # The SRS's own example (3.10.1), adapted to DECLARE its locals explicitly
    # (this interpreter enforces DECLARE-before-use consistently -- FR-11.2).
    # OUTPUT joins comma-separated values with no separator into one line
    # (existing FR-4.2 behaviour), so FullScore/HalfScore land on one line.
    output, _ = run_src(
        "PROCEDURE CalculateScore(RawScore:INTEGER)\n"
        " DECLARE FullScore, HalfScore : REAL\n"
        " FullScore <- (RawScore / 60) * 100\n"
        " HalfScore <- (RawScore / 60) * 50\n"
        " OUTPUT FullScore, HalfScore\n"
        "ENDPROCEDURE\n"
        "CALL CalculateScore(48)"
    )
    assert output == ["8040"]


def test_procedure_can_be_called_more_than_once():
    output, _ = run_src(
        "PROCEDURE Greet(Name:STRING)\n"
        " OUTPUT \"Hi \", Name\n"
        "ENDPROCEDURE\n"
        "CALL Greet(\"Ada\")\n"
        "CALL Greet(\"Lin\")"
    )
    assert output == ["Hi Ada", "Hi Lin"]


def test_calling_undefined_procedure_is_a_clear_error():
    with pytest.raises(PseudocodeError, match="no PROCEDURE with that name"):
        run_src("CALL DoesNotExist")


def test_call_wrong_argument_count_is_a_clear_error():
    with pytest.raises(PseudocodeError, match="expects 1 parameter, but got 2"):
        run_src("PROCEDURE Foo(A:INTEGER)\nENDPROCEDURE\nCALL Foo(1, 2)")


def test_calling_a_builtin_with_call_is_rejected():
    with pytest.raises(PseudocodeError, match="built-in function, not a PROCEDURE"):
        run_src("CALL ROUND(1.5, 0)")


def test_calling_a_function_with_call_is_rejected():
    # FR-10.4: a FUNCTION can only be invoked as part of an expression.
    with pytest.raises(PseudocodeError, match="is a FUNCTION, not a PROCEDURE"):
        run_src(
            "FUNCTION Double(N:INTEGER) RETURNS INTEGER\n"
            " RETURN N * 2\n"
            "ENDFUNCTION\n"
            "CALL Double(5)"
        )


# ---- end-to-end execution: functions ---------------------------------------


def test_function_call_in_expression():
    # The SRS's own example (3.10.2).
    output, _ = run_src(
        "FUNCTION SumSquare(Num1:INTEGER, Num2:INTEGER) RETURNS INTEGER\n"
        " RETURN Num1 ^ 2 + Num2 ^ 2\n"
        "ENDFUNCTION\n"
        "OUTPUT \"Sum of squares: \", SumSquare(5, 10)"
    )
    assert output == ["Sum of squares: 125"]


def test_function_with_no_params():
    output, _ = run_src(
        "FUNCTION Answer RETURNS INTEGER\n"
        " RETURN 42\n"
        "ENDFUNCTION\n"
        "OUTPUT Answer()"
    )
    assert output == ["42"]


def test_function_return_can_be_conditional():
    output, _ = run_src(
        "FUNCTION Abs(N:INTEGER) RETURNS INTEGER\n"
        " IF N < 0 THEN\n"
        "  RETURN -N\n"
        " ENDIF\n"
        " RETURN N\n"
        "ENDFUNCTION\n"
        "OUTPUT Abs(-5)\n"
        "OUTPUT Abs(5)"
    )
    assert output == ["5", "5"]


def test_function_using_call_keyword_is_rejected_per_fr_10_4():
    with pytest.raises(PseudocodeError, match="is a FUNCTION, not a PROCEDURE"):
        run_src(
            "FUNCTION Foo RETURNS INTEGER\nRETURN 1\nENDFUNCTION\nCALL Foo"
        )


def test_procedure_used_in_expression_is_rejected():
    with pytest.raises(PseudocodeError, match="is a PROCEDURE, not a FUNCTION"):
        run_src(
            "PROCEDURE Foo\nENDPROCEDURE\nDECLARE X : INTEGER\nX <- Foo()"
        )


def test_function_that_never_returns_is_a_clear_error():
    with pytest.raises(PseudocodeError, match="finished without executing a RETURN"):
        run_src(
            "FUNCTION Foo RETURNS INTEGER\n"
            " IF FALSE THEN\n"
            "  RETURN 1\n"
            " ENDIF\n"
            "ENDFUNCTION\n"
            "OUTPUT Foo()"
        )


def test_function_return_value_is_type_checked():
    with pytest.raises(PseudocodeError, match="return value"):
        run_src(
            "FUNCTION Foo RETURNS BOOLEAN\n"
            " RETURN 1\n"
            "ENDFUNCTION\n"
            "OUTPUT Foo()"
        )


def test_function_return_value_widens_integer_to_real():
    output, _ = run_src(
        "FUNCTION Half(N:INTEGER) RETURNS REAL\n"
        " RETURN N / 2\n"
        "ENDFUNCTION\n"
        "OUTPUT Half(5)"
    )
    assert output == ["2.5"]


def test_calling_unknown_name_in_expression_is_clear():
    with pytest.raises(PseudocodeError, match="isn't a recognized built-in or user-defined function"):
        run_src("DECLARE X : INTEGER\nX <- NotAThing(1)")


# ---- parameter type coercion (mirrors assignment rules) --------------------


def test_integer_argument_widens_into_real_parameter():
    output, _ = run_src(
        "PROCEDURE Show(N:REAL)\n"
        " OUTPUT N\n"
        "ENDPROCEDURE\n"
        "CALL Show(3)"
    )
    assert output == ["3"]


def test_boolean_argument_into_integer_parameter_is_rejected():
    with pytest.raises(PseudocodeError, match="declared as INTEGER"):
        run_src("PROCEDURE Foo(N:INTEGER)\nENDPROCEDURE\nCALL Foo(TRUE)")


# ---- scoping (Milestone 8 design decision; see interpreter.py docstring) ---


def test_parameter_is_local_to_the_call():
    output, _ = run_src(
        "PROCEDURE Foo(N:INTEGER)\n"
        " N <- N + 1\n"
        " OUTPUT N\n"
        "ENDPROCEDURE\n"
        "DECLARE N : INTEGER\n"
        "N <- 10\n"
        "CALL Foo(5)\n"
        "OUTPUT N"
    )
    assert output == ["6", "10"]  # the global N is untouched by the call


def test_global_variable_is_not_visible_inside_a_procedure():
    with pytest.raises(PseudocodeError, match="never declared"):
        run_src(
            "PROCEDURE Foo\n"
            " OUTPUT X\n"
            "ENDPROCEDURE\n"
            "DECLARE X : INTEGER\n"
            "X <- 1\n"
            "CALL Foo"
        )


def test_global_constant_is_visible_inside_a_function():
    # Definitions must stay at the top (SRS 3.10), so the CONSTANT is
    # declared after the FUNCTION but is still set by the time it's called.
    output, _ = run_src(
        "FUNCTION AddBonus(N:INTEGER) RETURNS INTEGER\n"
        " RETURN N + Bonus\n"
        "ENDFUNCTION\n"
        "CONSTANT Bonus <- 10\n"
        "OUTPUT AddBonus(5)"
    )
    assert output == ["15"]


def test_local_declare_does_not_leak_to_caller():
    with pytest.raises(PseudocodeError, match="never declared"):
        run_src(
            "PROCEDURE Foo\n"
            " DECLARE Local : INTEGER\n"
            " Local <- 1\n"
            "ENDPROCEDURE\n"
            "CALL Foo\n"
            "OUTPUT Local"
        )


def test_parameter_name_clashing_with_global_constant_is_rejected():
    with pytest.raises(PseudocodeError, match="same name as the global CONSTANT"):
        run_src(
            "PROCEDURE Foo(Max:INTEGER)\nENDPROCEDURE\n"
            "CONSTANT Max <- 10\n"
            "CALL Foo(5)"
        )


# ---- recursion --------------------------------------------------------------


def test_recursive_function_factorial():
    output, _ = run_src(
        "FUNCTION Factorial(N:INTEGER) RETURNS INTEGER\n"
        " IF N <= 1 THEN\n"
        "  RETURN 1\n"
        " ENDIF\n"
        " RETURN N * Factorial(N - 1)\n"
        "ENDFUNCTION\n"
        "OUTPUT Factorial(5)"
    )
    assert output == ["120"]


def test_unbounded_recursion_is_caught_with_a_clear_error():
    with pytest.raises(PseudocodeError, match="Too many nested or recursive"):
        run_src(
            "FUNCTION Loop(N:INTEGER) RETURNS INTEGER\n"
            " RETURN Loop(N + 1)\n"
            "ENDFUNCTION\n"
            "OUTPUT Loop(0)"
        )


def test_mutually_recursive_functions():
    output, _ = run_src(
        "FUNCTION IsEven(N:INTEGER) RETURNS BOOLEAN\n"
        " IF N = 0 THEN\n"
        "  RETURN TRUE\n"
        " ENDIF\n"
        " RETURN IsOdd(N - 1)\n"
        "ENDFUNCTION\n"
        "FUNCTION IsOdd(N:INTEGER) RETURNS BOOLEAN\n"
        " IF N = 0 THEN\n"
        "  RETURN FALSE\n"
        " ENDIF\n"
        " RETURN IsEven(N - 1)\n"
        "ENDFUNCTION\n"
        "OUTPUT IsEven(4)"
    )
    assert output == ["TRUE"]


# ---- interaction with other Milestone 8-adjacent features -------------------


def test_procedure_and_function_names_cannot_collide():
    with pytest.raises(PseudocodeError, match="already been defined"):
        run_src(
            "PROCEDURE Foo\nENDPROCEDURE\n"
            "FUNCTION Foo RETURNS INTEGER\nRETURN 1\nENDFUNCTION\n"
            "CALL Foo"
        )


def test_procedure_name_cannot_reuse_a_builtin_name():
    with pytest.raises(PseudocodeError, match="already the name of a built-in function"):
        run_src("PROCEDURE ROUND\nENDPROCEDURE\nCALL ROUND")


def test_function_can_call_a_procedure_indirectly_is_not_required_but_procedure_can_call_function():
    # A PROCEDURE's body can use a FUNCTION inside an expression.
    output, _ = run_src(
        "FUNCTION Square(N:INTEGER) RETURNS INTEGER\n"
        " RETURN N * N\n"
        "ENDFUNCTION\n"
        "PROCEDURE ShowSquare(N:INTEGER)\n"
        " OUTPUT Square(N)\n"
        "ENDPROCEDURE\n"
        "CALL ShowSquare(6)"
    )
    assert output == ["36"]


def test_array_declared_inside_recursive_function_does_not_exhaust_budget():
    # Regression check for the call-frame array-element bookkeeping: each
    # call's local array must be released when that call returns, or a
    # modest recursion depth would spuriously hit MAX_ARRAY_ELEMENTS.
    output, _ = run_src(
        "FUNCTION Touch(N:INTEGER) RETURNS INTEGER\n"
        " DECLARE Scratch : ARRAY[1:1000] OF INTEGER\n"
        " Scratch[1] <- N\n"
        " IF N <= 0 THEN\n"
        "  RETURN Scratch[1]\n"
        " ENDIF\n"
        " RETURN Touch(N - 1)\n"
        "ENDFUNCTION\n"
        "OUTPUT Touch(150)"
    )
    assert output == ["0"]