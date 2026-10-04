"""
Parser for the IGCSE Pseudocode Compiler (Milestone 2, extended through
Milestone 8).

Grammar implemented so far (EBNF-ish; NEWLINE separates statements):

    program     := (procedure_decl | function_decl)* (statement? NEWLINE)* EOF  -- FR-10.1, FR-10.3
    statement   := declare_stmt | constant_stmt | input_stmt | output_stmt
                 | if_stmt | case_stmt | for_stmt | repeat_stmt | while_stmt
                 | call_stmt | return_stmt | assignment_stmt
                 | openfile_stmt | readfile_stmt | writefile_stmt | closefile_stmt

    declare_stmt   := DECLARE IDENTIFIER (',' IDENTIFIER)* COLON
                       ( data_type | array_type )
    array_type     := ARRAY '[' bound_pair (',' bound_pair)? ']' OF data_type  -- FR-8.1, FR-8.3
    bound_pair     := expression ':' expression
    constant_stmt  := CONSTANT IDENTIFIER ASSIGN expression
    input_stmt     := INPUT ( IDENTIFIER | IDENTIFIER '[' arglist ']' )      -- FR-4.1, FR-8.2/FR-8.4
    output_stmt    := OUTPUT expression ( ',' expression )*
    if_stmt        := IF expression THEN block ( ELSE block )? ENDIF        -- FR-7.1, FR-7.2
    case_stmt      := CASE OF IDENTIFIER (case_value COLON statement)*
                       ( OTHERWISE statement )? ENDCASE                     -- FR-7.3, FR-7.4
    case_value     := '-'? literal
    for_stmt       := FOR IDENTIFIER ASSIGN expression TO expression
                       ( STEP expression )? block NEXT IDENTIFIER           -- FR-6.1, FR-6.2, FR-6.3
    repeat_stmt    := REPEAT block UNTIL expression                         -- FR-6.4
    while_stmt     := WHILE expression DO block ENDWHILE                    -- FR-6.5
    assignment_stmt:= ( IDENTIFIER | IDENTIFIER '[' arglist ']' ) ASSIGN expression  -- FR-8.2, FR-8.4
    data_type      := INTEGER | REAL | CHAR | STRING | BOOLEAN

    procedure_decl := PROCEDURE IDENTIFIER ( '(' param_list? ')' )?
                       block ENDPROCEDURE                                   -- FR-10.1
    function_decl  := FUNCTION IDENTIFIER ( '(' param_list? ')' )?
                       RETURNS data_type block ENDFUNCTION                  -- FR-10.3
    param_list     := param ( ',' param )*
    param          := IDENTIFIER ':' data_type                          -- FR-10.1, FR-10.3
    call_stmt      := CALL IDENTIFIER ( '(' arglist? ')' )?                 -- FR-10.2
    return_stmt    := RETURN expression                                    -- FR-10.3, only inside a FUNCTION

    openfile_stmt  := OPENFILE expression FOR file_mode                    -- FR-9.1
    file_mode      := READ | WRITE
    readfile_stmt  := READFILE expression ',' IDENTIFIER                   -- FR-9.2
    writefile_stmt := WRITEFILE expression ',' expression                  -- FR-9.3
    closefile_stmt := CLOSEFILE expression                                 -- FR-9.4

    expression  := or_expr                                -- extension: AND/OR/NOT (added on request)
    or_expr     := and_expr ( OR and_expr )*
    and_expr    := not_expr ( AND not_expr )*
    not_expr    := NOT not_expr | relational
    relational  := additive ( relop additive )?          -- FR-5.4, non-chaining
    additive    := term ( ('+' | '-') term )*             -- FR-5.1
    term        := unary ( ('*' | '/') unary )*           -- FR-5.1
    unary       := '-' unary | power
    power       := primary ( '^' unary )?                 -- right-associative
    primary     := INTEGER_LITERAL | REAL_LITERAL | CHAR_LITERAL
                 | STRING_LITERAL | BOOLEAN_LITERAL
                 | IDENTIFIER ( '(' arglist? ')' | '[' arglist ']' )?
                 | '(' expression ')'
    arglist     := expression ( ',' expression )*

Arrays are limited to 1 or 2 dimensions (FR-8.1, FR-8.3); a bound can
be any expression (e.g. a CONSTANT), evaluated when the DECLARE runs.

PROCEDURE/FUNCTION definitions are recognised ONLY in the leading run of
the program, before the first ordinary statement (SRS 3.10: "always
defined at the top of the program") -- see `parse()`. A PROCEDURE or
FUNCTION token reached anywhere else (mid-program, or nested inside
another block/definition) is reported as a placement error by
`_statement()` rather than being parsed as a nested definition, since
nesting isn't part of the grammar either. `Call` (the expression node)
is reused for user-defined FUNCTION calls, exactly as it already is for
built-ins -- only the interpreter needs to tell them apart.

A PROCEDURE/FUNCTION parameter is always scalar (`param := IDENTIFIER ':'
data_type`, matching the SRS's literal `<par n> : <data type>` grammar
exactly) -- an array cannot be passed as a parameter. Arrays remain
usable only via DECLARE, element assignment/read, and INPUT into an
element (FR-8.x); a whole array can't cross a PROCEDURE/FUNCTION
boundary in either direction.

File handling (FR-9.1 - FR-9.4, Milestone 9): the `<file identifier>`
in every SRS example is a quoted STRING literal, but the grammar above
parses it as a general `expression` -- so a STRING/CHAR variable works
too, evaluated at runtime by the interpreter (see ast_nodes.py's
module docstring and Interpreter._eval_file_identifier). READFILE's
target, per the SRS's own grammar, is a plain IDENTIFIER only -- not
an array element.
"""

from .tokens import Token, TokenType
from .errors import PseudocodeError, describe_token
from . import ast_nodes as ast

_DATA_TYPE_TOKENS = {
    TokenType.INTEGER: "INTEGER",
    TokenType.REAL: "REAL",
    TokenType.CHAR: "CHAR",
    TokenType.STRING: "STRING",
    TokenType.BOOLEAN: "BOOLEAN",
}

_RELATIONAL_TOKENS = {
    TokenType.EQUAL: "=",
    TokenType.LESS_THAN: "<",
    TokenType.LESS_EQUAL: "<=",
    TokenType.GREATER_THAN: ">",
    TokenType.GREATER_EQUAL: ">=",
    TokenType.NOT_EQUAL: "<>",
}

_LITERAL_TYPE_OF = {
    TokenType.INTEGER_LITERAL: "INTEGER",
    TokenType.REAL_LITERAL: "REAL",
    TokenType.CHAR_LITERAL: "CHAR",
    TokenType.STRING_LITERAL: "STRING",
    TokenType.BOOLEAN_LITERAL: "BOOLEAN",
}

# Each closing keyword, mapped to the kind of block it belongs to. When a block
# reaches the closing keyword of a DIFFERENT, enclosing block, the block it is
# in must itself be missing its own terminator (FR-11.1) -- it is not a stray
# keyword. See Parser._at_outer_closer.
_STATEMENT_KEYWORDS = frozenset(
    {
        TokenType.DECLARE,
        TokenType.CONSTANT,
        TokenType.INPUT,
        TokenType.OUTPUT,
        TokenType.IF,
        TokenType.CASE,
        TokenType.FOR,
        TokenType.REPEAT,
        TokenType.WHILE,
        TokenType.CALL,
        TokenType.RETURN,
        TokenType.OPENFILE,
        TokenType.READFILE,
        TokenType.WRITEFILE,
        TokenType.CLOSEFILE,
    }
)

_CLOSER_BELONGS_TO = {
    TokenType.ELSE: TokenType.IF,
    TokenType.ENDIF: TokenType.IF,
    TokenType.NEXT: TokenType.FOR,
    TokenType.UNTIL: TokenType.REPEAT,
    TokenType.ENDWHILE: TokenType.WHILE,
    TokenType.OTHERWISE: TokenType.CASE,
    TokenType.ENDCASE: TokenType.CASE,
    TokenType.ENDPROCEDURE: TokenType.PROCEDURE,
    TokenType.ENDFUNCTION: TokenType.FUNCTION,
}


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0
        # Kinds of block (IF / FOR / WHILE / REPEAT / CASE / PROCEDURE /
        # FUNCTION) whose body is being parsed right now, outermost first.
        self._open_blocks: list[TokenType] = []
        # PROCEDURE/FUNCTION currently being parsed, outermost first (in
        # practice at most one deep, since definitions can't nest -- see
        # the module docstring). Lets a RETURN statement (FR-10.3) check
        # it's inside a FUNCTION, not a PROCEDURE or the main program.
        self._callable_context: list[TokenType] = []

    # ---- token helpers -----------------------------------------------

    def _peek(self, offset: int = 0) -> Token:
        i = min(self.pos + offset, len(self.tokens) - 1)
        return self.tokens[i]

    def _advance(self) -> Token:
        tok = self.tokens[self.pos]
        if tok.type != TokenType.EOF:
            self.pos += 1
        return tok

    def _check(self, type_: TokenType) -> bool:
        return self._peek().type == type_

    def _match(self, *types: TokenType) -> bool:
        if self._peek().type in types:
            self._advance()
            return True
        return False

    def _expect(self, type_: TokenType, message: str) -> Token:
        if self._check(type_):
            return self._advance()
        found = self._peek()
        raise PseudocodeError(found.line, f"{message} (found {describe_token(found)}).")

    # ---- program / statements ------------------------------------------

    def parse(self) -> ast.Program:
        # PROCEDURE/FUNCTION definitions (FR-10.1, FR-10.3) are only
        # recognised in this leading run, before the first ordinary
        # statement (SRS 3.10). Once any other statement has been seen --
        # including one before the very first definition -- a later
        # PROCEDURE/FUNCTION token is a placement error, reported by
        # _statement() below rather than parsed as a definition.
        self._skip_newlines()
        declarations = []
        while self._peek().type in (TokenType.PROCEDURE, TokenType.FUNCTION):
            if self._peek().type == TokenType.PROCEDURE:
                declarations.append(self._procedure_decl())
            else:
                declarations.append(self._function_decl())
            self._end_of_statement()
            self._skip_newlines()
        statements = self._block(stop_types=frozenset())
        return ast.Program(declarations + statements)

    def _skip_newlines(self):
        while self._match(TokenType.NEWLINE):
            pass

    def _block(self, stop_types: frozenset) -> list:
        """Parse statements until EOF, a token in `stop_types`, or the closing
        keyword of an enclosing block is seen (the stop token itself is left
        unconsumed, so the caller can report which terminator is missing)."""
        statements = []
        self._skip_newlines()
        while (
            not self._check(TokenType.EOF)
            and self._peek().type not in stop_types
            and not self._at_outer_closer()
        ):
            statements.append(self._statement())
            self._end_of_statement()
            self._skip_newlines()
        return statements

    def _at_outer_closer(self) -> bool:
        """True when the next token closes a block that is currently open
        (e.g. NEXT while a FOR is open).

        Reached from inside a *nested* block, that means the nested block ran
        into its parent's terminator without ever being closed itself. Stopping
        here lets that nested statement report "this IF is missing its ENDIF"
        instead of blaming the parent's terminator ("NEXT has no matching FOR").
        A closer with no matching open block is a genuinely stray keyword and
        still falls through to _statement()'s "does not have a matching ..."."""
        opener = _CLOSER_BELONGS_TO.get(self._peek().type)
        return opener is not None and opener in self._open_blocks

    def _case_body_has_ended(self) -> bool:
        """True when the next token starts an ordinary statement rather than a
        CASE branch ("<literal> : ..."), i.e. the CASE is missing its ENDCASE.
        A bad branch value such as "Total : ..." is left for _case_value() to
        report as before."""
        tok = self._peek()
        if tok.type in _STATEMENT_KEYWORDS:
            return True
        return tok.type == TokenType.IDENTIFIER and self._peek(1).type != TokenType.COLON

    def _missing_end(self, line: int, construct: str, terminator: str) -> PseudocodeError:
        """FR-11.1: a missing terminator, reported at the line of the opening
        keyword, plus where the parser noticed the problem (if not at the end)."""
        message = f"This {construct} statement is missing its matching {terminator}."
        found = self._peek()
        if found.type != TokenType.EOF:
            message += (
                f" The program reached {describe_token(found)} on line {found.line}"
                " before this was closed."
            )
        return PseudocodeError(line, message)

    def _end_of_statement(self):
        """A statement must be followed by a newline or EOF."""
        if self._check(TokenType.EOF):
            return
        self._expect(TokenType.NEWLINE, "Expected the end of this line")

    def _statement(self):
        tok = self._peek()
        if tok.type == TokenType.DECLARE:
            return self._declare_statement()
        if tok.type == TokenType.CONSTANT:
            return self._constant_statement()
        if tok.type == TokenType.INPUT:
            return self._input_statement()
        if tok.type == TokenType.OUTPUT:
            return self._output_statement()
        if tok.type == TokenType.IF:
            return self._if_statement()
        if tok.type == TokenType.CASE:
            return self._case_statement()
        if tok.type == TokenType.FOR:
            return self._for_statement()
        if tok.type == TokenType.REPEAT:
            return self._repeat_statement()
        if tok.type == TokenType.WHILE:
            return self._while_statement()
        if tok.type == TokenType.CALL:
            return self._call_statement()
        if tok.type == TokenType.RETURN:
            return self._return_statement()
        if tok.type == TokenType.OPENFILE:
            return self._openfile_statement()
        if tok.type == TokenType.READFILE:
            return self._readfile_statement()
        if tok.type == TokenType.WRITEFILE:
            return self._writefile_statement()
        if tok.type == TokenType.CLOSEFILE:
            return self._closefile_statement()
        if tok.type == TokenType.IDENTIFIER:
            return self._assignment_statement()

        if tok.type in (TokenType.PROCEDURE, TokenType.FUNCTION):
            # Reached from inside _statement() rather than the leading scan
            # in parse(), which means either an ordinary statement already
            # came before it, or it's nested inside another block/definition
            # -- neither is allowed (SRS 3.10, FR-10.1/FR-10.3).
            keyword = "PROCEDURE" if tok.type == TokenType.PROCEDURE else "FUNCTION"
            raise PseudocodeError(
                tok.line,
                f"A {keyword} definition must be at the top of the program, before any other "
                f"statement, and cannot be nested inside another PROCEDURE or FUNCTION.",
            )

        unexpected_endings = {
            TokenType.ELSE: "ELSE does not have a matching IF statement.",
            TokenType.ENDIF: "ENDIF does not have a matching IF statement.",
            TokenType.NEXT: "NEXT does not have a matching FOR statement.",
            TokenType.UNTIL: "UNTIL does not have a matching REPEAT statement.",
            TokenType.ENDWHILE: "ENDWHILE does not have a matching WHILE statement.",
            TokenType.ENDCASE: "ENDCASE does not have a matching CASE OF statement.",
            TokenType.ENDPROCEDURE: "ENDPROCEDURE does not have a matching PROCEDURE statement.",
            TokenType.ENDFUNCTION: "ENDFUNCTION does not have a matching FUNCTION statement.",
        }
        if tok.type in unexpected_endings:
            raise PseudocodeError(tok.line, unexpected_endings[tok.type])

        raise PseudocodeError(
            tok.line,
            f"Expected a statement here, but found {describe_token(tok)}.",
        )

    def _declare_statement(self):
        line = self._advance().line  # consume DECLARE
        names = [self._expect(TokenType.IDENTIFIER, "Expected an identifier after DECLARE").lexeme]
        while self._match(TokenType.COMMA):
            names.append(self._expect(TokenType.IDENTIFIER, "Expected an identifier after ','").lexeme)
        self._expect(TokenType.COLON, "Expected ':' after the identifier(s) in a DECLARE statement")

        if self._check(TokenType.ARRAY):
            return self._array_declare_tail(names, line)

        type_tok = self._peek()
        if type_tok.type not in _DATA_TYPE_TOKENS:
            raise PseudocodeError(
                type_tok.line,
                f"Expected a data type (INTEGER, REAL, CHAR, STRING, or BOOLEAN), "
                f"but found '{type_tok.lexeme or type_tok.type.name}'.",
            )
        self._advance()
        return ast.Declare(names, _DATA_TYPE_TOKENS[type_tok.type], line)

    def _array_type_tail(self, line):
        """The ARRAY[...] OF <type> part of a DECLARE (FR-8.1, FR-8.3).
        Assumes ARRAY is the next token. Returns (dimensions, element_type).
        (PROCEDURE/FUNCTION parameters never reach this -- see _param,
        which rejects ARRAY there directly.)"""
        self._advance()  # consume ARRAY
        self._expect(TokenType.LBRACKET, "Expected '[' after ARRAY")
        dimensions = [self._array_bound_pair()]
        while self._match(TokenType.COMMA):
            dimensions.append(self._array_bound_pair())
        if len(dimensions) > 2:
            raise PseudocodeError(line, "Arrays can have at most 2 dimensions (1D or 2D).")
        self._expect(TokenType.RBRACKET, "Expected ']' to close the array's bounds")
        self._expect(TokenType.OF, "Expected OF after the array's bounds")

        type_tok = self._peek()
        if type_tok.type not in _DATA_TYPE_TOKENS:
            raise PseudocodeError(
                type_tok.line,
                f"Expected a data type (INTEGER, REAL, CHAR, STRING, or BOOLEAN), "
                f"but found {describe_token(type_tok)}.",
            )
        self._advance()
        return dimensions, _DATA_TYPE_TOKENS[type_tok.type]

    def _array_declare_tail(self, names, line):
        """The ARRAY[...] OF <type> part of a DECLARE, after the
        identifier list and ':' have already been consumed.
        (FR-8.1, FR-8.3)"""
        dimensions, element_type = self._array_type_tail(line)
        return ast.ArrayDeclare(names, dimensions, element_type, line)

    def _array_bound_pair(self):
        lower = self._expression()
        self._expect(TokenType.COLON, "Expected ':' between an array's lower and upper bound")
        upper = self._expression()
        return (lower, upper)

    def _constant_statement(self):
        line = self._advance().line  # consume CONSTANT
        name_tok = self._expect(TokenType.IDENTIFIER, "Expected an identifier after CONSTANT")
        self._expect(TokenType.ASSIGN, "Expected '<-' after the identifier in a CONSTANT statement")
        value = self._expression()
        return ast.Constant(name_tok.lexeme, value, line)

    def _input_statement(self):
        line = self._advance().line  # consume INPUT
        name_tok = self._expect(TokenType.IDENTIFIER, "Expected an identifier after INPUT")
        if self._check(TokenType.LBRACKET):
            target = self._finish_index(name_tok)  # INPUT <identifier>[<index>...]
        else:
            target = ast.Identifier(name_tok.lexeme, name_tok.line, name_tok.column, name_tok.end_column)
        return ast.Input(target, line)

    def _output_statement(self):
        line = self._advance().line  # consume OUTPUT
        values = [self._expression()]
        while self._match(TokenType.COMMA):
            values.append(self._expression())
        return ast.Output(values, line)

    def _for_statement(self):
        """FOR <identifier> <- <start> TO <finish> [STEP <step>] ... NEXT <identifier>
        (FR-6.1, FR-6.2, FR-6.3)."""
        line = self._advance().line  # consume FOR
        var_tok = self._expect(TokenType.IDENTIFIER, "Expected the loop variable after FOR")
        self._expect(TokenType.ASSIGN, "Expected '<-' after the loop variable in a FOR statement")
        start = self._expression()
        self._expect(TokenType.TO, "Expected TO after the FOR loop's start value")
        finish = self._expression()

        step = None
        if self._check(TokenType.STEP):
            self._advance()
            step = self._expression()

        self._open_blocks.append(TokenType.FOR)
        body = self._block(frozenset({TokenType.NEXT}))
        if not self._check(TokenType.NEXT):
            raise self._missing_end(line, "FOR", "NEXT")
        self._open_blocks.pop()
        self._advance()  # consume NEXT
        next_name_tok = self._expect(TokenType.IDENTIFIER, "Expected the loop variable's name after NEXT")
        if next_name_tok.lexeme != var_tok.lexeme:
            raise PseudocodeError(
                next_name_tok.line,
                f"NEXT {next_name_tok.lexeme} doesn't match the loop variable "
                f"'{var_tok.lexeme}' from the FOR statement.",
            )
        return ast.ForLoop(var_tok.lexeme, start, finish, step, body, line)

    def _repeat_statement(self):
        """REPEAT ... UNTIL <condition>   (FR-6.4)"""
        line = self._advance().line  # consume REPEAT
        self._open_blocks.append(TokenType.REPEAT)
        body = self._block(frozenset({TokenType.UNTIL}))
        if not self._check(TokenType.UNTIL):
            raise self._missing_end(line, "REPEAT", "UNTIL")
        self._open_blocks.pop()
        self._advance()  # consume UNTIL
        condition = self._expression()
        return ast.RepeatLoop(body, condition, line)

    def _while_statement(self):
        """WHILE <condition> DO ... ENDWHILE   (FR-6.5)"""
        line = self._advance().line  # consume WHILE
        condition = self._expression()
        self._skip_newlines()  # DO is conventionally same-line, but allow either
        self._expect(TokenType.DO, "Expected DO after the WHILE condition")
        self._open_blocks.append(TokenType.WHILE)
        body = self._block(frozenset({TokenType.ENDWHILE}))
        if not self._check(TokenType.ENDWHILE):
            raise self._missing_end(line, "WHILE", "ENDWHILE")
        self._open_blocks.pop()
        self._advance()  # consume ENDWHILE
        return ast.WhileLoop(condition, body, line)

    # ---- procedures / functions (FR-10.1 - FR-10.4) ---------------------

    def _param_list(self):
        """<param> (',' <param>)*, the contents of a PROCEDURE/FUNCTION's
        parameter parentheses (already known to be non-empty by the caller)."""
        params = [self._param()]
        while self._match(TokenType.COMMA):
            params.append(self._param())
        return params

    def _param(self):
        """<identifier> ':' <data type> -- one parameter (FR-10.1, FR-10.3).
        A parameter is always scalar; an array cannot be passed as a
        PROCEDURE/FUNCTION parameter (see this module's docstring)."""
        name_tok = self._expect(TokenType.IDENTIFIER, "Expected a parameter name")
        self._expect(TokenType.COLON, "Expected ':' after the parameter name")
        if self._check(TokenType.ARRAY):
            raise PseudocodeError(
                name_tok.line,
                f"Parameter '{name_tok.lexeme}' can't be declared as an ARRAY -- an array can't be "
                f"passed as a PROCEDURE/FUNCTION parameter. Pass individual elements (e.g. "
                f"MyArray[1]) as separate parameters instead.",
            )
        type_tok = self._peek()
        if type_tok.type not in _DATA_TYPE_TOKENS:
            raise PseudocodeError(
                type_tok.line,
                f"Expected a data type (INTEGER, REAL, CHAR, STRING, or BOOLEAN) for "
                f"parameter '{name_tok.lexeme}', but found {describe_token(type_tok)}.",
            )
        self._advance()
        return ast.Param(name_tok.lexeme, _DATA_TYPE_TOKENS[type_tok.type])

    def _parse_param_clause(self, owner_name: str):
        """The optional '(' <param_list> ')' shared by PROCEDURE and
        FUNCTION headers. Returns [] when there is no parameter list at all."""
        if not self._match(TokenType.LPAREN):
            return []
        params = [] if self._check(TokenType.RPAREN) else self._param_list()
        self._expect(TokenType.RPAREN, "Expected ')' to close the parameter list")
        seen = set()
        for p in params:
            if p.name in seen:
                raise PseudocodeError(
                    self._peek().line,
                    f"Parameter '{p.name}' is repeated in the parameter list for '{owner_name}'.",
                )
            seen.add(p.name)
        return params

    def _procedure_decl(self):
        """PROCEDURE <identifier> [(<params>)] ... ENDPROCEDURE   (FR-10.1)"""
        line = self._advance().line  # consume PROCEDURE
        name_tok = self._expect(TokenType.IDENTIFIER, "Expected a name after PROCEDURE")
        params = self._parse_param_clause(name_tok.lexeme)
        self._open_blocks.append(TokenType.PROCEDURE)
        self._callable_context.append(TokenType.PROCEDURE)
        body = self._block(frozenset({TokenType.ENDPROCEDURE}))
        if not self._check(TokenType.ENDPROCEDURE):
            raise self._missing_end(line, "PROCEDURE", "ENDPROCEDURE")
        self._callable_context.pop()
        self._open_blocks.pop()
        self._advance()  # consume ENDPROCEDURE
        return ast.ProcedureDecl(name_tok.lexeme, params, body, line)

    def _function_decl(self):
        """FUNCTION <identifier> [(<params>)] RETURNS <data type> ...
        ENDFUNCTION   (FR-10.3)"""
        line = self._advance().line  # consume FUNCTION
        name_tok = self._expect(TokenType.IDENTIFIER, "Expected a name after FUNCTION")
        params = self._parse_param_clause(name_tok.lexeme)
        self._expect(TokenType.RETURNS, "Expected RETURNS after the function's name/parameters")
        type_tok = self._peek()
        if type_tok.type not in _DATA_TYPE_TOKENS:
            raise PseudocodeError(
                type_tok.line,
                f"Expected a data type (INTEGER, REAL, CHAR, STRING, or BOOLEAN) after RETURNS, "
                f"but found {describe_token(type_tok)}.",
            )
        self._advance()
        return_type = _DATA_TYPE_TOKENS[type_tok.type]
        self._open_blocks.append(TokenType.FUNCTION)
        self._callable_context.append(TokenType.FUNCTION)
        body = self._block(frozenset({TokenType.ENDFUNCTION}))
        if not self._check(TokenType.ENDFUNCTION):
            raise self._missing_end(line, "FUNCTION", "ENDFUNCTION")
        self._callable_context.pop()
        self._open_blocks.pop()
        self._advance()  # consume ENDFUNCTION
        return ast.FunctionDecl(name_tok.lexeme, params, return_type, body, line)

    def _call_statement(self):
        """CALL <identifier> or CALL <identifier>(<val1>, ...)   (FR-10.2)"""
        line = self._advance().line  # consume CALL
        name_tok = self._expect(TokenType.IDENTIFIER, "Expected a procedure name after CALL")
        args = []
        if self._match(TokenType.LPAREN):
            if not self._check(TokenType.RPAREN):
                args.append(self._expression())
                while self._match(TokenType.COMMA):
                    args.append(self._expression())
            self._expect(TokenType.RPAREN, f"Expected ')' to close the call to {name_tok.lexeme}")
        return ast.ProcedureCall(name_tok.lexeme, args, line)

    def _return_statement(self):
        """RETURN <expression>   (FR-10.3) -- only valid inside a FUNCTION;
        checked structurally here rather than left to the interpreter, since
        it's purely a question of where in the source this token sits."""
        line = self._advance().line  # consume RETURN
        if not self._callable_context:
            raise PseudocodeError(line, "RETURN is only valid inside a user-defined FUNCTION.")
        if self._callable_context[-1] != TokenType.FUNCTION:
            raise PseudocodeError(
                line,
                "RETURN cannot be used inside a PROCEDURE, only inside a FUNCTION -- "
                "a PROCEDURE does not return a value.",
            )
        value = self._expression()
        return ast.Return(value, line)

    # ---- file handling (FR-9.1 - FR-9.4) --------------------------------

    def _openfile_statement(self):
        """OPENFILE <file identifier> FOR <file mode>   (FR-9.1)"""
        line = self._advance().line  # consume OPENFILE
        file_expr = self._expression()
        self._expect(TokenType.FOR, "Expected FOR after the file identifier in an OPENFILE statement")
        mode_tok = self._peek()
        if mode_tok.type == TokenType.READ:
            mode = "READ"
        elif mode_tok.type == TokenType.WRITE:
            mode = "WRITE"
        else:
            raise PseudocodeError(
                mode_tok.line,
                f"Expected READ or WRITE after FOR in an OPENFILE statement, "
                f"but found {describe_token(mode_tok)}.",
            )
        self._advance()  # consume READ/WRITE
        return ast.OpenFile(file_expr, mode, line)

    def _readfile_statement(self):
        """READFILE <file identifier>, <identifier>   (FR-9.2)"""
        line = self._advance().line  # consume READFILE
        file_expr = self._expression()
        self._expect(TokenType.COMMA, "Expected ',' after the file identifier in a READFILE statement")
        name_tok = self._expect(TokenType.IDENTIFIER, "Expected an identifier after ',' in a READFILE statement")
        target = ast.Identifier(name_tok.lexeme, name_tok.line, name_tok.column, name_tok.end_column)
        return ast.ReadFile(file_expr, target, line)

    def _writefile_statement(self):
        """WRITEFILE <file identifier>, <value>   (FR-9.3)"""
        line = self._advance().line  # consume WRITEFILE
        file_expr = self._expression()
        self._expect(TokenType.COMMA, "Expected ',' after the file identifier in a WRITEFILE statement")
        value = self._expression()
        return ast.WriteFile(file_expr, value, line)

    def _closefile_statement(self):
        """CLOSEFILE <file identifier>   (FR-9.4)"""
        line = self._advance().line  # consume CLOSEFILE
        file_expr = self._expression()
        return ast.CloseFile(file_expr, line)

    def _if_statement(self):
        """IF <condition> [NEWLINE] THEN [NEWLINE] <block> [ELSE [NEWLINE] <block>] ENDIF   (FR-7.1, FR-7.2)"""
        line = self._advance().line  # consume IF
        condition = self._expression()
        self._skip_newlines()  # THEN is conventionally on its own line, but same-line is fine too
        self._expect(TokenType.THEN, "Expected THEN after the IF condition")
        self._open_blocks.append(TokenType.IF)
        then_body = self._block(frozenset({TokenType.ELSE, TokenType.ENDIF}))

        else_body = []
        if self._check(TokenType.ELSE):
            self._advance()
            else_body = self._block(frozenset({TokenType.ENDIF}))
            if self._check(TokenType.ELSE):
                found_line = self._peek().line
                if self._open_blocks.count(TokenType.IF) > 1:
                    # Nested IF: this ELSE most likely belongs to the enclosing
                    # IF, which means this IF is missing its ENDIF.
                    raise PseudocodeError(
                        line,
                        "This IF statement is missing its matching ENDIF, or has more than "
                        f"one ELSE. The program reached 'ELSE' on line {found_line} "
                        "before this was closed.",
                    )
                raise PseudocodeError(
                    found_line,
                    "This IF statement already has an ELSE; it can only have one.",
                )

        if not self._check(TokenType.ENDIF):
            raise self._missing_end(line, "IF", "ENDIF")
        self._open_blocks.pop()
        self._advance()  # consume ENDIF
        return ast.If(condition, then_body, else_body, line)

    def _case_statement(self):
        """CASE OF <identifier> (<value> : <statement>)* [OTHERWISE <statement>] ENDCASE   (FR-7.3, FR-7.4)"""
        line = self._advance().line  # consume CASE
        self._expect(TokenType.OF, "Expected OF after CASE")
        subject_tok = self._expect(TokenType.IDENTIFIER, "Expected an identifier after CASE OF")
        if self._check(TokenType.LBRACKET):
            # CASE OF takes a plain variable (FR-7.3). Without this check the
            # '[' is read as the start of a branch value, which points the
            # student at the wrong place.
            raise PseudocodeError(
                subject_tok.line,
                f"CASE OF needs a plain variable, but '{subject_tok.lexeme}[...]' is an array "
                f"element. Copy it into a variable first (for example Choice <- "
                f"{subject_tok.lexeme}[1]) and use CASE OF Choice.",
            )

        branches = []
        otherwise_stmt = None
        self._open_blocks.append(TokenType.CASE)
        self._skip_newlines()
        while (
            not self._check(TokenType.EOF)
            and self._peek().type not in (TokenType.OTHERWISE, TokenType.ENDCASE)
            and not self._at_outer_closer()
        ):
            if self._case_body_has_ended():
                raise self._missing_end(line, "CASE OF", "ENDCASE")
            value_node = self._case_value()
            self._expect(TokenType.COLON, "Expected ':' after the CASE value")
            branch_stmt = self._statement()
            branches.append((value_node, branch_stmt))
            self._end_of_statement()
            self._skip_newlines()

        if self._check(TokenType.OTHERWISE):
            self._advance()
            otherwise_stmt = self._statement()
            self._end_of_statement()
            self._skip_newlines()

        if not self._check(TokenType.ENDCASE):
            raise self._missing_end(line, "CASE OF", "ENDCASE")
        self._open_blocks.pop()
        self._advance()  # consume ENDCASE
        return ast.Case(subject_tok.lexeme, branches, otherwise_stmt, line)

    def _case_value(self):
        """A CASE branch's value must be a literal (optionally negative),
        not a general expression — the syntax guide only shows literals."""
        tok = self._peek()
        if tok.type == TokenType.MINUS:
            self._advance()
            operand = self._case_value()
            return ast.UnaryOp("-", operand, tok.line, tok.column, operand.end_column)
        if tok.type in _LITERAL_TYPE_OF:
            self._advance()
            return ast.Literal(tok.value, _LITERAL_TYPE_OF[tok.type], tok.line, tok.column, tok.end_column)
        raise PseudocodeError(
            tok.line,
            f"Expected a literal value for this CASE branch, but found {describe_token(tok)}.",
        )

    def _assignment_statement(self):
        name_tok = self._advance()  # consume IDENTIFIER
        if self._check(TokenType.LBRACKET):
            target = self._finish_index(name_tok)  # <identifier>[<index>...] <- <value>, FR-8.2/FR-8.4
        else:
            target = ast.Identifier(name_tok.lexeme, name_tok.line, name_tok.column, name_tok.end_column)
        self._expect(TokenType.ASSIGN, "Expected '<-' to assign a value")
        if self._check(TokenType.LBRACKET):
            # "MyArray <- [1, 2, 3]" is not part of the language: an array is
            # filled one element at a time, through its index.
            raise PseudocodeError(
                self._peek().line,
                f"A list of values can't be assigned to '{name_tok.lexeme}' in one step. "
                f"An array is filled one element at a time using an index, "
                f"e.g. {name_tok.lexeme}[1] <- value.",
            )
        value = self._expression()
        return ast.Assignment(target, value, name_tok.line)

    # ---- expressions (precedence climbing) -----------------------------
    #
    # Boolean connectives (extension beyond the reference syntax guide,
    # added on request) sit above relational comparisons:
    #   expression := or_expr
    #   or_expr     := and_expr ( OR and_expr )*
    #   and_expr    := not_expr ( AND not_expr )*
    #   not_expr    := NOT not_expr | relational
    # so "A = 1 AND (B = 2 OR C <> 3)" groups as
    # (A = 1) AND ((B = 2) OR (C <> 3)), and parentheses override this
    # exactly as they do for arithmetic. AND/OR evaluate both sides
    # (no short-circuiting) — see Interpreter._eval_logical.

    def _expression(self):
        return self._or_expr()

    def _or_expr(self):
        left = self._and_expr()
        while self._check(TokenType.OR):
            tok = self._advance()
            right = self._and_expr()
            left = ast.BinaryOp("OR", left, right, tok.line, left.column, right.end_column)
        return left

    def _and_expr(self):
        left = self._not_expr()
        while self._check(TokenType.AND):
            tok = self._advance()
            right = self._not_expr()
            left = ast.BinaryOp("AND", left, right, tok.line, left.column, right.end_column)
        return left

    def _not_expr(self):
        if self._check(TokenType.NOT):
            tok = self._advance()
            operand = self._not_expr()
            return ast.UnaryOp("NOT", operand, tok.line, tok.column, operand.end_column)
        return self._relational()

    def _relational(self):
        left = self._additive()
        tok = self._peek()
        if tok.type in _RELATIONAL_TOKENS:
            self._advance()
            right = self._additive()
            left = ast.BinaryOp(
                _RELATIONAL_TOKENS[tok.type], left, right, tok.line, left.column, right.end_column
            )
        return left

    def _additive(self):
        left = self._term()
        while self._peek().type in (TokenType.PLUS, TokenType.MINUS):
            op_tok = self._advance()
            right = self._term()
            left = ast.BinaryOp(op_tok.lexeme, left, right, op_tok.line, left.column, right.end_column)
        return left

    def _term(self):
        left = self._unary()
        while self._peek().type in (TokenType.MULTIPLY, TokenType.DIVIDE):
            op_tok = self._advance()
            right = self._unary()
            left = ast.BinaryOp(op_tok.lexeme, left, right, op_tok.line, left.column, right.end_column)
        return left

    def _unary(self):
        if self._check(TokenType.MINUS):
            op_tok = self._advance()
            operand = self._unary()
            return ast.UnaryOp("-", operand, op_tok.line, op_tok.column, operand.end_column)
        return self._power()

    def _power(self):
        base = self._primary()
        if self._check(TokenType.POWER):
            op_tok = self._advance()
            exponent = self._unary()  # right-associative
            return ast.BinaryOp("^", base, exponent, op_tok.line, base.column, exponent.end_column)
        return base

    def _primary(self):
        tok = self._peek()

        if tok.type in _LITERAL_TYPE_OF:
            self._advance()
            return ast.Literal(tok.value, _LITERAL_TYPE_OF[tok.type], tok.line, tok.column, tok.end_column)

        if tok.type == TokenType.LPAREN:
            lparen = self._advance()
            expr = self._expression()
            rparen = self._expect(TokenType.RPAREN, "Expected ')' to close this expression")
            # Widen the span to include the parentheses themselves, so an
            # error blamed on this (now-grouped) expression underlines the
            # parens too, e.g. "10 / (2 - 2)" rather than just "2 - 2".
            expr.column = lparen.column
            expr.end_column = rparen.end_column
            return expr

        if tok.type == TokenType.IDENTIFIER:
            self._advance()
            if self._check(TokenType.LPAREN):
                return self._finish_call(tok)
            if self._check(TokenType.LBRACKET):
                return self._finish_index(tok)
            return ast.Identifier(tok.lexeme, tok.line, tok.column, tok.end_column)

        if tok.type == TokenType.LBRACKET:
            raise PseudocodeError(
                tok.line,
                "A list such as [1, 2, 3] isn't supported. To keep several values, declare an "
                "array and use its elements one at a time through an index, e.g. MyArray[1].",
            )

        raise PseudocodeError(
            tok.line,
            f"Expected a value or expression here, but found {describe_token(tok)}.",
        )

    def _finish_call(self, name_tok: Token):
        self._advance()  # consume '('
        args = []
        if not self._check(TokenType.RPAREN):
            args.append(self._expression())
            while self._match(TokenType.COMMA):
                args.append(self._expression())
        rparen = self._expect(TokenType.RPAREN, f"Expected ')' to close the call to {name_tok.lexeme}")
        return ast.Call(name_tok.lexeme, args, name_tok.line, name_tok.column, rparen.end_column)

    def _finish_index(self, name_tok: Token):
        self._advance()  # consume '['
        indices = [self._expression()]
        while self._match(TokenType.COMMA):
            indices.append(self._expression())
        rbracket = self._expect(TokenType.RBRACKET, f"Expected ']' to close the index into {name_tok.lexeme}")
        return ast.Index(name_tok.lexeme, indices, name_tok.line, name_tok.column, rbracket.end_column)


def parse(tokens: list[Token]) -> ast.Program:
    """Convenience wrapper: parse a full token list into a Program."""
    parser = Parser(tokens)
    try:
        return parser.parse()
    except RecursionError:
        # Each level of brackets or nested blocks costs several Python stack
        # frames; report running out of them as an ordinary error.
        raise PseudocodeError(
            parser._peek().line,
            "This part of the program is nested too deeply (too many brackets or "
            "blocks inside one another).",
        ) from None