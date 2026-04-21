"""Qualtrics QSF typed models.

QSF is undocumented JSON. Models follow the reverse-engineered structure from
Christian Testa's gist and the ``QualtricsTools`` R package. Every level uses
``extra='allow'`` so unknown keys round-trip without loss.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import ConfigDict, Field

from surveywizard.models.common import BaseIR


class QSFElementCode(StrEnum):
    """Discriminator values for ``SurveyElement.Element``."""

    BL = "BL"  # Blocks (payload is an array)
    FL = "FL"  # Flow (payload is an object)
    SO = "SO"  # Survey Options
    SCO = "SCO"  # Scoring
    PROJ = "PROJ"  # Project metadata
    STAT = "STAT"  # Statistics
    QC = "QC"  # Question Count
    RS = "RS"  # Response Set
    PL = "PL"  # Predefined Library / notes
    SQ = "SQ"  # Survey Question
    TR = "TR"  # Translation
    OCAC = "OCAC"  # Other collections


class QuestionType(StrEnum):
    """``Payload.QuestionType`` values."""

    MC = "MC"
    TE = "TE"
    MATRIX = "Matrix"
    SLIDER = "Slider"
    RO = "RO"
    SBS = "SBS"
    CS = "CS"
    HL = "HL"
    HOTSPOT = "HotSpot"
    DB = "DB"
    CAPTCHA = "Captcha"
    FILE_UPLOAD = "FileUpload"
    DD = "DD"
    DRAW = "Draw"
    TIMING = "Timing"
    META = "Meta"
    DYNAMIC_MATRIX = "DynamicMatrix"


# Selectors observed in real QSFs. ``Selector`` narrows QuestionType.
# MC: SAVR (single-answer vertical radio), MAVR (multi-answer vertical),
#     SAHR (single-answer horizontal), MAHR (multi-answer horizontal),
#     DL (drop list), SB (select box).
# TE: SL (single line), ML (multi-line), ESTB (essay text box / form fields).
# Matrix: Likert, Bipolar, Profile, RS.
# Slider: HSLIDER (horizontal), HBAR, STAR.
# RO: DND (drag-drop), Box.
# DB: TB (text block), GR (graphic).


class SurveyEntry(BaseIR):
    """Top-level survey metadata (``SurveyEntry`` in QSF JSON)."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    SurveyID: str
    SurveyName: str
    # Real QSFs often have ``null`` on these string-ish fields — permit None.
    SurveyDescription: str | None = ""
    SurveyOwnerID: str | None = ""
    SurveyBrandID: str | None = ""
    DivisionID: str | None = None
    SurveyLanguage: str | None = "EN"
    SurveyActiveResponseSet: str | None = ""
    SurveyStatus: str | None = "Inactive"
    SurveyStartDate: str | None = "0000-00-00 00:00:00"
    SurveyExpirationDate: str | None = "0000-00-00 00:00:00"
    SurveyCreationDate: str | None = ""
    CreatorID: str | None = ""
    LastModified: str | None = ""
    LastAccessed: str | None = "0000-00-00 00:00:00"
    LastActivated: str | None = "0000-00-00 00:00:00"
    Deleted: str | None = None


class BlockElement(BaseIR):
    """One entry in a block's ``BlockElements`` list."""

    Type: Literal["Question", "Page Break", "Embedded Data"] | str
    QuestionID: str | None = None


class BlockOptions(BaseIR):
    model_config = ConfigDict(extra="allow")

    # QSF mixes booleans and strings for these flags in the wild — accept both.
    BlockLocking: str | bool = "false"
    RandomizeQuestions: str | bool = "false"
    Looping: str | bool = "None"
    LoopingOptions: Any = None


class Block(BaseIR):
    """One block inside the ``BL`` element (block list)."""

    Type: Literal["Default", "Standard", "Trash"] | str = "Standard"
    SubType: str = ""
    Description: str = ""
    ID: str
    BlockElements: list[BlockElement] = Field(default_factory=list)
    Options: BlockOptions = Field(default_factory=BlockOptions)


class FlowNode(BaseIR):
    """One node in the survey flow (tree structure under ``FL.Payload.Flow``)."""

    Type: str
    FlowID: str
    ID: str | None = None
    Description: str | None = None
    Flow: list[FlowNode] = Field(default_factory=list)
    # BlockRandomizer / Randomizer
    SubSet: int | None = None
    EvenPresentation: bool | None = None
    Autofill: list[Any] | None = None
    # Branch logic
    BranchLogic: dict[str, Any] | None = None
    # EmbeddedData
    EmbeddedData: list[dict[str, Any]] | None = None
    # WebService
    URL: str | None = None
    Method: str | None = None
    RequestParams: list[dict[str, Any]] | None = None
    ResponseMap: list[dict[str, Any]] | None = None
    FireAndForget: bool | None = None


FlowNode.model_rebuild()


class DisplayLogic(BaseIR):
    """Nested ``DisplayLogic`` JSON structure.

    The outer top-level numeric keys (``"0"``, ``"1"``, ...) are OR-joined
    groups. Within a group, sibling expressions use ``Conjuction`` (the
    canonical Qualtrics typo — preserve exactly) for AND/OR. Keep the raw
    dict for faithful round-trip and let translators work with it.
    """

    model_config = ConfigDict(extra="allow")

    raw: dict[str, Any]


class ValidationSettings(BaseIR):
    model_config = ConfigDict(extra="allow")

    ForceResponse: str | None = "OFF"
    ForceResponseType: str | None = "ON"
    Type: str | None = "None"


class QuestionValidation(BaseIR):
    model_config = ConfigDict(extra="allow")

    Settings: ValidationSettings = Field(default_factory=ValidationSettings)


class Choice(BaseIR):
    """One entry in ``Choices`` / ``Answers`` dicts (keyed by integer-string).

    All fields are intentionally loose — QSF mixes strings, ints, and bools
    for the same conceptual value across different surveys. The values pass
    through unchanged on round-trip.
    """

    model_config = ConfigDict(extra="allow")

    Display: str | int | float = ""
    TextEntry: str | int | bool | None = None
    TextEntryVariableType: str | None = None


class Question(BaseIR):
    """``SQ`` payload — one survey question."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    QuestionID: str
    QuestionText: str = ""
    QuestionDescription: str = ""
    DataExportTag: str = ""
    QuestionType: QuestionType
    Selector: str = ""
    SubSelector: str = ""
    Configuration: dict[str, Any] = Field(default_factory=dict)
    Validation: QuestionValidation = Field(default_factory=QuestionValidation)
    Language: list[Any] = Field(default_factory=list)
    GradingData: list[Any] = Field(default_factory=list)
    DataVisibility: dict[str, Any] = Field(default_factory=dict)
    # Choices (rows) and Answers (columns) are integer-keyed dicts
    Choices: dict[str, Choice] = Field(default_factory=dict)
    ChoiceOrder: list[int] = Field(default_factory=list)
    Answers: dict[str, Choice] = Field(default_factory=dict)
    AnswerOrder: list[int] = Field(default_factory=list)
    DefaultChoices: dict[str, Any] | bool = False
    NextChoiceId: int | None = None
    NextAnswerId: int | None = None
    Labels: list[Any] = Field(default_factory=list)
    # Display logic
    DisplayLogic: dict[str, Any] | bool | None = None


# Raw element wrapper — payload shape varies by element code
class SurveyElement(BaseIR):
    """A single entry in ``SurveyElements`` array.

    The ``Payload`` is polymorphic:
      - BL -> list[Block]
      - FL -> FlowNode (object)
      - SQ -> Question
      - SO -> dict (survey options)
      - RS / QC / STAT -> None / dict
    Store as ``dict[str, Any]`` / ``list[...]`` and let readers interpret.
    """

    model_config = ConfigDict(extra="allow")

    SurveyID: str
    # Accept any string — QSF occasionally adds new element codes (e.g. ``NT``
    # for notes in newer exports). Known codes live in ``QSFElementCode``.
    Element: str
    PrimaryAttribute: str
    SecondaryAttribute: str | None = ""
    TertiaryAttribute: str | None = None
    Payload: Any = None


class QualtricsSurvey(BaseIR):
    """Top-level QSF document."""

    model_config = ConfigDict(extra="allow")

    SurveyEntry: SurveyEntry
    SurveyElements: list[SurveyElement] = Field(default_factory=list)

    # ----- element filters for convenience

    def elements_by_code(self, code: QSFElementCode | str) -> list[SurveyElement]:
        target = code.value if isinstance(code, QSFElementCode) else code
        return [e for e in self.SurveyElements if e.Element == target]

    def blocks(self) -> list[Block]:
        """Return the single ``BL`` element's payload list, if present."""
        for e in self.SurveyElements:
            if e.Element == QSFElementCode.BL.value and isinstance(e.Payload, list):
                return [Block.model_validate(b) for b in e.Payload]
        return []

    def flow(self) -> FlowNode | None:
        for e in self.SurveyElements:
            if e.Element == QSFElementCode.FL.value and isinstance(e.Payload, dict):
                return FlowNode.model_validate(e.Payload)
        return None

    def questions(self) -> list[Question]:
        out: list[Question] = []
        for e in self.SurveyElements:
            if e.Element == QSFElementCode.SQ.value and isinstance(e.Payload, dict):
                out.append(Question.model_validate(e.Payload))
        return out

    def question_by_qid(self, qid: str) -> Question | None:
        return next((q for q in self.questions() if q.QuestionID == qid), None)
