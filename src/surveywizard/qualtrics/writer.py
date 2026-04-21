"""Serialize a ``QualtricsSurvey`` model back into QSF-compatible JSON.

Qualtrics QSF re-import is order-sensitive in some places:
  - ``ChoiceOrder`` and ``AnswerOrder`` must be arrays of ints that reference
    the string keys in ``Choices``/``Answers``.
  - Unknown keys on every element must round-trip so we don't lose internal
    Qualtrics state like ``NextChoiceId`` or ``GradingData``.
  - The canonical typo ``Conjuction`` (not ``Conjunction``) in DisplayLogic
    must be preserved exactly.

This module writes JSON with ``ensure_ascii=False`` (UTF-8) and compact
separators matching Qualtrics' own exports.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from surveywizard.models.qualtrics import QualtricsSurvey


def to_json_dict(survey: QualtricsSurvey) -> dict[str, Any]:
    """Produce a plain-dict representation ready for ``json.dumps``."""
    return survey.model_dump(mode="json", by_alias=True, exclude_none=False)


def dump_qsf(survey: QualtricsSurvey, path: str | Path, *, pretty: bool = False) -> None:
    """Write the survey to a file on disk."""
    data = to_json_dict(survey)
    with open(path, "w", encoding="utf-8") as fp:
        if pretty:
            json.dump(data, fp, indent=2, ensure_ascii=False)
        else:
            json.dump(data, fp, ensure_ascii=False, separators=(",", ":"))


def dumps_qsf(survey: QualtricsSurvey, *, pretty: bool = False) -> str:
    """Serialize a survey to a JSON string."""
    data = to_json_dict(survey)
    if pretty:
        return json.dumps(data, indent=2, ensure_ascii=False)
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


__all__ = ["dump_qsf", "dumps_qsf", "to_json_dict"]
