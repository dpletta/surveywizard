"""Tokenizer + parser + AST for REDCap branching-logic expressions.

The REDCap mini-DSL grammar (subset):

    expr       := or_expr
    or_expr    := and_expr ('or' and_expr)*
    and_expr   := cmp_expr ('and' cmp_expr)*
    cmp_expr   := add_expr (cmp_op add_expr)?
    cmp_op     := '=' | '<>' | '<' | '>' | '<=' | '>='
    add_expr   := mul_expr (('+' | '-') mul_expr)*
    mul_expr   := unary ('*' / unary)*
    unary      := '-' unary | atom
    atom       := field_ref | literal | func_call | '(' expr ')'
    field_ref  := '[' IDENT ']' ( '[' IDENT ']' )? ( '(' code ')' )?
    literal    := STRING | NUMBER
    func_call  := IDENT '(' arg_list? ')'
    arg_list   := expr (',' expr)*

A successful parse returns a ``Node`` tree; ``render(node)`` produces the
canonical string form. Round-trip ``render(parse(s))`` must be idempotent
on valid REDCap logic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from surveywizard.errors import ExpressionError

# ---------- tokenizer ----------


class TokenKind(StrEnum):
    LBRACKET = "LBRACKET"  # [
    RBRACKET = "RBRACKET"  # ]
    LPAREN = "LPAREN"  # (
    RPAREN = "RPAREN"  # )
    COMMA = "COMMA"
    STRING = "STRING"
    NUMBER = "NUMBER"
    IDENT = "IDENT"
    EQ = "EQ"  # =
    NE = "NE"  # <>
    LT = "LT"  # <
    LE = "LE"  # <=
    GT = "GT"  # >
    GE = "GE"  # >=
    AND = "AND"  # and
    OR = "OR"  # or
    NOT = "NOT"  # not (rare but supported)
    PLUS = "PLUS"
    MINUS = "MINUS"
    STAR = "STAR"
    SLASH = "SLASH"
    EOF = "EOF"


@dataclass(frozen=True)
class Token:
    kind: TokenKind
    value: str
    pos: int


_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_\-]*")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_KEYWORDS: dict[str, TokenKind] = {
    "and": TokenKind.AND,
    "or": TokenKind.OR,
    "not": TokenKind.NOT,
}


def tokenize(source: str) -> list[Token]:
    """Return the token list for a REDCap logic expression."""
    tokens: list[Token] = []
    i = 0
    n = len(source)
    while i < n:
        ch = source[i]
        if ch.isspace():
            i += 1
            continue
        if ch == "[":
            tokens.append(Token(TokenKind.LBRACKET, "[", i))
            i += 1
            continue
        if ch == "]":
            tokens.append(Token(TokenKind.RBRACKET, "]", i))
            i += 1
            continue
        if ch == "(":
            tokens.append(Token(TokenKind.LPAREN, "(", i))
            i += 1
            continue
        if ch == ")":
            tokens.append(Token(TokenKind.RPAREN, ")", i))
            i += 1
            continue
        if ch == ",":
            tokens.append(Token(TokenKind.COMMA, ",", i))
            i += 1
            continue
        if ch == "'" or ch == '"':
            quote = ch
            start = i
            i += 1
            buf: list[str] = []
            while i < n and source[i] != quote:
                if source[i] == "\\" and i + 1 < n:
                    buf.append(source[i + 1])
                    i += 2
                else:
                    buf.append(source[i])
                    i += 1
            if i >= n:
                raise ExpressionError(f"Unterminated string literal at pos {start}")
            i += 1  # closing quote
            tokens.append(Token(TokenKind.STRING, "".join(buf), start))
            continue
        # multi-char operators first
        if ch == "<" and i + 1 < n and source[i + 1] == "=":
            tokens.append(Token(TokenKind.LE, "<=", i))
            i += 2
            continue
        if ch == ">" and i + 1 < n and source[i + 1] == "=":
            tokens.append(Token(TokenKind.GE, ">=", i))
            i += 2
            continue
        if ch == "<" and i + 1 < n and source[i + 1] == ">":
            tokens.append(Token(TokenKind.NE, "<>", i))
            i += 2
            continue
        if ch == "!" and i + 1 < n and source[i + 1] == "=":
            tokens.append(Token(TokenKind.NE, "!=", i))
            i += 2
            continue
        if ch == "=":
            tokens.append(Token(TokenKind.EQ, "=", i))
            i += 1
            continue
        if ch == "<":
            tokens.append(Token(TokenKind.LT, "<", i))
            i += 1
            continue
        if ch == ">":
            tokens.append(Token(TokenKind.GT, ">", i))
            i += 1
            continue
        if ch == "+":
            tokens.append(Token(TokenKind.PLUS, "+", i))
            i += 1
            continue
        if ch == "-":
            tokens.append(Token(TokenKind.MINUS, "-", i))
            i += 1
            continue
        if ch == "*":
            tokens.append(Token(TokenKind.STAR, "*", i))
            i += 1
            continue
        if ch == "/":
            tokens.append(Token(TokenKind.SLASH, "/", i))
            i += 1
            continue
        if m := _NUMBER_RE.match(source, i):
            tokens.append(Token(TokenKind.NUMBER, m.group(0), i))
            i = m.end()
            continue
        if m := _IDENT_RE.match(source, i):
            value = m.group(0)
            kind = _KEYWORDS.get(value.lower(), TokenKind.IDENT)
            tokens.append(Token(kind, value, i))
            i = m.end()
            continue
        raise ExpressionError(f"Unexpected character {ch!r} at pos {i}")
    tokens.append(Token(TokenKind.EOF, "", n))
    return tokens


# ---------- AST ----------


@dataclass
class Node:
    """Marker base for all AST nodes."""

    kind: str = ""


@dataclass
class FieldRef(Node):
    name: str = ""
    event: str | None = None
    option_code: str | None = None
    kind: str = "FieldRef"


@dataclass
class Literal(Node):
    value: str = ""
    literal_kind: str = "string"  # 'string' or 'number'
    kind: str = "Literal"


@dataclass
class BinaryOp(Node):
    """Comparison or arithmetic op: = <> < > <= >= + - * /."""

    op: str = ""
    left: Node | None = None
    right: Node | None = None
    kind: str = "BinaryOp"


@dataclass
class LogicalOp(Node):
    """and / or."""

    op: str = ""
    left: Node | None = None
    right: Node | None = None
    kind: str = "LogicalOp"


@dataclass
class UnaryOp(Node):
    op: str = ""
    operand: Node | None = None
    kind: str = "UnaryOp"


@dataclass
class FunctionCall(Node):
    name: str = ""
    args: list[Node] = field(default_factory=list)
    kind: str = "FunctionCall"


# ---------- parser ----------


class _Parser:
    """Recursive-descent parser with precedence climbing."""

    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.pos = 0

    def peek(self, offset: int = 0) -> Token:
        idx = self.pos + offset
        if idx < 0 or idx >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[idx]

    def consume(self, kind: TokenKind | None = None) -> Token:
        tok = self.tokens[self.pos]
        if kind is not None and tok.kind != kind:
            raise ExpressionError(
                f"Expected {kind} at pos {tok.pos}, got {tok.kind} ({tok.value!r})"
            )
        self.pos += 1
        return tok

    def match(self, *kinds: TokenKind) -> Token | None:
        if self.tokens[self.pos].kind in kinds:
            return self.consume()
        return None

    def parse(self) -> Node:
        node = self.parse_or()
        if self.peek().kind != TokenKind.EOF:
            leftover = self.peek()
            raise ExpressionError(f"Trailing tokens at pos {leftover.pos}: {leftover.value!r}")
        return node

    def parse_or(self) -> Node:
        left = self.parse_and()
        while self.peek().kind == TokenKind.OR:
            op_tok = self.consume()
            right = self.parse_and()
            left = LogicalOp(op=op_tok.value.lower(), left=left, right=right)
        return left

    def parse_and(self) -> Node:
        left = self.parse_cmp()
        while self.peek().kind == TokenKind.AND:
            op_tok = self.consume()
            right = self.parse_cmp()
            left = LogicalOp(op=op_tok.value.lower(), left=left, right=right)
        return left

    _CMP_TOKENS = {
        TokenKind.EQ,
        TokenKind.NE,
        TokenKind.LT,
        TokenKind.LE,
        TokenKind.GT,
        TokenKind.GE,
    }
    _CMP_OP_TEXT = {
        TokenKind.EQ: "=",
        TokenKind.NE: "<>",
        TokenKind.LT: "<",
        TokenKind.LE: "<=",
        TokenKind.GT: ">",
        TokenKind.GE: ">=",
    }

    def parse_cmp(self) -> Node:
        left = self.parse_add()
        while self.peek().kind in self._CMP_TOKENS:
            op_tok = self.consume()
            right = self.parse_add()
            left = BinaryOp(op=self._CMP_OP_TEXT[op_tok.kind], left=left, right=right)
        return left

    def parse_add(self) -> Node:
        left = self.parse_mul()
        while self.peek().kind in (TokenKind.PLUS, TokenKind.MINUS):
            op_tok = self.consume()
            right = self.parse_mul()
            left = BinaryOp(op=op_tok.value, left=left, right=right)
        return left

    def parse_mul(self) -> Node:
        left = self.parse_unary()
        while self.peek().kind in (TokenKind.STAR, TokenKind.SLASH):
            op_tok = self.consume()
            right = self.parse_unary()
            left = BinaryOp(op=op_tok.value, left=left, right=right)
        return left

    def parse_unary(self) -> Node:
        if tok := self.match(TokenKind.MINUS):
            return UnaryOp(op=tok.value, operand=self.parse_unary())
        if tok := self.match(TokenKind.NOT):
            return UnaryOp(op=tok.value.lower(), operand=self.parse_unary())
        return self.parse_atom()

    def parse_atom(self) -> Node:
        tok = self.peek()
        if tok.kind == TokenKind.LBRACKET:
            return self.parse_field_ref()
        if tok.kind == TokenKind.STRING:
            self.consume()
            return Literal(value=tok.value, literal_kind="string")
        if tok.kind == TokenKind.NUMBER:
            self.consume()
            return Literal(value=tok.value, literal_kind="number")
        if tok.kind == TokenKind.IDENT:
            # function call: IDENT '(' ... ')'
            self.consume()
            if self.peek().kind != TokenKind.LPAREN:
                raise ExpressionError(
                    f"Bare identifier {tok.value!r} at pos {tok.pos} — "
                    "expected field reference [name] or function call"
                )
            self.consume(TokenKind.LPAREN)
            args: list[Node] = []
            if self.peek().kind != TokenKind.RPAREN:
                args.append(self.parse_or())
                while self.match(TokenKind.COMMA):
                    args.append(self.parse_or())
            self.consume(TokenKind.RPAREN)
            return FunctionCall(name=tok.value, args=args)
        if tok.kind == TokenKind.LPAREN:
            self.consume()
            inner = self.parse_or()
            self.consume(TokenKind.RPAREN)
            return inner
        raise ExpressionError(f"Unexpected token {tok.kind} at pos {tok.pos}: {tok.value!r}")

    def parse_field_ref(self) -> FieldRef:
        # First bracket: either an event name or the field name.
        self.consume(TokenKind.LBRACKET)
        first_ident = self.consume()
        if first_ident.kind != TokenKind.IDENT:
            raise ExpressionError(
                f"Expected field name at pos {first_ident.pos}, got {first_ident.kind}"
            )

        # Optional inline checkbox option on this identifier: [field(code)]
        option_code: str | None = None
        if self.peek().kind == TokenKind.LPAREN:
            self.consume(TokenKind.LPAREN)
            code_tok = self.consume()
            if code_tok.kind not in (TokenKind.IDENT, TokenKind.NUMBER, TokenKind.STRING):
                raise ExpressionError(
                    f"Expected option code at pos {code_tok.pos}, got {code_tok.kind}"
                )
            option_code = code_tok.value
            self.consume(TokenKind.RPAREN)

        self.consume(TokenKind.RBRACKET)

        # Could be event-qualified: [event][field] or [event][field(code)]
        event: str | None = None
        name = first_ident.value
        if self.peek().kind == TokenKind.LBRACKET and option_code is None:
            self.consume(TokenKind.LBRACKET)
            field_tok = self.consume(TokenKind.IDENT)
            # Second bracket may also have a checkbox option
            if self.peek().kind == TokenKind.LPAREN:
                self.consume(TokenKind.LPAREN)
                code_tok = self.consume()
                if code_tok.kind not in (TokenKind.IDENT, TokenKind.NUMBER, TokenKind.STRING):
                    raise ExpressionError(
                        f"Expected option code at pos {code_tok.pos}, got {code_tok.kind}"
                    )
                option_code = code_tok.value
                self.consume(TokenKind.RPAREN)
            self.consume(TokenKind.RBRACKET)
            event = first_ident.value
            name = field_tok.value

        return FieldRef(name=name, event=event, option_code=option_code)


def parse(source: str) -> Node:
    """Parse a REDCap branching-logic expression into an AST."""
    if not source or not source.strip():
        raise ExpressionError("Empty expression")
    tokens = tokenize(source)
    return _Parser(tokens).parse()


# ---------- renderer ----------


def render(node: Node) -> str:
    """Emit the canonical REDCap string form of ``node``.

    ``parse(render(parse(s)))`` is always a fixed point; ``render(parse(s))``
    may normalize whitespace but must round-trip through ``parse`` identically.
    """
    if isinstance(node, FieldRef):
        # Checkbox option code lives INSIDE the brackets: [field(code)].
        inner = node.name
        if node.option_code is not None:
            inner = f"{node.name}({node.option_code})"
        return f"[{node.event}][{inner}]" if node.event else f"[{inner}]"
    if isinstance(node, Literal):
        if node.literal_kind == "string":
            escaped = node.value.replace("'", "\\'")
            return f"'{escaped}'"
        return node.value
    if isinstance(node, UnaryOp):
        sep = " " if node.op.isalpha() else ""
        return f"{node.op}{sep}{render(node.operand)}" if node.operand else node.op
    if isinstance(node, BinaryOp) and node.left and node.right:
        return f"{render(node.left)} {node.op} {render(node.right)}"
    if isinstance(node, LogicalOp) and node.left and node.right:
        return f"{render(node.left)} {node.op} {render(node.right)}"
    if isinstance(node, FunctionCall):
        args = ", ".join(render(a) for a in node.args)
        return f"{node.name}({args})"
    raise ExpressionError(f"Cannot render node: {node!r}")


def to_dict(node: Node) -> dict[str, Any]:
    """Serialize an AST node to a JSON-friendly dict (for the Branching model)."""
    if isinstance(node, FieldRef):
        return {
            "kind": "FieldRef",
            "name": node.name,
            "event": node.event,
            "option_code": node.option_code,
        }
    if isinstance(node, Literal):
        return {"kind": "Literal", "value": node.value, "literal_kind": node.literal_kind}
    if isinstance(node, UnaryOp):
        return {
            "kind": "UnaryOp",
            "op": node.op,
            "operand": to_dict(node.operand) if node.operand else None,
        }
    if isinstance(node, BinaryOp):
        return {
            "kind": "BinaryOp",
            "op": node.op,
            "left": to_dict(node.left) if node.left else None,
            "right": to_dict(node.right) if node.right else None,
        }
    if isinstance(node, LogicalOp):
        return {
            "kind": "LogicalOp",
            "op": node.op,
            "left": to_dict(node.left) if node.left else None,
            "right": to_dict(node.right) if node.right else None,
        }
    if isinstance(node, FunctionCall):
        return {"kind": "FunctionCall", "name": node.name, "args": [to_dict(a) for a in node.args]}
    raise ExpressionError(f"Cannot serialize node: {node!r}")


def from_dict(data: dict[str, Any]) -> Node:
    """Deserialize a dict produced by ``to_dict`` back into an AST."""
    kind = data.get("kind")
    if kind == "FieldRef":
        return FieldRef(
            name=data["name"], event=data.get("event"), option_code=data.get("option_code")
        )
    if kind == "Literal":
        return Literal(value=data["value"], literal_kind=data.get("literal_kind", "string"))
    if kind == "UnaryOp":
        operand = from_dict(data["operand"]) if data.get("operand") else None
        return UnaryOp(op=data["op"], operand=operand)
    if kind == "BinaryOp":
        return BinaryOp(
            op=data["op"],
            left=from_dict(data["left"]) if data.get("left") else None,
            right=from_dict(data["right"]) if data.get("right") else None,
        )
    if kind == "LogicalOp":
        return LogicalOp(
            op=data["op"],
            left=from_dict(data["left"]) if data.get("left") else None,
            right=from_dict(data["right"]) if data.get("right") else None,
        )
    if kind == "FunctionCall":
        return FunctionCall(name=data["name"], args=[from_dict(a) for a in data["args"]])
    raise ExpressionError(f"Unknown node kind: {kind!r}")


__all__ = [
    "BinaryOp",
    "FieldRef",
    "FunctionCall",
    "Literal",
    "LogicalOp",
    "Node",
    "Token",
    "TokenKind",
    "UnaryOp",
    "from_dict",
    "parse",
    "render",
    "to_dict",
    "tokenize",
]
