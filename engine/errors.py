"""
Shared user-facing error definitions and formatting helpers.

Milestone 10 establishes one error contract for the whole compiler:

* source-related errors carry a 1-based source line (or 0 when no source
  line exists, such as a web-session failure),
* messages use pseudocode/student terminology rather than Python or parser
  implementation terminology, and
* lexer, parser, and interpreter errors all flow through ``PseudocodeError``.
"""


class PseudocodeError(Exception):
    """A user-facing compiler/interpreter error.

    ``line`` is 1-based for source errors. ``0`` is reserved for errors that
    have no meaningful source location, such as a generic host/runtime
    failure surfaced by the web interface.

    ``column``/``end_column`` are an OPTIONAL 1-based, inclusive character
    span on that line -- e.g. ``column=8, end_column=14`` covers the seven
    characters from the 8th through the 14th. They let the frontend draw an
    underline beneath the offending text, the way a compiler diagnostic
    normally does:

        Score <- "hello"
               ^^^^^^^
        Type mismatch: expected INTEGER

    Most errors DO carry a span (undeclared identifiers, type mismatches,
    division by zero, array bounds, non-BOOLEAN conditions, ...). A span is
    deliberately omitted -- both stay ``None`` -- for purely structural
    errors that don't point at one piece of text, such as "this IF is
    missing its ENDIF" (the problem is the block as a whole, not any single
    token on the reported line).
    """

    def __init__(self, line: int, message: str, column: int = None, end_column: int = None):
        self.line = line if isinstance(line, int) and line >= 0 else 0
        self.message = str(message).strip()
        if isinstance(column, int) and not isinstance(column, bool) and column > 0:
            self.column = column
            # Fall back to a single-character span rather than discarding a
            # valid start column because the end wasn't given or is bogus.
            self.end_column = (
                end_column
                if isinstance(end_column, int) and not isinstance(end_column, bool) and end_column >= column
                else column
            )
        else:
            self.column = None
            self.end_column = None
        super().__init__(f"Line {self.line}: {self.message}")

    def to_dict(self) -> dict:
        """Serialisable form for the web frontend.

        ``column``/``end_column`` are only included when this error actually
        has a span, keeping the payload identical to the pre-span contract
        for errors that don't.
        """
        d = {"line": self.line, "message": self.message}
        if self.column is not None:
            d["column"] = self.column
            d["end_column"] = self.end_column
        return d


def describe_token(token) -> str:
    """Return a student-friendly description of a parser token.

    Parser diagnostics used to expose implementation names such as
    ``EOF`` and ``NEWLINE``. Those names are useful to developers but not to
    students, so the parser uses this helper anywhere it needs to describe
    the token it found.
    """

    token_type = getattr(getattr(token, "type", None), "name", "")
    lexeme = getattr(token, "lexeme", "")

    if token_type == "EOF":
        return "the end of the program"
    if token_type == "NEWLINE":
        return "the end of the line"
    if lexeme:
        return f"'{lexeme}'"

    # Fallback for token types that have no source lexeme.
    readable = token_type.replace("_", " ").lower() if token_type else "an unknown symbol"
    return readable


def format_type_name(value) -> str:
    """Return one of the pseudocode data-type names when possible.

    Values outside the five supported pseudocode data types are deliberately
    described as unsupported values rather than exposing Python type names
    such as ``complex`` or ``dict`` to the student.
    """

    if isinstance(value, bool):
        return "BOOLEAN"
    if isinstance(value, int):
        return "INTEGER"
    if isinstance(value, float):
        return "REAL"
    if isinstance(value, str) and len(value) == 1:
        return "CHAR"
    if isinstance(value, str):
        return "STRING"
    return "an unsupported value"


def normalize_unexpected_error(line: int, exc: Exception) -> PseudocodeError:
    """Convert an unexpected Python-level runtime error to a safe message.

    Specific, student-actionable runtime failures are handled at their
    operation sites. This helper is the final safety net so an implementation
    exception can never leak into the language's normal error channel.
    """

    if isinstance(exc, MemoryError):
        message = "The program was stopped because it used too much memory."
    elif isinstance(exc, ZeroDivisionError):
        message = "The program tried to divide by zero."
    elif isinstance(exc, OverflowError):
        message = "The calculation produced a number outside the supported range."
    elif isinstance(exc, ValueError):
        message = "The program could not use one of the values in this statement."
    elif isinstance(exc, TypeError):
        message = "The operation could not be performed with the values in this statement."
    elif isinstance(exc, (IndexError, KeyError)):
        message = "The program tried to access data that is not available."
    else:
        message = "The program could not be completed because of an unexpected runtime error."

    return PseudocodeError(line, message)
