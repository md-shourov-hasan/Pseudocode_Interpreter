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
    """

    def __init__(self, line: int, message: str):
        self.line = line if isinstance(line, int) and line >= 0 else 0
        self.message = str(message).strip()
        super().__init__(f"Line {self.line}: {self.message}")

    def to_dict(self) -> dict:
        """Serialisable form for the web frontend."""
        return {"line": self.line, "message": self.message}


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

    if isinstance(exc, ZeroDivisionError):
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
