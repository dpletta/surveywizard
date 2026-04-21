"""Central bidirectional type-mapping table for the converter pipeline.

Each row is a ``FieldMapping`` describing how one REDCap field shape maps to
one Qualtrics question shape. The table is consulted in both directions:

- ``redcap_to_qualtrics`` walks every ``RedcapField`` and picks the row whose
  REDCap key (``field_type``, ``validation_type``) matches.
- ``qualtrics_to_redcap`` walks every ``Question`` and picks the row whose
  Qualtrics key (``question_type``, ``selector``) matches.

Lossy mappings carry a ``loss`` note, which the converters forward to
``report.Report``.
"""

from __future__ import annotations

from dataclasses import dataclass

from surveywizard.models.qualtrics import QuestionType
from surveywizard.models.redcap import RedcapFieldType, RedcapValidationType


@dataclass(frozen=True)
class FieldMapping:
    """One row in the type-mapping table."""

    redcap_field_type: RedcapFieldType
    redcap_validation: RedcapValidationType = RedcapValidationType.NONE
    qualtrics_question_type: QuestionType = QuestionType.TE
    qualtrics_selector: str = "SL"
    qualtrics_sub_selector: str = ""
    qualtrics_content_type: str | None = None
    loss: str | None = None  # non-None means the mapping is approximate


# The canonical bidirectional mapping table — each row is a ``FieldMapping``.
TABLE: list[FieldMapping] = [
    # Choice-based fields
    FieldMapping(RedcapFieldType.RADIO, RedcapValidationType.NONE,
                 QuestionType.MC, "SAVR", "TX"),
    FieldMapping(RedcapFieldType.SELECT, RedcapValidationType.NONE,
                 QuestionType.MC, "DL"),
    FieldMapping(RedcapFieldType.CHECKBOX, RedcapValidationType.NONE,
                 QuestionType.MC, "MAVR", "TX"),
    FieldMapping(RedcapFieldType.YESNO, RedcapValidationType.NONE,
                 QuestionType.MC, "SAVR", "TX"),
    FieldMapping(RedcapFieldType.TRUEFALSE, RedcapValidationType.NONE,
                 QuestionType.MC, "SAVR", "TX"),

    # Text + validation subtypes
    FieldMapping(RedcapFieldType.TEXT, RedcapValidationType.NONE,
                 QuestionType.TE, "SL"),
    FieldMapping(RedcapFieldType.TEXT, RedcapValidationType.EMAIL,
                 QuestionType.TE, "SL", qualtrics_content_type="ValidEmailAddress"),
    FieldMapping(RedcapFieldType.TEXT, RedcapValidationType.INT,
                 QuestionType.TE, "SL", qualtrics_content_type="ValidNumber"),
    FieldMapping(RedcapFieldType.TEXT, RedcapValidationType.NUMBER,
                 QuestionType.TE, "SL", qualtrics_content_type="ValidNumber"),
    FieldMapping(RedcapFieldType.TEXT, RedcapValidationType.NUMBER_1DP,
                 QuestionType.TE, "SL", qualtrics_content_type="ValidNumber"),
    FieldMapping(RedcapFieldType.TEXT, RedcapValidationType.NUMBER_2DP,
                 QuestionType.TE, "SL", qualtrics_content_type="ValidNumber"),
    FieldMapping(RedcapFieldType.TEXT, RedcapValidationType.PHONE,
                 QuestionType.TE, "SL", qualtrics_content_type="ValidUSPhone"),
    FieldMapping(RedcapFieldType.TEXT, RedcapValidationType.ZIPCODE,
                 QuestionType.TE, "SL", qualtrics_content_type="ValidUSZip"),
    FieldMapping(RedcapFieldType.TEXT, RedcapValidationType.DATE_YMD,
                 QuestionType.TE, "SL", qualtrics_content_type="ValidDate"),
    FieldMapping(RedcapFieldType.TEXT, RedcapValidationType.DATE_MDY,
                 QuestionType.TE, "SL", qualtrics_content_type="ValidDate"),
    FieldMapping(RedcapFieldType.TEXT, RedcapValidationType.DATE_DMY,
                 QuestionType.TE, "SL", qualtrics_content_type="ValidDate"),
    FieldMapping(RedcapFieldType.TEXT, RedcapValidationType.DATETIME_YMD,
                 QuestionType.TE, "SL", qualtrics_content_type="ValidDate"),
    FieldMapping(RedcapFieldType.TEXT, RedcapValidationType.DATETIME_MDY,
                 QuestionType.TE, "SL", qualtrics_content_type="ValidDate"),
    FieldMapping(RedcapFieldType.TEXT, RedcapValidationType.DATETIME_DMY,
                 QuestionType.TE, "SL", qualtrics_content_type="ValidDate"),
    FieldMapping(RedcapFieldType.TEXT, RedcapValidationType.TIME,
                 QuestionType.TE, "SL", qualtrics_content_type="ValidDate"),

    # Free text
    FieldMapping(RedcapFieldType.TEXTAREA, RedcapValidationType.NONE,
                 QuestionType.TE, "ESTB"),

    # Visual / layout
    FieldMapping(RedcapFieldType.SLIDER, RedcapValidationType.NONE,
                 QuestionType.SLIDER, "HSLIDER"),
    FieldMapping(RedcapFieldType.DESCRIPTIVE, RedcapValidationType.NONE,
                 QuestionType.DB, "TB"),

    # Inherently lossy
    FieldMapping(RedcapFieldType.CALC, RedcapValidationType.NONE,
                 QuestionType.DB, "TB",
                 loss="REDCap calc equations cannot be natively evaluated by Qualtrics. "
                      "Emitted as a read-only descriptive block; formula preserved "
                      "in the question text for the survey author to replace with "
                      "Qualtrics piped-text or EmbeddedData math."),
    FieldMapping(RedcapFieldType.SQL, RedcapValidationType.NONE,
                 QuestionType.MC, "DL",
                 loss="REDCap SQL fields pull options from a database at runtime. "
                      "Qualtrics cannot replicate this dynamically; the field is "
                      "emitted with an empty option list for the author to populate."),
    FieldMapping(RedcapFieldType.FILE, RedcapValidationType.NONE,
                 QuestionType.FILE_UPLOAD, ""),
]


def lookup_from_redcap(
    field_type: RedcapFieldType,
    validation: RedcapValidationType = RedcapValidationType.NONE,
) -> FieldMapping:
    """Return the canonical Qualtrics mapping for a REDCap field shape."""
    # Exact match preferred; fall back to field_type only.
    for row in TABLE:
        if row.redcap_field_type == field_type and row.redcap_validation == validation:
            return row
    for row in TABLE:
        if row.redcap_field_type == field_type:
            return row
    # Last resort: treat as plain text
    return FieldMapping(field_type, validation, QuestionType.TE, "SL")


def lookup_from_qualtrics(
    question_type: QuestionType,
    selector: str = "",
    sub_selector: str = "",
    content_type: str | None = None,
) -> FieldMapping:
    """Return the canonical REDCap mapping for a Qualtrics question shape."""
    candidates = [r for r in TABLE if r.qualtrics_question_type == question_type]
    if selector:
        same_sel = [r for r in candidates if r.qualtrics_selector == selector]
        if same_sel:
            candidates = same_sel
    if content_type:
        by_ct = [r for r in candidates if r.qualtrics_content_type == content_type]
        if by_ct:
            return by_ct[0]
    if sub_selector:
        by_sub = [r for r in candidates if r.qualtrics_sub_selector == sub_selector]
        if by_sub:
            return by_sub[0]
    if candidates:
        return candidates[0]
    # Fall back: dump unmapped Qualtrics questions as REDCap text fields
    return FieldMapping(RedcapFieldType.TEXT, RedcapValidationType.NONE,
                        question_type, selector)


__all__ = ["TABLE", "FieldMapping", "lookup_from_qualtrics", "lookup_from_redcap"]
