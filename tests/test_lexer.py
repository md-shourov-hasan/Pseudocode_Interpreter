import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from engine.lexer import tokenize
from engine.tokens import TokenType
from engine.errors import PseudocodeError


def types_of(tokens):
    return [t.type for t in tokens]


def test_comment_stripped_but_line_kept():
    tokens = tokenize("// This is a comment\nOUTPUT Result // trailing comment")
    # comment lines produce nothing but a NEWLINE; inline comment produces nothing
    assert types_of(tokens) == [
        TokenType.NEWLINE,
        TokenType.OUTPUT,
        TokenType.IDENTIFIER,
        TokenType.EOF,
    ]


def test_integer_literal():
    tokens = tokenize("5")
    assert tokens[0].type == TokenType.INTEGER_LITERAL
    assert tokens[0].value == 5


def test_real_literal():
    tokens = tokenize("3.14")
    assert tokens[0].type == TokenType.REAL_LITERAL
    assert tokens[0].value == 3.14


def test_char_literal():
    tokens = tokenize("'x'")
    assert tokens[0].type == TokenType.CHAR_LITERAL
    assert tokens[0].value == "x"


def test_char_literal_too_long_is_error():
    with pytest.raises(PseudocodeError):
        tokenize("'xy'")


def test_string_literal_including_empty():
    tokens = tokenize('"An orange cat"')
    assert tokens[0].type == TokenType.STRING_LITERAL
    assert tokens[0].value == "An orange cat"

    tokens = tokenize('""')
    assert tokens[0].type == TokenType.STRING_LITERAL
    assert tokens[0].value == ""


def test_unterminated_string_is_error():
    with pytest.raises(PseudocodeError):
        tokenize('"unterminated')


def test_boolean_literals():
    tokens = tokenize("TRUE FALSE")
    assert tokens[0].type == TokenType.BOOLEAN_LITERAL and tokens[0].value is True
    assert tokens[1].type == TokenType.BOOLEAN_LITERAL and tokens[1].value is False


def test_declare_statement():
    tokens = tokenize("DECLARE NumTeams : INTEGER")
    assert types_of(tokens) == [
        TokenType.DECLARE,
        TokenType.IDENTIFIER,
        TokenType.COLON,
        TokenType.INTEGER,
        TokenType.EOF,
    ]


def test_assignment_ascii_and_unicode_arrow():
    tokens_ascii = tokenize("MaxAttempt <- 4")
    tokens_unicode = tokenize("MaxAttempt \u2190 4")
    assert types_of(tokens_ascii) == types_of(tokens_unicode) == [
        TokenType.IDENTIFIER,
        TokenType.ASSIGN,
        TokenType.INTEGER_LITERAL,
        TokenType.EOF,
    ]


def test_relational_operators_maximal_munch():
    tokens = tokenize("< <= <> > >= =")
    assert types_of(tokens) == [
        TokenType.LESS_THAN,
        TokenType.LESS_EQUAL,
        TokenType.NOT_EQUAL,
        TokenType.GREATER_THAN,
        TokenType.GREATER_EQUAL,
        TokenType.EQUAL,
        TokenType.EOF,
    ]


def test_for_loop_with_step():
    tokens = tokenize("FOR Index <- 1 TO 30 STEP 5\nNEXT Index")
    assert types_of(tokens) == [
        TokenType.FOR,
        TokenType.IDENTIFIER,
        TokenType.ASSIGN,
        TokenType.INTEGER_LITERAL,
        TokenType.TO,
        TokenType.INTEGER_LITERAL,
        TokenType.STEP,
        TokenType.INTEGER_LITERAL,
        TokenType.NEWLINE,
        TokenType.NEXT,
        TokenType.IDENTIFIER,
        TokenType.EOF,
    ]


def test_array_declaration_and_2d_index():
    tokens = tokenize("DECLARE Grade : ARRAY[1:30, 1:5] OF CHAR\nGrade[16, 3] <- 'A'")
    types = types_of(tokens)
    assert TokenType.ARRAY in types
    assert types.count(TokenType.LBRACKET) == 2
    assert types.count(TokenType.COMMA) == 2  # one in array bounds, one in the index


def test_procedure_call_example_from_srs():
    src = (
        "PROCEDURE CalculateScore(RawScore:INTEGER)\n"
        " FullScore <- (RawScore/60) * 100\n"
        " OUTPUT FullScore\n"
        "ENDPROCEDURE\n"
        "CALL CalculateScore(48) // Returns 80 and 40\n"
    )
    tokens = tokenize(src)
    types = types_of(tokens)
    assert TokenType.PROCEDURE in types
    assert TokenType.ENDPROCEDURE in types
    assert TokenType.CALL in types
    # the inline comment must not produce any tokens for "Returns 80 and 40"
    lexemes = [t.lexeme for t in tokens]
    assert "Returns" not in lexemes


def test_line_numbers_tracked_across_newlines():
    tokens = tokenize("DECLARE X : INTEGER\nDECLARE Y : INTEGER\nDECLARE Z : INTEGER")
    declare_tokens = [t for t in tokens if t.type == TokenType.DECLARE]
    assert [t.line for t in declare_tokens] == [1, 2, 3]


def test_unexpected_character_reports_line():
    with pytest.raises(PseudocodeError) as exc_info:
        tokenize("DECLARE X : INTEGER\nX <- 5 @ 3")
    assert exc_info.value.line == 2
