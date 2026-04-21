"""Unit tests for the QSF reader, writer, ID minter, and logic builders."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from surveywizard.errors import ParseError
from surveywizard.models.qualtrics import QuestionType
from surveywizard.qualtrics import logic
from surveywizard.qualtrics.ids import IdMinter
from surveywizard.qualtrics.reader import parse_qsf
from surveywizard.qualtrics.writer import dumps_qsf, to_json_dict

MINIMAL_QSF = {
    "SurveyEntry": {
        "SurveyID": "SV_abc123",
        "SurveyName": "Unit Test",
        "SurveyOwnerID": "UR_owner",
        "SurveyLanguage": "EN",
    },
    "SurveyElements": [
        {
            "SurveyID": "SV_abc123",
            "Element": "BL",
            "PrimaryAttribute": "Survey Blocks",
            "SecondaryAttribute": None,
            "TertiaryAttribute": None,
            "Payload": [
                {
                    "Type": "Default",
                    "Description": "Block 1",
                    "ID": "BL_block1",
                    "BlockElements": [{"Type": "Question", "QuestionID": "QID1"}],
                    "Options": {"BlockLocking": "false", "RandomizeQuestions": "false"},
                }
            ],
        },
        {
            "SurveyID": "SV_abc123",
            "Element": "FL",
            "PrimaryAttribute": "Survey Flow",
            "Payload": {"Type": "Root", "FlowID": "FL_1",
                        "Flow": [{"Type": "Standard", "ID": "BL_block1", "FlowID": "FL_2"}]},
        },
        {
            "SurveyID": "SV_abc123",
            "Element": "SQ",
            "PrimaryAttribute": "QID1",
            "Payload": {
                "QuestionID": "QID1",
                "QuestionText": "Do you agree?",
                "DataExportTag": "agree",
                "QuestionType": "MC",
                "Selector": "SAVR",
                "Choices": {"1": {"Display": "Yes"}, "2": {"Display": "No"}},
                "ChoiceOrder": [1, 2],
                "Validation": {"Settings": {"ForceResponse": "OFF", "Type": "None"}},
            },
        },
    ],
}


class TestReader:
    def test_parses_minimal_qsf(self, tmp_path: Path) -> None:
        path = tmp_path / "in.qsf"
        path.write_text(json.dumps(MINIMAL_QSF), encoding="utf-8")
        survey = parse_qsf(path)
        assert survey.SurveyEntry.SurveyName == "Unit Test"
        assert len(survey.SurveyElements) == 3

    def test_parses_bytes_input(self) -> None:
        raw = json.dumps(MINIMAL_QSF).encode()
        survey = parse_qsf(raw)
        assert survey.SurveyEntry.SurveyID == "SV_abc123"

    def test_extracts_questions(self) -> None:
        survey = parse_qsf(json.dumps(MINIMAL_QSF).encode())
        qs = survey.questions()
        assert len(qs) == 1
        assert qs[0].QuestionType == QuestionType.MC
        assert qs[0].Choices["1"].Display == "Yes"

    def test_extracts_blocks(self) -> None:
        survey = parse_qsf(json.dumps(MINIMAL_QSF).encode())
        blocks = survey.blocks()
        assert len(blocks) == 1
        assert blocks[0].ID == "BL_block1"

    def test_extracts_flow(self) -> None:
        survey = parse_qsf(json.dumps(MINIMAL_QSF).encode())
        flow = survey.flow()
        assert flow is not None
        assert flow.Type == "Root"

    def test_malformed_json_raises(self) -> None:
        with pytest.raises(ParseError, match="parse error"):
            parse_qsf(b"not json at all")

    def test_missing_top_keys_raises(self) -> None:
        with pytest.raises(ParseError, match="missing required"):
            parse_qsf(b'{"foo": "bar"}')


class TestFixtures:
    """Parse each of the 5 downloaded QSF fixtures."""

    def test_parse_conjoint(self, qualtrics_fixtures: Path) -> None:
        survey = parse_qsf(qualtrics_fixtures / "conjoint.qsf")
        assert len(survey.questions()) > 5
        # conjoint has WebService in its flow
        flow = survey.flow()
        assert flow is not None

    def test_parse_team_skills(self, qualtrics_fixtures: Path) -> None:
        survey = parse_qsf(qualtrics_fixtures / "team_skills.qsf")
        qs = survey.questions()
        # Matrix/Likert questions
        matrix_qs = [q for q in qs if q.QuestionType == QuestionType.MATRIX]
        assert len(matrix_qs) > 0

    def test_parse_better_sample(self, qualtrics_fixtures: Path) -> None:
        survey = parse_qsf(qualtrics_fixtures / "better_sample.qsf")
        assert survey.SurveyEntry.SurveyName

    def test_parse_occupation_immigration(self, qualtrics_fixtures: Path) -> None:
        survey = parse_qsf(qualtrics_fixtures / "occupation_immigration.qsf")
        qs = survey.questions()
        te_with_validation = [q for q in qs if q.QuestionType == QuestionType.TE]
        assert len(te_with_validation) > 0

    def test_parse_productivity_experiment(self, qualtrics_fixtures: Path) -> None:
        survey = parse_qsf(qualtrics_fixtures / "productivity_experiment.qsf")
        flow = survey.flow()
        assert flow is not None


class TestWriter:
    def test_round_trip_minimal(self) -> None:
        survey = parse_qsf(json.dumps(MINIMAL_QSF).encode())
        serialized = dumps_qsf(survey)
        reparsed = parse_qsf(serialized.encode())
        assert reparsed.SurveyEntry.SurveyID == survey.SurveyEntry.SurveyID
        assert len(reparsed.SurveyElements) == len(survey.SurveyElements)

    def test_writer_preserves_choices_and_order(self) -> None:
        survey = parse_qsf(json.dumps(MINIMAL_QSF).encode())
        data = to_json_dict(survey)
        sq = next(e for e in data["SurveyElements"] if e["Element"] == "SQ")
        assert sq["Payload"]["Choices"]["1"]["Display"] == "Yes"
        assert sq["Payload"]["ChoiceOrder"] == [1, 2]

    def test_writer_preserves_unknown_keys(self) -> None:
        """Unknown Pydantic extras survive round-trip."""
        qsf = json.loads(json.dumps(MINIMAL_QSF))
        qsf["SurveyElements"][2]["Payload"]["MysteriousFutureField"] = 42
        survey = parse_qsf(json.dumps(qsf).encode())
        out = to_json_dict(survey)
        sq = next(e for e in out["SurveyElements"] if e["Element"] == "SQ")
        assert sq["Payload"]["MysteriousFutureField"] == 42

    def test_round_trip_all_fixtures(self, qualtrics_fixtures: Path) -> None:
        for fixture in sorted(qualtrics_fixtures.glob("*.qsf")):
            original = parse_qsf(fixture)
            serialized = dumps_qsf(original)
            reparsed = parse_qsf(serialized.encode())
            assert reparsed.SurveyEntry.SurveyID == original.SurveyEntry.SurveyID
            assert len(reparsed.questions()) == len(original.questions())


class TestIdMinter:
    def test_sequential_qids(self) -> None:
        m = IdMinter()
        assert m.qid() == "QID1"
        assert m.qid() == "QID2"

    def test_reserve_qid(self) -> None:
        m = IdMinter()
        m.reserve_qid("QID17")
        assert m.qid() == "QID18"

    def test_block_format(self) -> None:
        m = IdMinter(seed=42)
        b = m.block()
        assert b.startswith("BL_") and len(b) == 25

    def test_survey_format(self) -> None:
        m = IdMinter(seed=1)
        s = m.survey()
        assert s.startswith("SV_") and len(s) == 19

    def test_deterministic_with_seed(self) -> None:
        m1 = IdMinter(seed=123)
        m2 = IdMinter(seed=123)
        assert m1.block() == m2.block()
        assert m1.survey() == m2.survey()

    def test_reserve_flow(self) -> None:
        m = IdMinter()
        m.reserve_flow("FL_10")
        assert m.flow() == "FL_11"


class TestLogicBuilders:
    def test_selectable_choice_uri(self) -> None:
        assert logic.selectable_choice_uri("QID5", 1) == "q://QID5/SelectableChoice/1"

    def test_question_expression_shape(self) -> None:
        expr = logic.question_expression("QID3", "Selected", choice_code=2)
        assert expr["Operator"] == "Selected"
        assert expr["QuestionID"] == "QID3"
        assert expr["LeftOperand"] == "q://QID3/SelectableChoice/2"
        assert expr["ChoiceLocator"] == "q://QID3/SelectableChoice/2"

    def test_embedded_data_uri(self) -> None:
        assert logic.embedded_data_uri("user_email") == "ed://user_email"

    def test_group_and_adds_conjuction(self) -> None:
        e1 = logic.question_expression("QID1", "Selected", choice_code=1)
        e2 = logic.question_expression("QID2", "Selected", choice_code=1)
        group = logic.group_and([e1, e2])
        assert group["Type"] == "If"
        assert group["0"]["Operator"] == "Selected"
        assert group["1"]["Conjuction"] == "And"  # note the canonical typo

    def test_group_or_top_level(self) -> None:
        group1 = logic.group_and([logic.question_expression("QID1", "Selected", choice_code=1)])
        root = logic.group_or([group1])
        assert root["Type"] == "BooleanExpression"
        assert root["inPage"] is False
        assert root["0"] is group1
        assert logic.is_display_logic(root)
