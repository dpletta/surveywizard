"""Exception hierarchy for SurveyWizard."""

from __future__ import annotations


class SurveyWizardError(Exception):
    """Base class for all SurveyWizard errors."""


class ParseError(SurveyWizardError):
    """Raised when a source file cannot be parsed."""


class ConversionError(SurveyWizardError):
    """Raised when conversion cannot proceed safely."""


class UnsupportedFieldError(ConversionError):
    """Raised when a field type cannot be mapped and strict mode is enabled."""


class ExpressionError(SurveyWizardError):
    """Raised when branching-logic expressions are malformed or untranslatable."""
