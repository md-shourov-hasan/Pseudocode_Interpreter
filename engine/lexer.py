"""
Lexer for the IGCSE Pseudocode Compiler.

Implements:
    FR-1.1, FR-1.2, FR-1.3  Comments (// ... to end of line, ignored)
    FR-2.1                  INTEGER literals
    FR-2.2                  REAL literals
    FR-2.3                  CHAR literals
    FR-2.4                  STRING literals (may be empty)
    FR-2.5                  BOOLEAN literals (TRUE / FALSE)
    FR-5.1, FR-5.4          Arithmetic and relational operators

Design notes:
    - Negative number literals (e.g. -3) are NOT produced here as a single
      token; MINUS is always a separate operator token and the parser
      applies it as unary negation. This keeps "A - 1" and "-1" consistent
      and avoids lexer/parser ambiguity.
    - Both the reference arrow "←" (U+2190) and the ASCII fallback "<-"
      are accepted as the assignment operator, since most keyboards and
      text editors cannot easily type "←".
    - NEWLINE tokens are emitted because pseudocode statements are
      separated by line breaks rather than a terminator character; the
      parser uses them to know where one statement ends.
"""

import math

from .tokens import Token, TokenType, KEYWORDS
from .errors import PseudocodeError


class Lexer:
    def __init__(self, source: str):
        self.source = source
        self.pos = 0
        self.line = 1
        # Index (into `source`) of the first character of the current line.
        # Together with `pos`, this gives 1-based columns without a second
        # pass over the source: column = pos - line_start + 1.
        self.line_start = 0
        # Position where the token currently being scanned started; set at
        # the top of _scan_token() and read by _add()/_error_here().
        self._tok_start = 0
        self.tokens: list[Token] = []

    # ---- public API -----------------------------------------------------

    def tokenize(self) -> list[Token]:
        while not self._at_end():
            self._scan_token()
        eof_col = self.pos - self.line_start + 1
        self.tokens.append(Token(TokenType.EOF, "", None, self.line, eof_col, eof_col))
        return self.tokens

    # ---- helpers ----------------------------------------------------------

    def _at_end(self) -> bool:
        return self.pos >= len(self.source)

    def _peek(self, offset: int = 0) -> str:
        i = self.pos + offset
        return self.source[i] if i < len(self.source) else "\0"

    def _advance(self) -> str:
        ch = self.source[self.pos]
        self.pos += 1
        return ch

    def _add(self, type_: TokenType, lexeme: str, value=None):
        column = self._tok_start - self.line_start + 1
        end_column = column + len(lexeme) - 1 if lexeme else column
        self.tokens.append(Token(type_, lexeme, value, self.line, column, end_column))

    def _column_here(self) -> int:
        """1-based column of the token currently being scanned (its first
        character), for error messages raised mid-scan."""
        return self._tok_start - self.line_start + 1

    def _match(self, expected: str) -> bool:
        if self._peek() == expected:
            self.pos += 1
            return True
        return False

    # ---- main dispatch ------------------------------------------------

    def _scan_token(self):
        self._tok_start = self.pos
        ch = self._advance()

        # Newlines are significant (statement separators)
        if ch == "\n":
            self._add(TokenType.NEWLINE, "\\n")
            self.line += 1
            self.line_start = self.pos
            return

        # Whitespace (not newline) is ignored
        if ch in " \t\r":
            return

        # Comments: FR-1.1 / FR-1.2 / FR-1.3 - // to end of line
        if ch == "/" and self._peek() == "/":
            while not self._at_end() and self._peek() != "\n":
                self._advance()
            return

        # Assignment arrow (reference glyph) or ASCII fallback "<-"
        if ch == "\u2190":
            self._add(TokenType.ASSIGN, "\u2190")
            return

        # String literals: FR-2.4
        if ch == '"':
            self._string()
            return

        # Char literals: FR-2.3
        if ch == "'":
            self._char()
            return

        # Numbers: FR-2.1 / FR-2.2
        if ch.isdigit():
            self._number(ch)
            return

        # Identifiers / keywords
        if ch.isalpha() or ch == "_":
            self._identifier(ch)
            return

        # Multi-character operators (maximal munch) then single-character
        if ch == "<":
            if self._match("-"):
                # "<--" (no space before the second "-") is almost always a
                # typo for "<-" with an extra dash, not a deliberate
                # "assign a negative number written with zero spacing" —
                # silently accepting it turns a typo into a different,
                # valid-but-wrong program (e.g. "X <-- 5" quietly becomes
                # "X <- -5"). Catch it here instead of letting it through.
                # "X <- -5" (WITH a space before the minus) is unaffected
                # and still works exactly as intended.
                if self._peek() == "-":
                    raise PseudocodeError(
                        self.line,
                        "Found '<--'. This looks like a typo for the assignment arrow '<-'. "
                        "If you meant to assign a negative number, add a space: '<- -5'.",
                        column=self._column_here(),
                        end_column=self._column_here() + 2,
                    )
                self._add(TokenType.ASSIGN, "<-")
            elif self._match("="):
                self._add(TokenType.LESS_EQUAL, "<=")
            elif self._match(">"):
                self._add(TokenType.NOT_EQUAL, "<>")
            else:
                self._add(TokenType.LESS_THAN, "<")
            return

        if ch == ">":
            if self._match("="):
                self._add(TokenType.GREATER_EQUAL, ">=")
            else:
                self._add(TokenType.GREATER_THAN, ">")
            return

        single_char_ops = {
            "+": TokenType.PLUS,
            "-": TokenType.MINUS,
            "*": TokenType.MULTIPLY,
            "/": TokenType.DIVIDE,
            "^": TokenType.POWER,
            "=": TokenType.EQUAL,
            "(": TokenType.LPAREN,
            ")": TokenType.RPAREN,
            "[": TokenType.LBRACKET,
            "]": TokenType.RBRACKET,
            ",": TokenType.COMMA,
            ":": TokenType.COLON,
        }
        if ch in single_char_ops:
            self._add(single_char_ops[ch], ch)
            return

        raise PseudocodeError(
            self.line,
            f"Unexpected character '{ch}'.",
            column=self._column_here(),
            end_column=self._column_here(),
        )

    # ---- literal scanners ------------------------------------------------

    def _string(self):
        start_line = self.line
        start_col = self._column_here()
        chars = []
        while not self._at_end() and self._peek() != '"':
            c = self._advance()
            if c == "\n":
                raise PseudocodeError(
                    start_line,
                    "String is missing a closing \" before the end of the line.",
                    column=start_col,
                    end_column=start_col,
                )
            chars.append(c)
        if self._at_end():
            raise PseudocodeError(
                start_line,
                "String is missing a closing \".",
                column=start_col,
                end_column=start_col,
            )
        self._advance()  # consume closing quote
        text = "".join(chars)
        self._add(TokenType.STRING_LITERAL, f'"{text}"', text)

    def _char(self):
        start_line = self.line
        start_col = self._column_here()
        if self._at_end() or self._peek() == "\n":
            raise PseudocodeError(
                start_line,
                "Character literal is missing a closing '.",
                column=start_col,
                end_column=start_col,
            )
        c = self._advance()
        if self._peek() != "'":
            raise PseudocodeError(
                start_line,
                "A CHAR literal must contain exactly one character between quotes, e.g. 'x'.",
                column=start_col,
                end_column=start_col,
            )
        self._advance()  # consume closing quote
        self._add(TokenType.CHAR_LITERAL, f"'{c}'", c)

    def _number(self, first_digit: str):
        start_line = self.line
        digits = [first_digit]
        while self._peek().isdigit():
            digits.append(self._advance())

        if self._peek() == "." and self._peek(1).isdigit():
            digits.append(self._advance())  # consume '.'
            while self._peek().isdigit():
                digits.append(self._advance())
            text = "".join(digits)
            value = float(text)
            if not math.isfinite(value):
                raise PseudocodeError(
                    start_line,
                    "This REAL literal is outside the supported numeric range.",
                    column=self._column_here(),
                    end_column=self._column_here() + len(text) - 1,
                )
            self._add(TokenType.REAL_LITERAL, text, value)
            return

        text = "".join(digits)
        self._add(TokenType.INTEGER_LITERAL, text, int(text))

    def _identifier(self, first_char: str):
        chars = [first_char]
        while self._peek().isalnum() or self._peek() == "_":
            chars.append(self._advance())
        text = "".join(chars)

        if text in KEYWORDS:
            tok_type = KEYWORDS[text]
            value = True if text == "TRUE" else False if text == "FALSE" else None
            self._add(tok_type, text, value)
        else:
            self._add(TokenType.IDENTIFIER, text)


def tokenize(source: str) -> list[Token]:
    """Convenience wrapper: tokenize a full source string."""
    return Lexer(source).tokenize()
