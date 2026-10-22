"""Hand-written, byte-level lexer for the OWL (Overwatch Workshop Language) language."""

from enum import Enum, auto


class TokenKind(Enum):
    INT = auto()
    IDENT = auto()
    KW_FLEX = auto()
    KW_IF = auto()
    KW_ELSE = auto()
    KW_ULT = auto()       # "ult" - the boolean type keyword
    TYPE_I32 = auto()      # 🔫 - i32
    TYPE_I64 = auto()      # 🚀 - i64
    DECL_CONST = auto()    # 🔒 - immutable variable declaration
    TRUE = auto()          # 🔥
    FALSE = auto()         # 💤
    EQ = auto()            # 🆚  ==
    NEQ = auto()           # 🚫  !=
    COLON = auto()
    SEMI = auto()
    LBRACE = auto()
    RBRACE = auto()
    LPAREN = auto()
    RPAREN = auto()
    ASSIGN = auto()
    PLUS = auto()
    MINUS = auto()
    STAR = auto()
    SLASH = auto()
    PLUS_CHECKED = auto()   # +!
    MINUS_CHECKED = auto()  # -!
    STAR_CHECKED = auto()   # *!
    SLASH_CHECKED = auto()  # /!
    EOF = auto()


KEYWORDS = {
    "flex": TokenKind.KW_FLEX,
    "if": TokenKind.KW_IF,
    "else": TokenKind.KW_ELSE,
    "ult": TokenKind.KW_ULT,
}

# Overwatch-flavored keywords/operators written as emoji. Each one is a fixed
# 4-byte UTF-8 sequence: the lexer reads bytes, so an emoji keyword is just
# another byte sequence the state machine recognizes, the same way it
# recognizes "flex" or "if".
EMOJI_TOKENS = {
    "🔫".encode("utf-8"): (TokenKind.TYPE_I32, "🔫"),
    "🚀".encode("utf-8"): (TokenKind.TYPE_I64, "🚀"),
    "🔒".encode("utf-8"): (TokenKind.DECL_CONST, "🔒"),
    "🔥".encode("utf-8"): (TokenKind.TRUE, "🔥"),
    "💤".encode("utf-8"): (TokenKind.FALSE, "💤"),
    "🆚".encode("utf-8"): (TokenKind.EQ, "🆚"),
    "🚫".encode("utf-8"): (TokenKind.NEQ, "🚫"),
}

SINGLE_BYTE_TOKENS = {
    0x3A: TokenKind.COLON,   # :
    0x3B: TokenKind.SEMI,    # ;
    0x7B: TokenKind.LBRACE,  # {
    0x7D: TokenKind.RBRACE,  # }
    0x28: TokenKind.LPAREN,  # (
    0x29: TokenKind.RPAREN,  # )
    0x3D: TokenKind.ASSIGN,  # =
}

# Arithmetic operators that come in an "unchecked" (wrapping) flavor and a
# "checked" (overflow-checked) flavor spelled with a trailing '!'.
CHECKABLE_OPS = {
    0x2B: (TokenKind.PLUS, TokenKind.PLUS_CHECKED, "+"),   # +  / +!
    0x2D: (TokenKind.MINUS, TokenKind.MINUS_CHECKED, "-"), # -  / -!
    0x2A: (TokenKind.STAR, TokenKind.STAR_CHECKED, "*"),   # *  / *!
    0x2F: (TokenKind.SLASH, TokenKind.SLASH_CHECKED, "/"), # /  / /!
}


class Token:
    __slots__ = ("kind", "text", "line", "col")

    def __init__(self, kind, text, line, col):
        self.kind = kind
        self.text = text
        self.line = line
        self.col = col

    def __repr__(self):
        return f"Token({self.kind.name}, {self.text!r}, {self.line}:{self.col})"


class LexError(Exception):
    def __init__(self, line, col, message):
        super().__init__(message)
        self.line = line
        self.col = col
        self.message = message


def _is_digit(b):
    return b is not None and 0x30 <= b <= 0x39


def _is_alpha(b):
    return b is not None and ((0x41 <= b <= 0x5A) or (0x61 <= b <= 0x7A) or b == 0x5F)


def _is_alnum(b):
    return _is_alpha(b) or _is_digit(b)


class Lexer:
    """Scans raw source bytes into a flat list of tokens using a hand-written
    state machine. No regular expressions, no split(), no generator."""

    def __init__(self, source: bytes):
        self.src = source
        self.pos = 0
        self.line = 1
        self.col = 1

    def _peek_byte(self, offset=0):
        idx = self.pos + offset
        if idx >= len(self.src):
            return None
        return self.src[idx]

    def _advance(self, n=1):
        for _ in range(n):
            if self.pos >= len(self.src):
                return
            b = self.src[self.pos]
            self.pos += 1
            if b == 0x0A:  # '\n'
                self.line += 1
                self.col = 1
            else:
                self.col += 1

    def _skip_ignored(self):
        while True:
            b = self._peek_byte()
            if b in (0x20, 0x09, 0x0D, 0x0A):  # space, tab, CR, LF
                self._advance()
                continue
            if b == 0x2F and self._peek_byte(1) == 0x2F:  # line comment "//"
                while self._peek_byte() is not None and self._peek_byte() != 0x0A:
                    self._advance()
                continue
            break

    def tokenize(self):
        tokens = []
        while True:
            tok = self._next_token()
            tokens.append(tok)
            if tok.kind == TokenKind.EOF:
                break
        return tokens

    def _next_token(self):
        self._skip_ignored()
        line, col = self.line, self.col
        b = self._peek_byte()

        if b is None:
            return Token(TokenKind.EOF, "", line, col)

        if _is_digit(b):
            return self._lex_int(line, col)

        if _is_alpha(b):
            return self._lex_ident(line, col)

        if b >= 0xF0:
            return self._lex_emoji(line, col)

        if b in SINGLE_BYTE_TOKENS:
            self._advance()
            return Token(SINGLE_BYTE_TOKENS[b], chr(b), line, col)

        if b in CHECKABLE_OPS:
            base_kind, checked_kind, text = CHECKABLE_OPS[b]
            self._advance()
            if self._peek_byte() == 0x21:  # '!'
                self._advance()
                return Token(checked_kind, text + "!", line, col)
            return Token(base_kind, text, line, col)

        raise LexError(line, col, f"unexpected byte 0x{b:02x}")

    def _lex_int(self, line, col):
        start = self.pos
        while _is_digit(self._peek_byte()):
            self._advance()
        text = self.src[start:self.pos].decode("ascii")
        return Token(TokenKind.INT, text, line, col)

    def _lex_ident(self, line, col):
        start = self.pos
        while _is_alnum(self._peek_byte()):
            self._advance()
        text = self.src[start:self.pos].decode("ascii")
        kind = KEYWORDS.get(text, TokenKind.IDENT)
        return Token(kind, text, line, col)

    def _lex_emoji(self, line, col):
        chunk = self.src[self.pos:self.pos + 4]
        if len(chunk) == 4 and chunk in EMOJI_TOKENS:
            kind, text = EMOJI_TOKENS[chunk]
            self._advance(4)
            return Token(kind, text, line, col)
        raise LexError(line, col, f"unexpected symbol {chunk!r}")
