"""Common Intermediate Representation (IR).

The IR is the pivot for all conversions. Both `RedcapProject` and `QualtricsSurvey`
map to and from this shape so that readers, writers, and mapping logic can be
tested independently and a third format could be added without a combinatorial
explosion of pair-wise converters.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic import Field as PydField


class CommonFieldType(StrEnum):
    """Normalized field types that every source format maps to."""

    RADIO = "radio"
    DROPDOWN = "dropdown"
    CHECKBOX = "checkbox"
    TEXT = "text"
    TEXTAREA = "textarea"
    YESNO = "yesno"
    TRUEFALSE = "truefalse"
    SLIDER = "slider"
    DESCRIPTIVE = "descriptive"
    CALC = "calc"
    FILE = "file"
    SQL = "sql"
    MATRIX_SINGLE = "matrix_single"
    MATRIX_MULTI = "matrix_multi"
    RANK_ORDER = "rank_order"
    SIDE_BY_SIDE = "side_by_side"


class CommonValidationType(StrEnum):
    """Normalized text-validation types."""

    NONE = "none"
    INTEGER = "integer"
    NUMBER = "number"
    DATE = "date"
    DATETIME = "datetime"
    TIME = "time"
    EMAIL = "email"
    PHONE = "phone"
    ZIPCODE = "zipcode"
    LETTERS_ONLY = "letters_only"
    REGEX = "regex"


class BaseIR(BaseModel):
    """All IR models preserve unknown keys for round-trip fidelity."""

    model_config = ConfigDict(extra="allow", populate_by_name=True, str_strip_whitespace=False)


class Choice(BaseIR):
    """One option in a multiple-choice / dropdown / checkbox field."""

    code: str
    label: str
    allow_text_entry: bool = False


class Validation(BaseIR):
    """Text / number / date validation rules."""

    type: CommonValidationType = CommonValidationType.NONE
    required: bool = False
    min_value: str | None = None
    max_value: str | None = None
    decimals: int | None = None
    date_format: str | None = None
    regex: str | None = None
    min_length: int | None = None
    max_length: int | None = None


class Branching(BaseIR):
    """Conditional visibility rule.

    We keep both a raw expression string (REDCap mini-DSL) and, when parsed
    successfully, a structured AST. The translator consumes the AST; the
    writer emits the string form when round-tripping to REDCap.
    """

    expression: str | None = None
    ast: dict[str, Any] | None = None  # serialized AST; actual nodes live in redcap/expressions


class SliderScale(BaseIR):
    """Min/mid/max labels for slider fields."""

    min_label: str | None = None
    mid_label: str | None = None
    max_label: str | None = None
    min_value: float = 0
    max_value: float = 100
    step: float | None = None
    show_value: bool = True


class MatrixGroup(BaseIR):
    """Shared matrix group — rows share a choice list and layout."""

    group_name: str
    is_multi: bool = False
    is_ranking: bool = False


class Field(BaseIR):
    """A single survey question."""

    oid: str  # stable identifier (REDCap variable name / QSF DataExportTag)
    label: str  # visible question text
    field_type: CommonFieldType
    section_header: str | None = None
    note: str | None = None  # helper text beneath the question
    annotation: str | None = None  # action tags (@HIDDEN, @READONLY, etc.)
    identifier: bool = False  # PHI flag
    required: bool = False
    branching: Branching | None = None

    # Type-specific details — exactly one tends to be populated per field
    choices: list[Choice] = PydField(default_factory=list)
    validation: Validation | None = None
    slider_scale: SliderScale | None = None
    matrix_group: MatrixGroup | None = None
    calc_equation: str | None = None
    sql_query: str | None = None
    descriptive_attachment: str | None = None  # file/image URL
    alignment: str | None = None  # LH/LV/RH/RV
    question_number: str | None = None


class Section(BaseIR):
    """A page-break / section header within an instrument."""

    name: str
    fields: list[Field] = PydField(default_factory=list)


class Instrument(BaseIR):
    """A form / block — groups fields and sections."""

    name: str  # stable identifier
    title: str  # display title
    sections: list[Section] = PydField(default_factory=list)
    repeating: bool = False
    # Survey-specific settings (Qualtrics block options / REDCap survey settings)
    settings: dict[str, Any] = PydField(default_factory=dict)


class Event(BaseIR):
    """A longitudinal event (REDCap) or scheduled timepoint."""

    name: str  # unique event name
    label: str
    arm: int = 1
    day_offset: int | None = None
    instruments: list[str] = PydField(default_factory=list)  # instrument names in order


class SurveyMeta(BaseIR):
    """Project / survey top-level metadata."""

    title: str
    description: str | None = None
    purpose: str | None = None
    language: str = "EN"
    record_id_field: str | None = None
    source_system: str | None = None
    source_version: str | None = None


class CommonSurvey(BaseIR):
    """The pivot representation. Both REDCap and Qualtrics map here."""

    meta: SurveyMeta
    instruments: list[Instrument] = PydField(default_factory=list)
    events: list[Event] = PydField(default_factory=list)
    # Opaque passthrough for format-specific features we don't model yet
    passthrough: dict[str, Any] = PydField(default_factory=dict)

    def all_fields(self) -> list[Field]:
        """Yield every field across every instrument + section."""
        out: list[Field] = []
        for inst in self.instruments:
            for sect in inst.sections:
                out.extend(sect.fields)
        return out
