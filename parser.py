"""Hand-written recursive-descent parser for OWL. Builds the AST defined in
ast_nodes.py by peeking at and eating tokens from the flat token stream
produced by lexer.py. One function per grammar rule in grammar.ebnf."""

from lexer import TokenKind
from ast_nodes import (
    ProgramNode, BlockNode, VarDeclNode, AssignNode, IfNode,
    IntLiteralNode, BoolLiteralNode, IdentNode, UnaryExprNode, BinaryExprNode,
    ParamNode, FunctionDeclNode, ReturnNode, ExprStmtNode, CallNode,
)

TYPE_NAMES = {
    TokenKind.TYPE_I32: "i32",
    TokenKind.TYPE_I64: "i64",
    TokenKind.KW_ULT: "bool",
}

ADD_OPS = {
    TokenKind.PLUS: ("ADD", False),
    TokenKind.MINUS: ("SUB", False),
    TokenKind.PLUS_CHECKED: ("ADD", True),
    TokenKind.MINUS_CHECKED: ("SUB", True),
}

MUL_OPS = {
    TokenKind.STAR: ("MUL", False),
    TokenKind.SLASH: ("DIV", False),
    TokenKind.STAR_CHECKED: ("MUL", True),
    TokenKind.SLASH_CHECKED: ("DIV", True),
}

EQ_OPS = {
    TokenKind.EQ: "EQ",
    TokenKind.NEQ: "NEQ",
}


class ParseError(Exception):
    def __init__(self, line, col, message):
        super().__init__(message)
        self.line = line
        self.col = col
        self.message = message


def _found_text(tok):
    return "end of file" if tok.kind == TokenKind.EOF else repr(tok.text)


class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def _peek(self):
        return self.tokens[self.pos]

    def _advance(self):
        tok = self.tokens[self.pos]
        if self.pos < len(self.tokens) - 1:
            self.pos += 1
        return tok

    def _eat(self, kind, what):
        tok = self._peek()
        if tok.kind != kind:
            raise ParseError(tok.line, tok.col, f"expected {what} but found {_found_text(tok)}")
        return self._advance()

    def _peek_kind(self, offset):
        idx = min(self.pos + offset, len(self.tokens) - 1)
        return self.tokens[idx].kind

    def _parse_type(self):
        type_tok = self._peek()
        if type_tok.kind not in TYPE_NAMES:
            raise ParseError(type_tok.line, type_tok.col, f"expected a type but found {_found_text(type_tok)}")
        self._advance()
        return TYPE_NAMES[type_tok.kind]

    # program = { topItem } ;
    def parse_program(self):
        items = []
        while self._peek().kind != TokenKind.EOF:
            items.append(self._parse_top_item())
        return ProgramNode(items)

    # topItem = functionDecl | statement ;
    def _parse_top_item(self):
        if self._peek().kind == TokenKind.KW_ABILITY:
            return self._parse_function_decl()
        return self._parse_statement()

    # functionDecl = "ability" identifier "(" [ param { "," param } ] ")" "->" typeName block ;
    def _parse_function_decl(self):
        ability_tok = self._eat(TokenKind.KW_ABILITY, "'ability'")
        name_tok = self._eat(TokenKind.IDENT, "function name")
        self._eat(TokenKind.LPAREN, "'('")
        params = []
        if self._peek().kind != TokenKind.RPAREN:
            params.append(self._parse_param())
            while self._peek().kind == TokenKind.COMMA:
                self._advance()
                params.append(self._parse_param())
        self._eat(TokenKind.RPAREN, "')'")
        self._eat(TokenKind.ARROW, "'->'")
        result_type = self._parse_type()
        body = self._parse_block()
        return FunctionDeclNode(name_tok.text, params, result_type, body, ability_tok.line, ability_tok.col)

    # param = identifier ":" typeName ;
    def _parse_param(self):
        name_tok = self._eat(TokenKind.IDENT, "parameter name")
        self._eat(TokenKind.COLON, "':'")
        param_type = self._parse_type()
        return ParamNode(name_tok.text, param_type, name_tok.line, name_tok.col)

    # statement = varDecl | assignStmt | ifStmt | returnStmt | callStmt ;
    def _parse_statement(self):
        tok = self._peek()
        if tok.kind in (TokenKind.KW_FLEX, TokenKind.DECL_CONST):
            return self._parse_var_decl()
        if tok.kind == TokenKind.IDENT and self._peek_kind(1) == TokenKind.LPAREN:
            return self._parse_call_stmt()
        if tok.kind == TokenKind.IDENT:
            return self._parse_assign()
        if tok.kind == TokenKind.KW_IF:
            return self._parse_if()
        if tok.kind == TokenKind.KW_GG:
            return self._parse_return()
        if tok.kind == TokenKind.KW_ABILITY:
            raise ParseError(tok.line, tok.col, "functions can only be declared at the top level")
        raise ParseError(tok.line, tok.col, f"expected statement but found {_found_text(tok)}")

    # returnStmt = "gg" expression ";" ;
    def _parse_return(self):
        gg_tok = self._eat(TokenKind.KW_GG, "'gg'")
        value = self._parse_expression()
        self._eat(TokenKind.SEMI, "';'")
        return ReturnNode(value, gg_tok.line, gg_tok.col)

    # callStmt = call ";" ;
    def _parse_call_stmt(self):
        call = self._parse_call()
        self._eat(TokenKind.SEMI, "';'")
        return ExprStmtNode(call, call.line, call.col)

    # call = identifier "(" [ expression { "," expression } ] ")" ;
    def _parse_call(self):
        name_tok = self._eat(TokenKind.IDENT, "function name")
        self._eat(TokenKind.LPAREN, "'('")
        args = []
        if self._peek().kind != TokenKind.RPAREN:
            args.append(self._parse_expression())
            while self._peek().kind == TokenKind.COMMA:
                self._advance()
                args.append(self._parse_expression())
        self._eat(TokenKind.RPAREN, "')'")
        return CallNode(name_tok.text, args, name_tok.line, name_tok.col)

    # varDecl = declKeyword identifier ":" typeName "=" expression ";" ;
    def _parse_var_decl(self):
        decl_tok = self._advance()
        mutable = decl_tok.kind == TokenKind.KW_FLEX
        name_tok = self._eat(TokenKind.IDENT, "identifier")
        self._eat(TokenKind.COLON, "':'")
        var_type = self._parse_type()
        self._eat(TokenKind.ASSIGN, "'='")
        value = self._parse_expression()
        self._eat(TokenKind.SEMI, "';'")
        return VarDeclNode(mutable, name_tok.text, var_type, value, decl_tok.line, decl_tok.col)

    # assignStmt = identifier "=" expression ";" ;
    def _parse_assign(self):
        name_tok = self._eat(TokenKind.IDENT, "identifier")
        self._eat(TokenKind.ASSIGN, "'='")
        value = self._parse_expression()
        self._eat(TokenKind.SEMI, "';'")
        return AssignNode(name_tok.text, value, name_tok.line, name_tok.col)

    # ifStmt = "if" expression block [ "else" block ] ;
    def _parse_if(self):
        if_tok = self._eat(TokenKind.KW_IF, "'if'")
        condition = self._parse_expression()
        then_block = self._parse_block()
        else_block = None
        if self._peek().kind == TokenKind.KW_ELSE:
            self._advance()
            else_block = self._parse_block()
        return IfNode(condition, then_block, else_block, if_tok.line, if_tok.col)

    # block = "{" statement { statement } "}" ;
    def _parse_block(self):
        brace_tok = self._eat(TokenKind.LBRACE, "'{'")
        statements = []
        while self._peek().kind not in (TokenKind.RBRACE, TokenKind.EOF):
            statements.append(self._parse_statement())
        if self._peek().kind == TokenKind.EOF:
            eof_tok = self._peek()
            raise ParseError(eof_tok.line, eof_tok.col, "expected '}' but found end of file")
        if not statements:
            raise ParseError(brace_tok.line, brace_tok.col, "a block must contain at least one statement")
        self._eat(TokenKind.RBRACE, "'}'")
        return BlockNode(statements, brace_tok.line, brace_tok.col)

    # expression = equality ;
    def _parse_expression(self):
        return self._parse_equality()

    # equality = additive [ ( "🆚" | "🚫" ) additive ] ;
    def _parse_equality(self):
        left = self._parse_additive()
        if self._peek().kind in EQ_OPS:
            op_tok = self._advance()
            right = self._parse_additive()
            left = BinaryExprNode(EQ_OPS[op_tok.kind], False, left, right, op_tok.line, op_tok.col)
        return left

    # additive = multiplicative { ( "+" | "-" | "+!" | "-!" ) multiplicative } ;
    def _parse_additive(self):
        left = self._parse_multiplicative()
        while self._peek().kind in ADD_OPS:
            op_tok = self._advance()
            right = self._parse_multiplicative()
            op, checked = ADD_OPS[op_tok.kind]
            left = BinaryExprNode(op, checked, left, right, op_tok.line, op_tok.col)
        return left

    # multiplicative = unary { ( "*" | "/" | "*!" | "/!" ) unary } ;
    def _parse_multiplicative(self):
        left = self._parse_unary()
        while self._peek().kind in MUL_OPS:
            op_tok = self._advance()
            right = self._parse_unary()
            op, checked = MUL_OPS[op_tok.kind]
            left = BinaryExprNode(op, checked, left, right, op_tok.line, op_tok.col)
        return left

    # unary = "-" unary | primary ;
    def _parse_unary(self):
        if self._peek().kind == TokenKind.MINUS:
            op_tok = self._advance()
            operand = self._parse_unary()
            return UnaryExprNode("NEG", operand, op_tok.line, op_tok.col)
        return self._parse_primary()

    # primary = intLiteral | boolLiteral | call | identifier | "(" expression ")" ;
    def _parse_primary(self):
        tok = self._peek()
        if tok.kind == TokenKind.INT:
            self._advance()
            return IntLiteralNode(int(tok.text), tok.line, tok.col)
        if tok.kind == TokenKind.TRUE:
            self._advance()
            return BoolLiteralNode(True, tok.line, tok.col)
        if tok.kind == TokenKind.FALSE:
            self._advance()
            return BoolLiteralNode(False, tok.line, tok.col)
        if tok.kind == TokenKind.IDENT and self._peek_kind(1) == TokenKind.LPAREN:
            return self._parse_call()
        if tok.kind == TokenKind.IDENT:
            self._advance()
            return IdentNode(tok.text, tok.line, tok.col)
        if tok.kind == TokenKind.LPAREN:
            self._advance()
            expr = self._parse_expression()
            self._eat(TokenKind.RPAREN, "')'")
            return expr
        raise ParseError(tok.line, tok.col, f"expected an expression but found {_found_text(tok)}")
