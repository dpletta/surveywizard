"""Integration tests for the end-to-end converter pipelines."""

from __future__ import annotations

from pathlib import Path

import pytest

from surveywizard.converters.field_mapping import (
    TABLE,
    lookup_from_qualtrics,
    lookup_from_redcap,
)
from surveywizard.converters.qualtrics_to_redcap import convert_qualtrics_to_redcap
from surveywizard.converters.redcap_to_qualtrics import convert_redcap_to_qualtrics
from surveywizard.models.qualtrics import QuestionType
from surveywizard.models.redcap import RedcapFieldType, RedcapValidationType
from surveywizard.qualtrics.reader import parse_qsf
from surveywizard.redcap.reader import parse_redcap_xml
from surveywizard.report import Level


class TestFieldMappingLookups:
    @pytest.mark.parametrize("row", [r for r in TABLE if not r.reverse_only])
    def test_redcap_side_resolves(self, row) -> None:
        result = lookup_from_redcap(row.redcap_field_type, row.redcap_validation)
        assert result.qualtrics_question_type == row.qualtrics_question_type

    def test_qualtrics_side_mc_savr(self) -> None:
        row = lookup_from_qualtrics(QuestionType.MC, "SAVR")
        assert row.redcap_field_type in {RedcapFieldType.RADIO, RedcapFieldType.YESNO,
                                           RedcapFieldType.TRUEFALSE}

    def test_qualtrics_te_with_email(self) -> None:
        row = lookup_from_qualtrics(QuestionType.TE, "SL", content_type="ValidEmailAddress")
        assert row.redcap_validation == RedcapValidationType.EMAIL

    def test_unknown_falls_back_to_text(self) -> None:
        row = lookup_from_qualtrics(QuestionType.META, "Meta")
        assert row.redcap_field_type == RedcapFieldType.TEXT

    def test_rank_order_maps_to_radio(self) -> None:
        row = lookup_from_qualtrics(QuestionType.RO, "DND")
        assert row.redcap_field_type == RedcapFieldType.RADIO
        assert row.loss is not None

    def test_redcap_radio_still_maps_to_mc(self) -> None:
        # Reverse-only rows must not shadow the canonical RADIO→MC mapping.
        row = lookup_from_redcap(RedcapFieldType.RADIO, RedcapValidationType.NONE)
        assert row.qualtrics_question_type == QuestionType.MC

    @pytest.mark.parametrize(
        "qtype", [QuestionType.HL, QuestionType.HOTSPOT, QuestionType.DRAW]
    )
    def test_graphical_types_map_to_text_with_loss(self, qtype) -> None:
        row = lookup_from_qualtrics(qtype)
        assert row.redcap_field_type == RedcapFieldType.TEXT
        assert row.loss is not None


def _expected_qualtrics_question_count(project) -> int:
    """Consecutive fields sharing ``matrix_group_name`` become one Matrix SQ."""
    n = 0
    i = 0
    fields = project.fields
    while i < len(fields):
        f = fields[i]
        if f.matrix_group_name is None:
            n += 1
            i += 1
            continue
        mg = f.matrix_group_name
        while i < len(fields) and fields[i].matrix_group_name == mg:
            i += 1
        n += 1
    return n


def _expected_redcap_field_count(survey) -> int:
    """Mirrors Qualtrics→REDCap expansion (matrix / TE·FORM / SBS)."""
    total = 0
    for q in survey.questions():
        qt = q.QuestionType
        sel = (q.Selector or "").upper()
        raw = q.model_dump(mode="python")
        if (qt == QuestionType.MATRIX or (qt == QuestionType.TE and sel == "FORM")) and q.Choices:
            total += len(q.Choices)
        elif qt == QuestionType.SBS and sel == "SBSMATRIX":
            addq = raw.get("AdditionalQuestions") or {}
            n = sum(
                len(col["Choices"])
                for col in addq.values()
                if isinstance(col, dict)
                and col.get("QuestionType") == "Matrix"
                and col.get("Choices")
            )
            total += n if n else 1
        else:
            total += 1
    return total


class TestRedcapToQualtrics:
    def test_convert_fixture(self, redcap_example_xml: Path) -> None:
        project = parse_redcap_xml(redcap_example_xml)
        survey, _report = convert_redcap_to_qualtrics(project, seed=42)

        assert len(survey.questions()) == _expected_qualtrics_question_count(project)

        # QIDs are unique
        qids = [q.QuestionID for q in survey.questions()]
        assert len(set(qids)) == len(qids)

        # DataExportTag mirrors the REDCap variable
        for question in survey.questions():
            assert project.field_by_variable(question.DataExportTag) is not None

        # Survey has at least one block per instrument
        blocks = survey.blocks()
        assert len(blocks) >= len(project.instruments)

    def test_yesno_produces_two_choices(self) -> None:
        # Construct a minimal project with a yesno field
        from surveywizard.models.redcap import (
            RedcapField,
            RedcapGlobalVariables,
            RedcapInstrument,
            RedcapItemGroup,
            RedcapProject,
        )

        project = RedcapProject(
            file_oid="test",
            creation_datetime="2026-04-21T00:00:00",
            globals=RedcapGlobalVariables(study_name="Test"),
            instruments=[RedcapInstrument(oid="Form.a", name="a", title="Form A",
                                           item_group_oids=["Group.a"])],
            item_groups=[RedcapItemGroup(oid="Group.a", name="a", item_oids=["consent"])],
            fields=[
                RedcapField(oid="consent", variable="consent",
                            field_type=RedcapFieldType.YESNO, label="Consent?")
            ],
        )
        survey, _report = convert_redcap_to_qualtrics(project, seed=1)
        q = survey.questions()[0]
        assert q.QuestionType == QuestionType.MC
        assert q.Selector == "SAVR"
        assert len(q.Choices) == 2
        assert q.Choices["1"].Display == "Yes"

    def test_calc_field_logs_warning(self) -> None:
        from surveywizard.models.redcap import (
            RedcapField,
            RedcapGlobalVariables,
            RedcapInstrument,
            RedcapItemGroup,
            RedcapProject,
        )

        project = RedcapProject(
            file_oid="test",
            creation_datetime="2026-04-21T00:00:00",
            globals=RedcapGlobalVariables(study_name="Test"),
            instruments=[RedcapInstrument(oid="Form.a", name="a", title="Form A",
                                           item_group_oids=["Group.a"])],
            item_groups=[RedcapItemGroup(oid="Group.a", name="a", item_oids=["age_group"])],
            fields=[
                RedcapField(oid="age_group", variable="age_group",
                            field_type=RedcapFieldType.CALC,
                            label="Age group",
                            calculation_equation="if([age] >= 65, 'senior', 'adult')")
            ],
        )
        _survey, report = convert_redcap_to_qualtrics(project)
        assert report.has_problems()
        assert any(item.level == Level.WARNING for item in report.items)
        assert any("calc" in item.from_type for item in report.items)

    def test_calc_formula_carried_into_question_text(self) -> None:
        from surveywizard.models.redcap import (
            RedcapField,
            RedcapGlobalVariables,
            RedcapInstrument,
            RedcapItemGroup,
            RedcapProject,
        )

        equation = "if([age] >= 65, 'senior', 'adult')"
        project = RedcapProject(
            file_oid="test",
            creation_datetime="2026-04-21T00:00:00",
            globals=RedcapGlobalVariables(study_name="Test"),
            instruments=[RedcapInstrument(oid="Form.a", name="a", title="Form A",
                                           item_group_oids=["Group.a"])],
            item_groups=[RedcapItemGroup(oid="Group.a", name="a", item_oids=["age_group"])],
            fields=[
                RedcapField(oid="age_group", variable="age_group",
                            field_type=RedcapFieldType.CALC,
                            label="Age group",
                            calculation_equation=equation)
            ],
        )
        survey, _report = convert_redcap_to_qualtrics(project, seed=1)
        q = survey.questions()[0]
        assert equation in q.QuestionText

    def test_sql_query_carried_into_question_text(self) -> None:
        from surveywizard.models.redcap import (
            RedcapField,
            RedcapGlobalVariables,
            RedcapInstrument,
            RedcapItemGroup,
            RedcapProject,
        )

        query = "select record_id, name from redcap_data"
        project = RedcapProject(
            file_oid="test",
            creation_datetime="2026-04-21T00:00:00",
            globals=RedcapGlobalVariables(study_name="Test"),
            instruments=[RedcapInstrument(oid="Form.a", name="a", title="Form A",
                                           item_group_oids=["Group.a"])],
            item_groups=[RedcapItemGroup(oid="Group.a", name="a", item_oids=["lookup"])],
            fields=[
                RedcapField(oid="lookup", variable="lookup",
                            field_type=RedcapFieldType.SQL,
                            label="Pick a record",
                            sql_query=query)
            ],
        )
        survey, _report = convert_redcap_to_qualtrics(project, seed=1)
        q = survey.questions()[0]
        assert query in q.QuestionText

    def test_branching_logic_becomes_display_logic(self) -> None:
        from surveywizard.models.redcap import (
            RedcapField,
            RedcapGlobalVariables,
            RedcapInstrument,
            RedcapItemGroup,
            RedcapProject,
        )

        project = RedcapProject(
            file_oid="test",
            creation_datetime="2026-04-21T00:00:00",
            globals=RedcapGlobalVariables(study_name="Test"),
            instruments=[RedcapInstrument(oid="Form.a", name="a", title="A",
                                           item_group_oids=["Group.a"])],
            item_groups=[RedcapItemGroup(oid="Group.a", name="a",
                                          item_oids=["age", "pregnant"])],
            fields=[
                RedcapField(oid="age", variable="age", field_type=RedcapFieldType.TEXT,
                            validation_type=RedcapValidationType.INT, label="Age"),
                RedcapField(oid="pregnant", variable="pregnant",
                            field_type=RedcapFieldType.YESNO, label="Pregnant?",
                            branching_logic="[age] >= 18"),
            ],
        )
        survey, _report = convert_redcap_to_qualtrics(project, seed=7)
        qp = next(q for q in survey.questions() if q.DataExportTag == "pregnant")
        assert isinstance(qp.DisplayLogic, dict)
        assert qp.DisplayLogic["Type"] == "BooleanExpression"


class TestQualtricsToRedcap:
    def test_convert_each_fixture(self, qualtrics_fixtures: Path) -> None:
        for fixture in sorted(qualtrics_fixtures.glob("*.qsf")):
            survey = parse_qsf(fixture)
            project, _report = convert_qualtrics_to_redcap(survey)
            assert project.globals.study_name

            assert len(project.fields) == _expected_redcap_field_count(survey)

            # Variable names are valid (lowercase snake_case)
            for f in project.fields:
                assert f.variable == f.variable.lower()
                assert all(c.isalnum() or c == "_" for c in f.variable)

    def test_mc_becomes_radio_with_codelist(self, qualtrics_fixtures: Path) -> None:
        survey = parse_qsf(qualtrics_fixtures / "conjoint.qsf")
        project, _report = convert_qualtrics_to_redcap(survey)
        mc_fields = [f for f in project.fields if f.field_type == RedcapFieldType.RADIO]
        assert len(mc_fields) > 0
        for f in mc_fields:
            if f.code_list_ref:
                assert project.code_list_by_oid(f.code_list_ref) is not None

    def test_rank_order_becomes_radio_with_ranking_flag(self) -> None:
        from surveywizard.models.qualtrics import (
            Choice,
            QualtricsSurvey,
            Question,
            SurveyElement,
            SurveyEntry,
        )

        question = Question(
            QuestionID="QID1",
            QuestionText="Rank these options",
            DataExportTag="rank_q",
            QuestionType=QuestionType.RO,
            Selector="DND",
            Choices={"1": Choice(Display="Apple"), "2": Choice(Display="Banana")},
            ChoiceOrder=[1, 2],
        )
        survey = QualtricsSurvey(
            SurveyEntry=SurveyEntry(SurveyID="SV_1", SurveyName="Rank survey"),
            SurveyElements=[
                SurveyElement(
                    SurveyID="SV_1",
                    Element="SQ",
                    PrimaryAttribute="QID1",
                    SecondaryAttribute="Rank these options",
                    Payload=question.model_dump(mode="json"),
                ),
            ],
        )
        project, report = convert_qualtrics_to_redcap(survey)
        ranked = [f for f in project.fields if f.matrix_ranking]
        assert len(ranked) == 1
        assert ranked[0].field_type == RedcapFieldType.RADIO
        assert ranked[0].code_list_ref is not None
        assert any(item.category == "rank_order_fallback" for item in report.items)


class TestRoundTripSurvival:
    def test_redcap_qsf_redcap(self, redcap_example_xml: Path) -> None:
        """REDCap → QSF → REDCap preserves the field count and variable names."""
        original_project = parse_redcap_xml(redcap_example_xml)
        survey, _ = convert_redcap_to_qualtrics(original_project, seed=1)
        reverted, _ = convert_qualtrics_to_redcap(survey)

        assert len(reverted.fields) == len(original_project.fields)
        original_vars = {f.variable for f in original_project.fields}
        reverted_vars = {f.variable for f in reverted.fields}
        assert original_vars == reverted_vars
