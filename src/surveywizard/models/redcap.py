"""REDCap-domain typed models (closer to XML shape).

These mirror the CDISC ODM 1.3.1 + `redcap:` namespace structure so the
reader/writer can round-trip without losing REDCap-specific attributes
that aren't modeled in the common IR.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import ConfigDict
from pydantic import Field as PydField

from surveywizard.models.common import BaseIR


class RedcapFieldType(StrEnum):
    """REDCap `redcap:FieldType` values found in the XML."""

    TEXT = "text"
    TEXTAREA = "textarea"  # notes
    RADIO = "radio"
    SELECT = "select"  # dropdown
    CHECKBOX = "checkbox"
    YESNO = "yesno"
    TRUEFALSE = "truefalse"
    SLIDER = "slider"
    DESCRIPTIVE = "descriptive"
    CALC = "calc"
    FILE = "file"
    SQL = "sql"


class RedcapValidationType(StrEnum):
    """REDCap `redcap:TextValidationType` values."""

    NONE = ""
    INT = "int"
    NUMBER = "number"
    NUMBER_1DP = "number_1dp"
    NUMBER_2DP = "number_2dp"
    NUMBER_3DP = "number_3dp"
    NUMBER_4DP = "number_4dp"
    DATE_YMD = "date_ymd"
    DATE_MDY = "date_mdy"
    DATE_DMY = "date_dmy"
    DATETIME_YMD = "datetime_ymd"
    DATETIME_MDY = "datetime_mdy"
    DATETIME_DMY = "datetime_dmy"
    DATETIME_SECONDS_YMD = "datetime_seconds_ymd"
    DATETIME_SECONDS_MDY = "datetime_seconds_mdy"
    DATETIME_SECONDS_DMY = "datetime_seconds_dmy"
    TIME = "time"
    TIME_HH_MM_SS = "time_hh_mm_ss"
    EMAIL = "email"
    PHONE = "phone"
    PHONE_AUSTRALIA = "phone_australia"
    ZIPCODE = "zipcode"
    POSTALCODE_CANADA = "postalcode_canada"
    POSTALCODE_AUSTRALIA = "postalcode_australia"
    LETTERS_ONLY = "letters_only"
    MRN_10D = "mrn_10d"
    SSN = "ssn"
    VMRN = "vmrn"
    AUTOCOMPLETE = "autocomplete"
    SIGNATURE = "signature"


class RedcapRangeCheck(BaseIR):
    """An ODM ``<RangeCheck>`` (min or max constraint on numeric/date fields)."""

    comparator: str  # GE, LE, GT, LT, EQ
    soft_hard: str = "Soft"
    value: str
    error_message: str | None = None


class RedcapCodeListItem(BaseIR):
    """One row in a `<CodeList>` — an option code + display label."""

    coded_value: str
    decode: str
    ordered_rank: int | None = None


class RedcapCodeList(BaseIR):
    """`<CodeList>` — enumerated options for radio/select/checkbox/yesno."""

    oid: str
    name: str
    data_type: str = "text"
    variable: str | None = None
    items: list[RedcapCodeListItem] = PydField(default_factory=list)


class RedcapField(BaseIR):
    """One `<ItemDef>` — a single REDCap field."""

    model_config = ConfigDict(extra="allow", str_strip_whitespace=False)

    oid: str
    variable: str  # redcap:Variable (REDCap field name, snake_case)
    field_type: RedcapFieldType
    label: str  # Question/TranslatedText

    # ODM DataType hint: text, integer, float, date, datetime, partialDatetime
    data_type: str = "text"
    length: int | None = None

    # redcap: namespace attributes
    validation_type: RedcapValidationType = RedcapValidationType.NONE
    validation_min: str | None = None
    validation_max: str | None = None
    required: bool = False
    identifier: bool = False
    field_note: str | None = None
    field_annotation: str | None = None  # action tags
    branching_logic: str | None = None
    section_header: str | None = None
    matrix_group_name: str | None = None
    matrix_ranking: bool = False
    custom_alignment: str | None = None
    question_number: str | None = None

    # Enumerated fields link to a CodeList via OID
    code_list_ref: str | None = None

    # Ranges for numeric/date fields
    range_checks: list[RedcapRangeCheck] = PydField(default_factory=list)

    # calc / sql / slider specifics
    calculation_equation: str | None = None
    sql_query: str | None = None
    slider_min_label: str | None = None
    slider_mid_label: str | None = None
    slider_max_label: str | None = None


class RedcapItemGroup(BaseIR):
    """`<ItemGroupDef>` — a section within a form."""

    oid: str
    name: str
    repeating: bool = False
    section_header: str | None = None
    item_oids: list[str] = PydField(default_factory=list)


class RedcapInstrument(BaseIR):
    """`<FormDef>` — a REDCap instrument / form."""

    oid: str
    name: str  # redcap:FormName
    title: str
    repeating: bool = False
    item_group_oids: list[str] = PydField(default_factory=list)

    # Survey-specific settings
    survey_enabled: bool = False
    survey_title: str | None = None
    survey_instructions: str | None = None
    survey_time_limit: int | None = None
    save_and_return: bool = False
    survey_theme: str | None = None


class RedcapEvent(BaseIR):
    """`<StudyEventDef>` — a longitudinal event."""

    oid: str
    name: str  # redcap:UniqueEventName
    label: str  # redcap:EventName
    arm_num: int = 1
    arm_name: str | None = None
    repeating: bool = False
    day_offset: int | None = None
    offset_min: int | None = None
    offset_max: int | None = None
    form_refs: list[str] = PydField(default_factory=list)  # FormDef OIDs in order


class RedcapGlobalVariables(BaseIR):
    """`<GlobalVariables>` — study-level settings."""

    study_name: str
    study_description: str | None = None
    protocol_name: str | None = None
    record_autonumbering_enabled: bool = True
    custom_record_label: str | None = None
    purpose: str | None = None
    purpose_other: str | None = None


class RedcapProject(BaseIR):
    """Full typed REDCap project parsed from an ODM XML export."""

    file_oid: str
    creation_datetime: str
    source_system: str = "REDCap"
    source_version: str | None = None
    odm_version: str = "1.3.1"

    globals: RedcapGlobalVariables
    record_id_field: str = "record_id"

    events: list[RedcapEvent] = PydField(default_factory=list)
    instruments: list[RedcapInstrument] = PydField(default_factory=list)
    item_groups: list[RedcapItemGroup] = PydField(default_factory=list)
    fields: list[RedcapField] = PydField(default_factory=list)
    code_lists: list[RedcapCodeList] = PydField(default_factory=list)

    # Opaque passthrough for study-level bits we don't model
    extras: dict[str, Any] = PydField(default_factory=dict)

    def field_by_oid(self, oid: str) -> RedcapField | None:
        return next((f for f in self.fields if f.oid == oid), None)

    def field_by_variable(self, variable: str) -> RedcapField | None:
        return next((f for f in self.fields if f.variable == variable), None)

    def code_list_by_oid(self, oid: str) -> RedcapCodeList | None:
        return next((c for c in self.code_lists if c.oid == oid), None)
