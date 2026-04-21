"""Parse a Qualtrics QSF JSON file into a typed ``QualtricsSurvey``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from surveywizard.errors import ParseError
from surveywizard.models.qualtrics import QualtricsSurvey


def parse_qsf(source: str | Path | bytes) -> QualtricsSurvey:
    """Parse a QSF file (path or bytes) into a ``QualtricsSurvey`` model."""
    try:
        if isinstance(source, (str, Path)):
            with open(source, encoding="utf-8") as fp:
                data: Any = json.load(fp)
        elif isinstance(source, bytes):
            data = json.loads(source.decode("utf-8"))
        else:
            raise TypeError(f"Unsupported source type: {type(source)!r}")
    except (json.JSONDecodeError, OSError) as err:
        raise ParseError(f"QSF JSON parse error: {err}") from err

    if not isinstance(data, dict) or "SurveyEntry" not in data or "SurveyElements" not in data:
        raise ParseError(
            "QSF missing required top-level keys 'SurveyEntry' or 'SurveyElements'"
        )

    try:
        return QualtricsSurvey.model_validate(data)
    except ValidationError as err:
        raise ParseError(f"QSF schema validation failed: {err}") from err


__all__ = ["parse_qsf"]
