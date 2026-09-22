"""
Token definitions for the IGCSE Pseudocode lexer.

Covers the keyword set listed in SRS 2.5, the five data types (FR-2.x),
literals, operators (FR-5.x), and punctuation used throughout the
reference syntax guide.
"""

from enum import Enum, auto
from dataclasses import dataclass


class TokenType(Enum):
    # Literals
    INTEGER_LITERAL = auto()
    REAL_LITERAL = auto()
    CHAR_LITERAL = auto()
    STRING_LITERAL = auto()
    BOOLEAN_LITERAL = auto()      # TRUE / FALSE

    # Identifiers
    IDENTIFIER = auto()

    # Data type keywords (FR-2.x)
    INTEGER = auto()
    REAL = auto()
    CHAR = auto()
    STRING = auto()
    BOOLEAN = auto()

    # Declarations (FR-3.x)
    DECLARE = auto()
    CONSTANT = auto()

    # I/O (FR-4.x)
    INPUT = auto()
    OUTPUT = auto()

    # Selection (FR-7.x)
    IF = auto()
    THEN = auto()
    ELSE = auto()
    ENDIF = auto()
    CASE = auto()
    OF = auto()
    OTHERWISE = auto()
    ENDCASE = auto()

    # Iteration (FR-6.x)
    FOR = auto()
    TO = auto()
    STEP = auto()
    NEXT = auto()
    REPEAT = auto()
    UNTIL = auto()
    WHILE = auto()
    DO = auto()
    ENDWHILE = auto()

    # Arrays (FR-8.x)
    ARRAY = auto()

    # File handling (FR-9.x)
    OPENFILE = auto()
    READFILE = auto()
    WRITEFILE = auto()
    CLOSEFILE = auto()
    READ = auto()
    WRITE = auto()

    # Procedures / functions (FR-10.x)
    PROCEDURE = auto()
    ENDPROCEDURE = auto()
    FUNCTION = auto()
    RETURNS = auto()
    ENDFUNCTION = auto()
    CALL = auto()
    RETURN = auto()

    # Boolean logic (extension beyond the reference syntax guide, added on request)
    AND = auto()
    OR = auto()
    NOT = auto()

    # Operators
    ASSIGN = auto()        # <- or unicode arrow
    PLUS = auto()
    MINUS = auto()
    MULTIPLY = auto()
    DIVIDE = auto()
    POWER = auto()         # ^
    EQUAL = auto()         # =
    LESS_THAN = auto()     # <
    LESS_EQUAL = auto()    # <=
    GREATER_THAN = auto()  # >
    GREATER_EQUAL = auto()  # >=
    NOT_EQUAL = auto()     # <>

    # Punctuation
    LPAREN = auto()
    RPAREN = auto()
    LBRACKET = auto()
    RBRACKET = auto()
    COMMA = auto()
    COLON = auto()

    # Structural
    NEWLINE = auto()
    EOF = auto()


# Reserved words -> TokenType. Matching is case-sensitive and exact,
# per the reference syntax guide (keywords are always upper case).
KEYWORDS = {
    "DECLARE": TokenType.DECLARE,
    "CONSTANT": TokenType.CONSTANT,
    "INPUT": TokenType.INPUT,
    "OUTPUT": TokenType.OUTPUT,
    "IF": TokenType.IF,
    "THEN": TokenType.THEN,
    "ELSE": TokenType.ELSE,
    "ENDIF": TokenType.ENDIF,
    "CASE": TokenType.CASE,
    "OF": TokenType.OF,
    "OTHERWISE": TokenType.OTHERWISE,
    "ENDCASE": TokenType.ENDCASE,
    "FOR": TokenType.FOR,
    "TO": TokenType.TO,
    "STEP": TokenType.STEP,
    "NEXT": TokenType.NEXT,
    "REPEAT": TokenType.REPEAT,
    "UNTIL": TokenType.UNTIL,
    "WHILE": TokenType.WHILE,
    "DO": TokenType.DO,
    "ENDWHILE": TokenType.ENDWHILE,
    "ARRAY": TokenType.ARRAY,
    "OPENFILE": TokenType.OPENFILE,
    "READFILE": TokenType.READFILE,
    "WRITEFILE": TokenType.WRITEFILE,
    "CLOSEFILE": TokenType.CLOSEFILE,
    "READ": TokenType.READ,
    "WRITE": TokenType.WRITE,
    "PROCEDURE": TokenType.PROCEDURE,
    "ENDPROCEDURE": TokenType.ENDPROCEDURE,
    "FUNCTION": TokenType.FUNCTION,
    "RETURNS": TokenType.RETURNS,
    "ENDFUNCTION": TokenType.ENDFUNCTION,
    "CALL": TokenType.CALL,
    "RETURN": TokenType.RETURN,
    "AND": TokenType.AND,
    "OR": TokenType.OR,
    "NOT": TokenType.NOT,
    "INTEGER": TokenType.INTEGER,
    "REAL": TokenType.REAL,
    "CHAR": TokenType.CHAR,
    "STRING": TokenType.STRING,
    "BOOLEAN": TokenType.BOOLEAN,
    "TRUE": TokenType.BOOLEAN_LITERAL,
    "FALSE": TokenType.BOOLEAN_LITERAL,
}

# Library / built-in function names (FR-4.3, FR-4.4, FR-5.2, FR-5.3, FR-5.5-5.8).
# These are NOT lexed as separate keywords — they are ordinary identifiers
# that the parser/interpreter recognises as built-in calls. Listed here so
# other modules have a single source of truth.
BUILTIN_FUNCTIONS = {
    "ROUND", "RANDOM", "DIV", "MOD",
    "LENGTH", "LCASE", "UCASE", "SUBSTRING",
}


@dataclass
class Token:
    type: TokenType
    lexeme: str      # raw source text for this token
    value: object     # literal value where applicable (int/float/str/bool), else None
    line: int         # 1-based line number, for FR-11.1 style error reporting
    column: int = 1        # 1-based column of the token's first character
    end_column: int = 1    # 1-based column of the token's LAST character (inclusive)

    def __repr__(self) -> str:
        if self.value is not None:
            return f"Token({self.type.name}, {self.value!r}, line={self.line}, col={self.column})"
        return f"Token({self.type.name}, {self.lexeme!r}, line={self.line}, col={self.column})"