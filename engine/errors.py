"""
Shared error type for the pseudocode compiler.

Per NFR-10, error messages must be phrased in terms a student familiar
with the pseudocode syntax can understand — never Python tracebacks or
compiler-implementation jargon. Every stage (lexer, parser, interpreter)
raises PseudocodeError with a line number and a plain-English message.
"""


class PseudocodeError(Exception):
    """A user-facing error: a syntax problem, an undeclared identifier,
    a type mismatch, a runtime failure, etc. `line` is 1-based."""

    def __init__(self, line: int, message: str):
        self.line = line
        self.message = message
        super().__init__(f"Line {line}: {message}")

    def to_dict(self) -> dict:
        """Serialisable form for the web frontend (Milestone 12)."""
        return {"line": self.line, "message": self.message}
