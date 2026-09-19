"""
Parser for the IGCSE Pseudocode Compiler (Milestone 2).

Grammar implemented so far (EBNF-ish; NEWLINE separates statements):

    program     := (statement? NEWLINE)* EOF
    statement   := declare_stmt | constant_stmt | input_stmt | output_stmt
                 | if_stmt | case_stmt | for_stmt | repeat_stmt | while_stmt
                 | assignment_stmt

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
Procedures/functions (Milestone 8) and file handling (Milestone 9)
remain unimplemented.
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
}


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0
        # Kinds of block (IF / FOR / WHILE / REPEAT / CASE) whose body is being
        # parsed right now, outermost first.
        self._open_blocks: list[TokenType] = []

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
        statements = self._block(stop_types=frozenset())
        return ast.Program(statements)

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
        if tok.type == TokenType.IDENTIFIER:
            return self._assignment_statement()
        unsupported = {
            TokenType.OPENFILE: "File handling statements are not supported yet.",
            TokenType.READFILE: "File handling statements are not supported yet.",
            TokenType.WRITEFILE: "File handling statements are not supported yet.",
            TokenType.CLOSEFILE: "File handling statements are not supported yet.",
            TokenType.PROCEDURE: "Procedures are not supported yet.",
            TokenType.ENDPROCEDURE: "Procedures are not supported yet.",
            TokenType.FUNCTION: "Functions are not supported yet.",
            TokenType.ENDFUNCTION: "Functions are not supported yet.",
            TokenType.CALL: "User-defined procedure/function calls are not supported yet.",
            TokenType.RETURN: "RETURN is only valid inside a user-defined function, which is not supported yet.",
        }
        if tok.type in unsupported:
            raise PseudocodeError(tok.line, unsupported[tok.type])

        unexpected_endings = {
            TokenType.ELSE: "ELSE does not have a matching IF statement.",
            TokenType.ENDIF: "ENDIF does not have a matching IF statement.",
            TokenType.NEXT: "NEXT does not have a matching FOR statement.",
            TokenType.UNTIL: "UNTIL does not have a matching REPEAT statement.",
            TokenType.ENDWHILE: "ENDWHILE does not have a matching WHILE statement.",
            TokenType.ENDCASE: "ENDCASE does not have a matching CASE OF statement.",
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

    def _array_declare_tail(self, names, line):
        """The ARRAY[...] OF <type> part of a DECLARE, after the
        identifier list and ':' have already been consumed.
        (FR-8.1, FR-8.3)"""
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
                f"but found '{type_tok.lexeme or type_tok.type.name}'.",
            )
        self._advance()
        return ast.ArrayDeclare(names, dimensions, _DATA_TYPE_TOKENS[type_tok.type], line)

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
            target = ast.Identifier(name_tok.lexeme, name_tok.line)
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
            return ast.UnaryOp("-", operand, tok.line)
        if tok.type in _LITERAL_TYPE_OF:
            self._advance()
            return ast.Literal(tok.value, _LITERAL_TYPE_OF[tok.type], tok.line)
        raise PseudocodeError(
            tok.line,
            f"Expected a literal value for this CASE branch, but found {describe_token(tok)}.",
        )

    def _assignment_statement(self):
        name_tok = self._advance()  # consume IDENTIFIER
        if self._check(TokenType.LBRACKET):
            target = self._finish_index(name_tok)  # <identifier>[<index>...] <- <value>, FR-8.2/FR-8.4
        else:
            target = ast.Identifier(name_tok.lexeme, name_tok.line)
        self._expect(TokenType.ASSIGN, "Expected '<-' to assign a value")
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
            left = ast.BinaryOp("OR", left, right, tok.line)
        return left

    def _and_expr(self):
        left = self._not_expr()
        while self._check(TokenType.AND):
            tok = self._advance()
            right = self._not_expr()
            left = ast.BinaryOp("AND", left, right, tok.line)
        return left

    def _not_expr(self):
        if self._check(TokenType.NOT):
            tok = self._advance()
            operand = self._not_expr()
            return ast.UnaryOp("NOT", operand, tok.line)
        return self._relational()

    def _relational(self):
        left = self._additive()
        tok = self._peek()
        if tok.type in _RELATIONAL_TOKENS:
            self._advance()
            right = self._additive()
            left = ast.BinaryOp(_RELATIONAL_TOKENS[tok.type], left, right, tok.line)
        return left

    def _additive(self):
        left = self._term()
        while self._peek().type in (TokenType.PLUS, TokenType.MINUS):
            op_tok = self._advance()
            right = self._term()
            left = ast.BinaryOp(op_tok.lexeme, left, right, op_tok.line)
        return left

    def _term(self):
        left = self._unary()
        while self._peek().type in (TokenType.MULTIPLY, TokenType.DIVIDE):
            op_tok = self._advance()
            right = self._unary()
            left = ast.BinaryOp(op_tok.lexeme, left, right, op_tok.line)
        return left

    def _unary(self):
        if self._check(TokenType.MINUS):
            op_tok = self._advance()
            operand = self._unary()
            return ast.UnaryOp("-", operand, op_tok.line)
        return self._power()

    def _power(self):
        base = self._primary()
        if self._check(TokenType.POWER):
            op_tok = self._advance()
            exponent = self._unary()  # right-associative
            return ast.BinaryOp("^", base, exponent, op_tok.line)
        return base

    def _primary(self):
        tok = self._peek()

        if tok.type in _LITERAL_TYPE_OF:
            self._advance()
            return ast.Literal(tok.value, _LITERAL_TYPE_OF[tok.type], tok.line)

        if tok.type == TokenType.LPAREN:
            self._advance()
            expr = self._expression()
            self._expect(TokenType.RPAREN, "Expected ')' to close this expression")
            return expr

        if tok.type == TokenType.IDENTIFIER:
            self._advance()
            if self._check(TokenType.LPAREN):
                return self._finish_call(tok)
            if self._check(TokenType.LBRACKET):
                return self._finish_index(tok)
            return ast.Identifier(tok.lexeme, tok.line)

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
        self._expect(TokenType.RPAREN, f"Expected ')' to close the call to {name_tok.lexeme}")
        return ast.Call(name_tok.lexeme, args, name_tok.line)

    def _finish_index(self, name_tok: Token):
        self._advance()  # consume '['
        indices = [self._expression()]
        while self._match(TokenType.COMMA):
            indices.append(self._expression())
        self._expect(TokenType.RBRACKET, f"Expected ']' to close the index into {name_tok.lexeme}")
        return ast.Index(name_tok.lexeme, indices, name_tok.line)


def parse(tokens: list[Token]) -> ast.Program:
    """Convenience wrapper: parse a full token list into a Program."""
    return Parser(tokens).parse()