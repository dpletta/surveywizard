"""Builders and helpers for Qualtrics ``DisplayLogic`` / ``BranchLogic`` JSON.

The DisplayLogic structure is a nested dict with numeric-string keys. Walking
it by hand is error-prone, so this module centralizes the vocabulary.

Shape:
    {
      "0": {                              # OR group 0
        "0": { <expression> },
        "1": { "Conjuction": "And", <expression> },  # note canonical typo
        "Type": "If"
      },
      "1": { ... },                        # OR group 1
      "Type": "BooleanExpression",
      "inPage": False
    }
"""

from __future__ import annotations

from typing import Any, Literal

Operator = Literal[
    "Selected",
    "NotSelected",
    "EqualTo",
    "NotEqualTo",
    "LessThan",
    "GreaterThan",
    "LessThanOrEqual",
    "GreaterThanOrEqual",
    "IsEmpty",
    "IsNotEmpty",
    "Contains",
    "NotContains",
    "Matches",
    "MatchesRegex",
]


def selectable_choice_uri(qid: str, choice_code: str | int) -> str:
    """Build a ``q://QIDn/SelectableChoice/k`` operand URI."""
    return f"q://{qid}/SelectableChoice/{choice_code}"


def choice_text_entry_uri(qid: str, choice_code: str | int | None = None) -> str:
    if choice_code is None:
        return f"q://{qid}/ChoiceTextEntryValue"
    return f"q://{qid}/ChoiceTextEntryValue/{choice_code}"


def embedded_data_uri(field_name: str) -> str:
    return f"ed://{field_name}"


def question_expression(
    qid: str,
    operator: Operator,
    choice_code: str | int | None = None,
    right_operand: str | None = None,
    conjuction: Literal["And", "Or"] | None = None,
) -> dict[str, Any]:
    """Construct one leaf expression in a DisplayLogic group."""
    node: dict[str, Any] = {
        "LogicType": "Question",
        "Type": "Expression",
        "Operator": operator,
        "QuestionID": qid,
        "QuestionIDFromLocator": qid,
        "QuestionIsInLoop": "no",
    }
    if choice_code is not None:
        uri = selectable_choice_uri(qid, choice_code)
        node["LeftOperand"] = uri
        node["ChoiceLocator"] = uri
    if right_operand is not None:
        node["RightOperand"] = right_operand
    if conjuction is not None:
        node["Conjuction"] = conjuction
    return node


def embedded_data_expression(
    field_name: str,
    operator: Operator,
    right_operand: str | None = None,
    conjuction: Literal["And", "Or"] | None = None,
) -> dict[str, Any]:
    node: dict[str, Any] = {
        "LogicType": "EmbeddedField",
        "Type": "Expression",
        "Operator": operator,
        "LeftOperand": embedded_data_uri(field_name),
        "Description": f'<span class="ConjDesc">If</span> {field_name}',
    }
    if right_operand is not None:
        node["RightOperand"] = right_operand
    if conjuction is not None:
        node["Conjuction"] = conjuction
    return node


def group_and(expressions: list[dict[str, Any]]) -> dict[str, Any]:
    """Wrap a list of expressions as one AND-joined group."""
    group: dict[str, Any] = {"Type": "If"}
    for idx, expr in enumerate(expressions):
        entry = dict(expr)
        if idx > 0 and "Conjuction" not in entry:
            entry["Conjuction"] = "And"
        group[str(idx)] = entry
    return group


def group_or(groups: list[dict[str, Any]]) -> dict[str, Any]:
    """Top-level boolean-expression wrapper of OR-joined AND groups."""
    root: dict[str, Any] = {"Type": "BooleanExpression", "inPage": False}
    for idx, group in enumerate(groups):
        root[str(idx)] = group
    return root


def is_display_logic(value: Any) -> bool:
    """Lightweight duck-type check."""
    return isinstance(value, dict) and value.get("Type") == "BooleanExpression"


__all__ = [
    "Operator",
    "choice_text_entry_uri",
    "embedded_data_expression",
    "embedded_data_uri",
    "group_and",
    "group_or",
    "is_display_logic",
    "question_expression",
    "selectable_choice_uri",
]
