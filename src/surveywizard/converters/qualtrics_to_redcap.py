"""Convert a ``QualtricsSurvey`` into a ``RedcapProject`` (+ Report)."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from surveywizard.converters.expression_translator import qsf_display_logic_to_redcap
from surveywizard.converters.field_mapping import lookup_from_qualtrics
from surveywizard.models.qualtrics import Block, QualtricsSurvey, Question, QuestionType
from surveywizard.models.redcap import (
    RedcapCodeList,
    RedcapCodeListItem,
    RedcapEvent,
    RedcapField,
    RedcapFieldType,
    RedcapGlobalVariables,
    RedcapInstrument,
    RedcapItemGroup,
    RedcapProject,
    RedcapValidationType,
)
from surveywizard.report import Report

_VALID_VARIABLE_RE = re.compile(r"[^a-z0-9_]")


def _sanitize_variable(name: str, *, fallback: str = "field") -> str:
    """REDCap variable names are lowercase snake_case, ideally ≤26 chars.

    We do not hard-truncate — REDCap's XML importer accepts longer names and
    some real-world projects have 28+ char names (e.g. synthetic
    ``..._complete`` markers). The caller's report collector can flag long
    names for the user to shorten before import.
    """
    if not name:
        return fallback
    cleaned = _VALID_VARIABLE_RE.sub("_", name.lower()).strip("_")
    if not cleaned:
        return fallback
    if cleaned[0].isdigit():
        cleaned = f"{fallback}_{cleaned}"
    return cleaned


class QualtricsToRedcap:
    def __init__(self, survey: QualtricsSurvey) -> None:
        self.survey = survey
        self.report = Report(
            direction="qualtrics→redcap",
            source_name=survey.SurveyEntry.SurveyName or survey.SurveyEntry.SurveyID,
        )
        self._qid_to_variable: dict[str, str] = {}

    def convert(self) -> RedcapProject:
        now = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%S")
        globals_ = RedcapGlobalVariables(
            study_name=self.survey.SurveyEntry.SurveyName or "Converted Qualtrics Survey",
            study_description=self.survey.SurveyEntry.SurveyDescription or None,
            record_autonumbering_enabled=True,
            purpose="0",
        )

        questions = self.survey.questions()
        blocks = self.survey.blocks()

        # First pass: assign REDCap variable names.
        variable_collisions: set[str] = set()
        for q in questions:
            base = q.DataExportTag or q.QuestionID
            variable = _sanitize_variable(base)
            while variable in variable_collisions:
                variable = f"{variable[:23]}_{len(variable_collisions):02d}"
            variable_collisions.add(variable)
            self._qid_to_variable[q.QuestionID] = variable

        fields: list[RedcapField] = []
        code_lists: list[RedcapCodeList] = []
        for q in questions:
            field, code_list = self._convert_question(q)
            fields.append(field)
            if code_list is not None:
                code_lists.append(code_list)

        instruments, item_groups = self._build_instruments(blocks, fields)
        events = self._build_default_event(instruments)

        return RedcapProject(
            file_oid=f"SurveyWizard.{self.survey.SurveyEntry.SurveyID}",
            creation_datetime=now,
            source_system="SurveyWizard",
            source_version="0.1.0",
            globals=globals_,
            record_id_field="record_id",
            events=events,
            instruments=instruments,
            item_groups=item_groups,
            fields=fields,
            code_lists=code_lists,
        )

    def _convert_question(self, q: Question) -> tuple[RedcapField, RedcapCodeList | None]:
        variable = self._qid_to_variable[q.QuestionID]
        content_type = None
        try:
            val_settings = q.Validation.Settings
            content_type = getattr(val_settings, "ContentType", None)
        except AttributeError:
            pass

        mapping = lookup_from_qualtrics(q.QuestionType, q.Selector, q.SubSelector, content_type)

        code_list: RedcapCodeList | None = None
        code_list_ref: str | None = None
        if q.Choices:
            code_list = self._build_code_list(variable, q)
            code_list_ref = code_list.oid

        required = False
        try:
            required_value = getattr(q.Validation.Settings, "ForceResponse", "OFF")
            required = required_value == "ON"
        except AttributeError:
            pass

        branching = qsf_display_logic_to_redcap(
            q.DisplayLogic if isinstance(q.DisplayLogic, dict) else None,
            self._qid_to_variable.get,
            self.report,
            variable,
        )

        field = RedcapField(
            oid=variable,
            variable=variable,
            field_type=mapping.redcap_field_type,
            label=q.QuestionText or "",
            data_type=self._infer_data_type(mapping.redcap_field_type, mapping.redcap_validation),
            validation_type=mapping.redcap_validation,
            required=required,
            branching_logic=branching,
            code_list_ref=code_list_ref,
        )

        if q.QuestionType == QuestionType.DB:
            self.report.info(
                f"qsf:{q.QuestionType.value}", f"redcap:{mapping.redcap_field_type.value}",
                "Descriptive text carried across — visible to respondent but captures no data.",
                variable,
            )
        if q.QuestionType in {QuestionType.SBS, QuestionType.MATRIX} and not q.Choices:
            self.report.warn(
                f"qsf:{q.QuestionType.value}", f"redcap:{mapping.redcap_field_type.value}",
                "Qualtrics matrix/side-by-side with no rows mapped — REDCap field "
                "produced but will need manual matrix grouping post-import.",
                variable,
            )
        if q.QuestionType in {QuestionType.HL, QuestionType.HOTSPOT, QuestionType.DRAW}:
            self.report.warn(
                f"qsf:{q.QuestionType.value}", f"redcap:{mapping.redcap_field_type.value}",
                "Qualtrics graphical question type has no REDCap equivalent — "
                "emitted as text for manual replacement.",
                variable,
            )

        return field, code_list

    @staticmethod
    def _infer_data_type(
        field_type: RedcapFieldType, validation: RedcapValidationType
    ) -> str:
        if validation in {RedcapValidationType.INT}:
            return "integer"
        if validation in {
            RedcapValidationType.NUMBER,
            RedcapValidationType.NUMBER_1DP,
            RedcapValidationType.NUMBER_2DP,
        }:
            return "float"
        if validation.value.startswith("date") and "datetime" not in validation.value:
            return "date"
        if "datetime" in validation.value:
            return "datetime"
        if validation.value.startswith("time"):
            return "partialDatetime"
        return "text"

    @staticmethod
    def _build_code_list(variable: str, q: Question) -> RedcapCodeList:
        items: list[RedcapCodeListItem] = []
        ordered_keys = [str(i) for i in q.ChoiceOrder] if q.ChoiceOrder else list(q.Choices.keys())
        for idx, key in enumerate(ordered_keys):
            choice = q.Choices.get(key)
            if choice is None:
                continue
            display = choice.Display if isinstance(choice.Display, str) else str(choice.Display)
            items.append(RedcapCodeListItem(coded_value=key, decode=display, ordered_rank=idx))
        return RedcapCodeList(
            oid=f"{variable}.choices",
            name=variable,
            variable=variable,
            items=items,
        )

    def _build_instruments(
        self, blocks: list[Block], fields: list[RedcapField]
    ) -> tuple[list[RedcapInstrument], list[RedcapItemGroup]]:
        field_by_variable = {f.variable: f for f in fields}
        instruments: list[RedcapInstrument] = []
        item_groups: list[RedcapItemGroup] = []

        if not blocks:
            ig_oid = "Group.default"
            item_groups.append(
                RedcapItemGroup(
                    oid=ig_oid,
                    name="default",
                    item_oids=[f.oid for f in fields],
                )
            )
            instruments.append(
                RedcapInstrument(
                    oid="Form.default",
                    name="default",
                    title="Survey",
                    item_group_oids=[ig_oid],
                )
            )
            return instruments, item_groups

        for block in blocks:
            if block.Type == "Trash":
                continue
            inst_name = _sanitize_variable(block.Description or block.ID, fallback="block")
            ig_oid = f"Group.{inst_name}"
            field_oids: list[str] = []
            for element in block.BlockElements:
                if element.Type != "Question" or not element.QuestionID:
                    continue
                variable = self._qid_to_variable.get(element.QuestionID)
                if variable is None:
                    continue
                field = field_by_variable.get(variable)
                if field is None:
                    continue
                field_oids.append(field.oid)
            if not field_oids:
                continue
            item_groups.append(
                RedcapItemGroup(oid=ig_oid, name=inst_name, item_oids=field_oids)
            )
            instruments.append(
                RedcapInstrument(
                    oid=f"Form.{inst_name}",
                    name=inst_name,
                    title=block.Description or inst_name,
                    item_group_oids=[ig_oid],
                )
            )

        return instruments, item_groups

    @staticmethod
    def _build_default_event(instruments: list[RedcapInstrument]) -> list[RedcapEvent]:
        """One synthesized event that includes every instrument in order."""
        if not instruments:
            return []
        return [
            RedcapEvent(
                oid="Event.1",
                name="event_1_arm_1",
                label="Event 1",
                arm_num=1,
                form_refs=[i.oid for i in instruments],
            )
        ]


def convert_qualtrics_to_redcap(survey: QualtricsSurvey) -> tuple[RedcapProject, Report]:
    c = QualtricsToRedcap(survey)
    project = c.convert()
    if not c.report.has_problems() and not c.report.items:
        c.report.info(
            "qsf:survey", "redcap:project",
            f"Converted {len(survey.questions())} Qualtrics questions into "
            f"{len(project.fields)} REDCap fields with no degradations.",
        )
    return project, c.report


__all__ = ["QualtricsToRedcap", "convert_qualtrics_to_redcap"]
