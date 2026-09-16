"""
IGCSE Pseudocode Compiler — core engine package.

Modules:
    tokens      Token type definitions and keyword table.
    errors      Shared error type used by lexer, parser, and interpreter.
    lexer       Converts pseudocode source text into a token stream.
    parser      (Milestone 2+) Converts tokens into an AST.
    interpreter (Milestone 3+) Walks the AST and executes it.
"""

__version__ = "0.1.0"
