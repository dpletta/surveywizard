"""Unit tests for the three IR model modules."""

from __future__ import annotations

import pytest

from surveywizard.models.common import (
    Branching,
    Choice,
    CommonFieldType,
    CommonSurvey,
    CommonValidationType,
    Event,
    Field,
    Instrument,
    Section,
    SurveyMeta,
    Validation,
)
from surveywizard.models.qualtrics import (
    QSFElementCode,
    QualtricsSurvey,
    Question,
    QuestionType,
    SurveyElement,
    SurveyEntry,
)
from surveywizard.models.redcap import (
    RedcapCodeList,
    RedcapCodeListItem,
    RedcapField,
    RedcapFieldType,
    RedcapGlobalVariables,
    RedcapInstrument,
    RedcapProject,
    RedcapValidationType,
)


class TestCommonIR:
    def test_minimal_survey_constructs(self) -> None:
        s = CommonSurvey(meta=SurveyMeta(title="Study A"))
        assert s.meta.title == "Study A"
        assert s.instruments == []
        assert s.events == []

    def test_field_round_trip(self) -> None:
        f = Field(
            oid="q1",
            label="What is your name?",
            field_type=CommonFieldType.TEXT,
            validation=Validation(type=CommonValidationType.NONE),
        )
        payload = f.model_dump()
        restored = Field.model_validate(payload)
        assert restored == f

    def test_branching_allows_structured_ast(self) -> None:
        b = Branching(expression="[age] > 18", ast={"type": "BinaryOp", "op": ">"})
        assert b.ast is not None
        assert b.ast["op"] == ">"

    def test_instrument_nesting(self) -> None:
        f1 = Field(oid="q1", label="Q1", field_type=CommonFieldType.TEXT)
        f2 = Field(oid="q2", label="Q2", field_type=CommonFieldType.RADIO,
                   choices=[Choice(code="1", label="Yes"), Choice(code="0", label="No")])
        sect = Section(name="Demographics", fields=[f1, f2])
        inst = Instrument(name="demo", title="Demographics", sections=[sect])
        survey = CommonSurvey(meta=SurveyMeta(title="S"), instruments=[inst])
        assert len(survey.all_fields()) == 2
        assert survey.all_fields()[1].choices[0].label == "Yes"

    def test_preserves_unknown_keys(self) -> None:
        """`extra='allow'` lets unknown keys round-trip."""
        f = Field.model_validate({
            "oid": "q1",
            "label": "Q1",
            "field_type": "text",
            "custom_future_field": "xyz",
        })
        assert f.model_dump()["custom_future_field"] == "xyz"

    def test_event_defaults(self) -> None:
        e = Event(name="baseline_arm_1", label="Baseline")
        assert e.arm == 1
        assert e.instruments == []


class TestRedcapModels:
    def test_minimal_project(self) -> None:
        p = RedcapProject(
            file_oid="000",
            creation_datetime="2026-04-21T00:00:00",
            globals=RedcapGlobalVariables(study_name="Trial"),
        )
        assert p.source_system == "REDCap"
        assert p.record_id_field == "record_id"

    def test_field_type_enum(self) -> None:
        f = RedcapField(
            oid="consent",
            variable="consent",
            field_type=RedcapFieldType.YESNO,
            label="Do you consent?",
        )
        assert f.field_type == RedcapFieldType.YESNO

    def test_code_list_lookup(self) -> None:
        cl = RedcapCodeList(
            oid="sex.choices",
            name="sex",
            items=[
                RedcapCodeListItem(coded_value="1", decode="Male"),
                RedcapCodeListItem(coded_value="2", decode="Female"),
            ],
        )
        p = RedcapProject(
            file_oid="1",
            creation_datetime="",
            globals=RedcapGlobalVariables(study_name="x"),
            code_lists=[cl],
        )
        assert p.code_list_by_oid("sex.choices") is cl
        assert p.code_list_by_oid("missing") is None

    def test_field_by_variable(self) -> None:
        f = RedcapField(
            oid="age",
            variable="age",
            field_type=RedcapFieldType.TEXT,
            label="Age",
            validation_type=RedcapValidationType.INT,
        )
        p = RedcapProject(
            file_oid="1",
            creation_datetime="",
            globals=RedcapGlobalVariables(study_name="x"),
            fields=[f],
        )
        assert p.field_by_variable("age") is f
        assert p.field_by_variable("unknown") is None

    def test_instrument_survey_settings(self) -> None:
        inst = RedcapInstrument(
            oid="Form.baseline",
            name="baseline",
            title="Baseline",
            survey_enabled=True,
            survey_title="Welcome",
        )
        assert inst.survey_enabled is True
        assert inst.survey_title == "Welcome"

    def test_extra_fields_allowed(self) -> None:
        """REDCap exports may have attributes we haven't modeled yet."""
        f = RedcapField.model_validate({
            "oid": "x",
            "variable": "x",
            "field_type": "text",
            "label": "x",
            "some_new_redcap_attr": "preserve me",
        })
        assert f.model_dump()["some_new_redcap_attr"] == "preserve me"


class TestQualtricsModels:
    def test_minimal_survey(self) -> None:
        s = QualtricsSurvey(
            SurveyEntry=SurveyEntry(SurveyID="SV_abc", SurveyName="My Survey"),
        )
        assert s.SurveyEntry.SurveyName == "My Survey"
        assert s.SurveyElements == []

    def test_element_filter(self) -> None:
        q_elem = SurveyElement(
            SurveyID="SV_1",
            Element=QSFElementCode.SQ,
            PrimaryAttribute="QID1",
            Payload={
                "QuestionID": "QID1",
                "QuestionType": "MC",
                "Selector": "SAVR",
                "QuestionText": "Q",
            },
        )
        survey = QualtricsSurvey(
            SurveyEntry=SurveyEntry(SurveyID="SV_1", SurveyName="S"),
            SurveyElements=[q_elem],
        )
        sqs = survey.elements_by_code(QSFElementCode.SQ)
        assert len(sqs) == 1
        assert sqs[0].PrimaryAttribute == "QID1"

    def test_questions_extracted(self) -> None:
        q_payload = {
            "QuestionID": "QID5",
            "QuestionText": "Rate your experience",
            "QuestionType": "MC",
            "Selector": "SAVR",
            "DataExportTag": "rating",
            "Choices": {"1": {"Display": "Good"}, "2": {"Display": "Bad"}},
            "ChoiceOrder": [1, 2],
        }
        survey = QualtricsSurvey(
            SurveyEntry=SurveyEntry(SurveyID="SV_1", SurveyName="S"),
            SurveyElements=[
                SurveyElement(
                    SurveyID="SV_1",
                    Element=QSFElementCode.SQ,
                    PrimaryAttribute="QID5",
                    Payload=q_payload,
                ),
            ],
        )
        qs = survey.questions()
        assert len(qs) == 1
        assert qs[0].QuestionType == QuestionType.MC
        assert qs[0].Choices["1"].Display == "Good"
        assert qs[0].ChoiceOrder == [1, 2]

    def test_preserves_conjuction_typo(self) -> None:
        """The canonical Qualtrics DisplayLogic uses ``Conjuction`` not
        ``Conjunction`` — must round-trip exactly."""
        payload = {
            "QuestionID": "QID1",
            "QuestionType": "MC",
            "Selector": "SAVR",
            "DisplayLogic": {
                "0": {
                    "0": {"LogicType": "Question", "Type": "Expression"},
                    "1": {"Conjuction": "And", "LogicType": "Question"},
                    "Type": "If",
                },
                "Type": "BooleanExpression",
            },
        }
        q = Question.model_validate(payload)
        dumped = q.model_dump()
        assert dumped["DisplayLogic"]["0"]["1"]["Conjuction"] == "And"

    def test_unknown_payload_keys_preserved(self) -> None:
        """Qualtrics adds internal fields like NextChoiceId — we must keep them."""
        payload = {
            "QuestionID": "QID1",
            "QuestionType": "TE",
            "Selector": "SL",
            "NextChoiceId": 42,
            "FuturQualtricsField": {"nested": True},
        }
        q = Question.model_validate(payload)
        dumped = q.model_dump()
        assert dumped["NextChoiceId"] == 42
        assert dumped["FuturQualtricsField"] == {"nested": True}


class TestEnumCoverage:
    """Verify enum coverage matches the spec field-mapping table."""

    def test_all_redcap_field_types(self) -> None:
        expected = {"text", "textarea", "radio", "select", "checkbox",
                    "yesno", "truefalse", "slider", "descriptive",
                    "calc", "file", "sql"}
        assert {ft.value for ft in RedcapFieldType} == expected

    def test_common_covers_both_sides(self) -> None:
        common_values = {ct.value for ct in CommonFieldType}
        {rt.value for rt in RedcapFieldType}
        # Common must cover every REDCap type after dropdown/textarea normalization
        # (REDCap 'select' -> common 'dropdown'; REDCap 'textarea' -> common 'textarea')
        missing = {"text", "textarea", "radio", "checkbox", "yesno", "truefalse",
                   "slider", "descriptive", "calc", "file", "sql"} - common_values
        assert missing == set()

    @pytest.mark.parametrize("code", list(QSFElementCode))
    def test_every_qsf_element_code_string(self, code: QSFElementCode) -> None:
        assert isinstance(code.value, str)
        assert 2 <= len(code.value) <= 5
