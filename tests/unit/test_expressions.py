"""Unit tests for the REDCap branching-logic tokenizer/parser/renderer."""

from __future__ import annotations

import pytest

from surveywizard.errors import ExpressionError
from surveywizard.redcap.expressions import (
    BinaryOp,
    FieldRef,
    FunctionCall,
    Literal,
    LogicalOp,
    from_dict,
    parse,
    render,
    to_dict,
    tokenize,
)


class TestTokenizer:
    def test_simple_field_ref(self) -> None:
        toks = tokenize("[age]")
        assert [t.kind.value for t in toks] == ["LBRACKET", "IDENT", "RBRACKET", "EOF"]

    def test_operators(self) -> None:
        toks = tokenize("<= >= <> != = < > + - * /")
        kinds = [t.kind.value for t in toks[:-1]]
        assert kinds == ["LE", "GE", "NE", "NE", "EQ", "LT", "GT", "PLUS", "MINUS", "STAR", "SLASH"]

    def test_string_literal_double(self) -> None:
        toks = tokenize('"yes"')
        assert toks[0].value == "yes"

    def test_string_literal_single(self) -> None:
        toks = tokenize("'yes'")
        assert toks[0].value == "yes"

    def test_keywords_case_insensitive(self) -> None:
        toks = tokenize("[a] = 1 AND [b] OR [c]")
        kinds = [t.kind.value for t in toks]
        assert "AND" in kinds
        assert "OR" in kinds

    def test_numeric(self) -> None:
        toks = tokenize("3.14 42")
        assert toks[0].value == "3.14"
        assert toks[1].value == "42"

    def test_unterminated_string_raises(self) -> None:
        with pytest.raises(ExpressionError, match="Unterminated"):
            tokenize("'abc")


class TestParser:
    def test_simple_equality(self) -> None:
        tree = parse("[age] = 18")
        assert isinstance(tree, BinaryOp)
        assert tree.op == "="
        assert isinstance(tree.left, FieldRef)
        assert tree.left.name == "age"
        assert isinstance(tree.right, Literal)
        assert tree.right.value == "18"

    def test_string_equality(self) -> None:
        tree = parse("[status] = 'active'")
        assert isinstance(tree, BinaryOp)
        assert isinstance(tree.right, Literal)
        assert tree.right.value == "active"
        assert tree.right.literal_kind == "string"

    def test_and_or_precedence(self) -> None:
        """'and' binds tighter than 'or'."""
        tree = parse("[a] = 1 and [b] = 2 or [c] = 3")
        # Should be (or (and ...) ...)
        assert isinstance(tree, LogicalOp)
        assert tree.op == "or"
        assert isinstance(tree.left, LogicalOp)
        assert tree.left.op == "and"

    def test_parentheses_override(self) -> None:
        tree = parse("[a] = 1 and ([b] = 2 or [c] = 3)")
        assert isinstance(tree, LogicalOp)
        assert tree.op == "and"
        assert isinstance(tree.right, LogicalOp)
        assert tree.right.op == "or"

    def test_checkbox_option_ref(self) -> None:
        tree = parse("[race(1)] = '1'")
        assert isinstance(tree, BinaryOp)
        assert isinstance(tree.left, FieldRef)
        assert tree.left.option_code == "1"

    def test_event_qualified_ref(self) -> None:
        tree = parse("[baseline_arm_1][age] > 18")
        assert isinstance(tree, BinaryOp)
        assert isinstance(tree.left, FieldRef)
        assert tree.left.event == "baseline_arm_1"
        assert tree.left.name == "age"

    def test_function_call(self) -> None:
        tree = parse("datediff([enroll], [today], 'y')")
        assert isinstance(tree, FunctionCall)
        assert tree.name == "datediff"
        assert len(tree.args) == 3

    def test_nested_functions(self) -> None:
        tree = parse("rounddown(sum([a], [b], [c]), 2)")
        assert isinstance(tree, FunctionCall)
        assert tree.name == "rounddown"
        assert isinstance(tree.args[0], FunctionCall)
        assert tree.args[0].name == "sum"

    def test_empty_expression_raises(self) -> None:
        with pytest.raises(ExpressionError, match="Empty"):
            parse("")
        with pytest.raises(ExpressionError, match="Empty"):
            parse("   ")

    def test_trailing_tokens_raise(self) -> None:
        with pytest.raises(ExpressionError, match="Trailing"):
            parse("[a] = 1 garbage_at_end")

    def test_bare_identifier_raises(self) -> None:
        with pytest.raises(ExpressionError, match="field reference"):
            parse("bare_name = 1")

    def test_compound_real_world_expression(self) -> None:
        """A real expression combining many features."""
        src = "([age] >= 18 and [consent] = '1') or [waiver(1)] = '1'"
        tree = parse(src)
        assert isinstance(tree, LogicalOp)


class TestRenderer:
    @pytest.mark.parametrize(
        "source",
        [
            "[age] = 18",
            "[status] = 'active'",
            "[a] = 1 and [b] = 2",
            "[a] = 1 or [b] = 2",
            "[baseline_arm_1][age] > 18",
            "[race(1)] = '1'",
            "datediff([start], [end], 'y')",
            "rounddown(sum([a], [b]), 2)",
            "[a] < 10",
            "[a] <> 0",
            "[a] >= 5.5",
        ],
    )
    def test_round_trip_canonical(self, source: str) -> None:
        rendered = render(parse(source))
        # Re-parsing the rendered form should yield an equivalent tree
        assert render(parse(rendered)) == rendered


class TestAstRoundTrip:
    @pytest.mark.parametrize(
        "source",
        [
            "[age] = 18",
            "[status] = 'active'",
            "[a] = 1 and [b] = 2 or [c] = 3",
            "([a] = 1 or [b] = 2) and [c] = 3",
            "[baseline_arm_1][age] >= 18",
            "[race(2)] = '1'",
            "datediff([a], [b], 'd')",
        ],
    )
    def test_ast_dict_round_trip(self, source: str) -> None:
        tree = parse(source)
        dumped = to_dict(tree)
        restored = from_dict(dumped)
        assert render(restored) == render(tree)


class TestFixtureExpressions:
    """Expressions lifted verbatim from the real REDCap fixture file."""

    @pytest.mark.parametrize(
        "expr",
        [
            "[finished] = '1'",
            "[finished] = '2'",
            "[a] = '1' and [b] <> '2'",
            "[age] >= 18 or [parent_consent] = '1'",
        ],
    )
    def test_fixture_expressions_parse(self, expr: str) -> None:
        tree = parse(expr)
        assert tree is not None
        # Render round-trip must produce equivalent
        assert render(parse(render(tree))) == render(tree)
