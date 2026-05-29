"""Translate REDCap branching-logic AST ↔ Qualtrics DisplayLogic JSON.

The two languages model the same domain (conditional visibility) with
different data shapes:

- REDCap is a compact mini-DSL evaluated by REDCap's PHP runtime.
- Qualtrics is a nested dictionary evaluated by Qualtrics' survey engine.

Translation is lossy for constructs with no cross-runtime equivalent
(``datediff``, arithmetic on mixed types, deeply nested ``if()`` calls).
Those are recorded as ``Degradation`` entries on the passed-in ``Report``.

Entry points:

- ``redcap_ast_to_qsf_display_logic(node, qid_lookup, report)`` — translate a
  REDCap AST produced by ``redcap.expressions.parse`` into a nested QSF
  ``DisplayLogic`` dict.
- ``qsf_display_logic_to_redcap(data, var_lookup, report)`` — translate a QSF
  ``DisplayLogic`` dict back into a REDCap expression string.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from surveywizard.qualtrics import logic as qlogic
from surveywizard.redcap import expressions as rexpr
from surveywizard.report import Report

# Maps REDCap comparison operator to the matching Qualtrics Operator string.
_RC_OP_TO_QSF_OP = {
    "=": "EqualTo",
    "<>": "NotEqualTo",
    "!=": "NotEqualTo",
    "<": "LessThan",
    "<=": "LessThanOrEqual",
    ">": "GreaterThan",
    ">=": "GreaterThanOrEqual",
}

_QSF_OP_TO_RC_OP = {
    "EqualTo": "=",
    "NotEqualTo": "<>",
    "LessThan": "<",
    "LessThanOrEqual": "<=",
    "GreaterThan": ">",
    "GreaterThanOrEqual": ">=",
    "Selected": "=",
    "NotSelected": "<>",
    # Presence operators — "this question was/wasn't displayed" maps to
    # REDCap "the variable is/isn't blank".
    "Displayed": "<>",
    "NotDisplayed": "=",
    "IsEmpty": "=",
    "IsNotEmpty": "<>",
    "Answered": "<>",
    "NotAnswered": "=",
    "Skipped": "=",
    "NotSkipped": "<>",
}


# Operators whose semantic is "was a specific choice *displayed*" — we
# translate by dropping the choice-specific part (REDCap can't distinguish
# "choice k was displayed" from "the question was answered").
_DISPLAY_SEMANTIC_OPS = frozenset(
    {
        "Displayed",
        "NotDisplayed",
        "IsEmpty",
        "IsNotEmpty",
        "Answered",
        "NotAnswered",
        "Skipped",
        "NotSkipped",
    }
)


def _flatten_or(node: rexpr.Node) -> list[rexpr.Node]:
    """Split an OR-joined tree into a flat list of alternative subtrees."""
    if isinstance(node, rexpr.LogicalOp) and node.op == "or":
        return _flatten_or(node.left) + _flatten_or(node.right) if node.left and node.right else []
    return [node]


def _flatten_and(node: rexpr.Node) -> list[rexpr.Node]:
    """Split an AND-joined tree into a flat list of conjuncts."""
    if isinstance(node, rexpr.LogicalOp) and node.op == "and":
        return (
            _flatten_and(node.left) + _flatten_and(node.right) if node.left and node.right else []
        )
    return [node]


def redcap_ast_to_qsf_display_logic(
    node: rexpr.Node,
    qid_lookup: Callable[[str], str | None],
    report: Report,
    source_field_oid: str | None = None,
) -> dict[str, Any] | None:
    """Build a QSF DisplayLogic dict from a REDCap AST.

    ``qid_lookup`` maps a REDCap variable name to its assigned QSF QuestionID
    (e.g. ``"age"`` → ``"QID7"``); returning ``None`` means the converter
    hasn't produced that question yet. Any missing reference is logged as a
    warning and the expression is dropped.
    """
    groups: list[dict[str, Any]] = []
    for or_branch in _flatten_or(node):
        expressions: list[dict[str, Any]] = []
        for conjunct in _flatten_and(or_branch):
            expr = _to_expression(conjunct, qid_lookup, report, source_field_oid)
            if expr is not None:
                expressions.append(expr)
        if expressions:
            groups.append(qlogic.group_and(expressions))

    if not groups:
        return None
    return qlogic.group_or(groups)


def _to_expression(
    node: rexpr.Node,
    qid_lookup: Callable[[str], str | None],
    report: Report,
    source_field_oid: str | None,
) -> dict[str, Any] | None:
    """Render a leaf-level expression."""
    if isinstance(node, rexpr.BinaryOp) and node.op in _RC_OP_TO_QSF_OP:
        left = node.left
        right = node.right
        if isinstance(left, rexpr.FieldRef):
            qid = qid_lookup(left.name)
            if qid is None:
                report.warn(
                    "redcap:branching",
                    "qsf:DisplayLogic",
                    f"Variable [{left.name}] referenced in branching logic but not "
                    "present in the output — display condition dropped.",
                    source_field_oid,
                    category="missing_branch_reference",
                )
                return None

            # Checkbox option code — use Selected/NotSelected
            if left.option_code is not None:
                op_sel: qlogic.Operator = "Selected" if node.op == "=" else "NotSelected"
                return qlogic.question_expression(qid, op_sel, choice_code=left.option_code)

            right_value = _literal_value(right)
            # If comparing to a choice code on a non-checkbox, still use SelectableChoice
            if right_value is not None and _looks_like_choice_code(right_value):
                op_sel = "Selected" if node.op == "=" else "NotSelected"
                return qlogic.question_expression(qid, op_sel, choice_code=right_value)

            op_cmp = cast(qlogic.Operator, _RC_OP_TO_QSF_OP[node.op])
            return qlogic.question_expression(
                qid,
                op_cmp,
                right_operand=right_value,
                choice_code=None,
            )

    if isinstance(node, rexpr.FunctionCall):
        report.warn(
            "redcap:branching",
            "qsf:DisplayLogic",
            f"Function call `{rexpr.render(node)}` has no direct Qualtrics "
            "equivalent — condition dropped. Consider Qualtrics custom JS.",
            source_field_oid,
            category="unsupported_branch_function",
        )
        return None

    report.warn(
        "redcap:branching",
        "qsf:DisplayLogic",
        f"Unsupported expression `{rexpr.render(node)}` — display condition dropped.",
        source_field_oid,
        category="unsupported_branch_expression",
    )
    return None


def _literal_value(node: rexpr.Node | None) -> str | None:
    if isinstance(node, rexpr.Literal):
        return node.value
    return None


def _looks_like_choice_code(value: str) -> bool:
    """Heuristic: choice codes are short alnum tokens (1, 2, YES, option_a)."""
    if not value:
        return False
    if len(value) > 16:
        return False
    return value.replace("_", "").replace("-", "").isalnum()


# ----- reverse direction: QSF DisplayLogic → REDCap expression string


def qsf_display_logic_to_redcap(
    data: dict[str, Any] | None,
    var_lookup: Callable[[str], str | None],
    report: Report,
    source_field_oid: str | None = None,
) -> str | None:
    """Emit the canonical REDCap mini-DSL string for a QSF DisplayLogic dict.

    ``var_lookup`` maps QSF QuestionID (``"QID7"``) → REDCap variable name
    (``"age"``); returning ``None`` drops the reference with a warning.
    """
    if not data or not isinstance(data, dict):
        return None
    if data.get("Type") != "BooleanExpression":
        return None

    or_parts: list[str] = []
    for _key, group in sorted(_numeric_children(data).items()):
        and_parts = _and_group_to_redcap(group, var_lookup, report, source_field_oid)
        if and_parts:
            or_parts.append(" and ".join(and_parts))
    if not or_parts:
        return None
    return " or ".join(f"({part})" if " " in part else part for part in or_parts)


def _numeric_children(group: dict[str, Any]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for key, value in group.items():
        if key.isdigit() and isinstance(value, dict):
            out[int(key)] = value
    return out


def _and_group_to_redcap(
    group: dict[str, Any],
    var_lookup: Callable[[str], str | None],
    report: Report,
    source_field_oid: str | None,
) -> list[str]:
    out: list[str] = []
    for _, expression in sorted(_numeric_children(group).items()):
        rendered = _expression_to_redcap(expression, var_lookup, report, source_field_oid)
        if rendered is not None:
            out.append(rendered)
    return out


def _expression_to_redcap(
    expression: dict[str, Any],
    var_lookup: Callable[[str], str | None],
    report: Report,
    source_field_oid: str | None,
) -> str | None:
    operator = expression.get("Operator")
    qid = expression.get("QuestionID") or expression.get("QuestionIDFromLocator")
    left_operand = expression.get("LeftOperand", "")
    right_operand = expression.get("RightOperand")
    choice_locator = expression.get("ChoiceLocator", "")

    if not operator or operator not in _QSF_OP_TO_RC_OP:
        report.warn(
            "qsf:DisplayLogic",
            "redcap:branching",
            f"Unsupported Qualtrics operator {operator!r} — condition dropped.",
            source_field_oid,
            category="unsupported_display_logic_operator",
        )
        return None

    rc_op = _QSF_OP_TO_RC_OP[operator]

    # EmbeddedData left operand: ed://field
    if left_operand.startswith("ed://"):
        ed_name = left_operand.removeprefix("ed://")
        rhs = _redcap_rhs(right_operand)
        return f"[{ed_name}] {rc_op} {rhs}"

    # Question/choice operands
    if qid is None:
        return None
    variable = var_lookup(qid)
    if variable is None:
        report.warn(
            "qsf:DisplayLogic",
            "redcap:branching",
            f"Qualtrics {qid} referenced in DisplayLogic but no matching "
            "REDCap variable — condition dropped.",
            source_field_oid,
            category="missing_display_logic_reference",
        )
        return None

    # Display-semantic operators: REDCap can only express "was this question
    # answered / is the variable blank". Degrade to a presence check and note
    # the loss in the report.
    if operator in _DISPLAY_SEMANTIC_OPS:
        report.info(
            "qsf:DisplayLogic",
            "redcap:branching",
            f"Qualtrics {operator!r} has no exact REDCap equivalent — "
            f"translated as a presence check on [{variable}] (loses "
            "choice-specific semantic if present).",
            source_field_oid,
            category="display_semantic_downgrade",
        )
        return f"[{variable}] {rc_op} ''"

    choice_code = _extract_choice_code(choice_locator) or _extract_choice_code(left_operand)
    if choice_code is not None:
        if operator == "Selected":
            return f"[{variable}({choice_code})] = '1'"
        if operator == "NotSelected":
            return f"[{variable}({choice_code})] <> '1'"
        return f"[{variable}] {rc_op} '{choice_code}'"

    rhs = _redcap_rhs(right_operand)
    return f"[{variable}] {rc_op} {rhs}"


def _extract_choice_code(locator: str) -> str | None:
    if "/SelectableChoice/" in locator:
        return locator.rsplit("/", 1)[-1]
    return None


def _redcap_rhs(value: Any) -> str:
    if value is None:
        return "''"
    if isinstance(value, bool):
        return "'1'" if value else "'0'"
    if isinstance(value, (int, float)):
        return str(value)
    stringy = str(value)
    if stringy.replace(".", "", 1).lstrip("-").isdigit():
        return stringy
    escaped = stringy.replace("'", "\\'")
    return f"'{escaped}'"


__all__ = [
    "qsf_display_logic_to_redcap",
    "redcap_ast_to_qsf_display_logic",
]
