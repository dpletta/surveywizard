"""Convert a ``QualtricsSurvey`` into a ``RedcapProject`` (+ Report)."""

from __future__ import annotations

import contextlib
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
            new_fields, new_code_lists = self._convert_question(q)
            fields.extend(new_fields)
            code_lists.extend(new_code_lists)

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

    def _convert_question(
        self, q: Question
    ) -> tuple[list[RedcapField], list[RedcapCodeList]]:
        """Convert one Qualtrics question into 1+ REDCap fields (+ codelists).

        Matrix questions expand to one REDCap field per row sharing a common
        ``matrix_group_name`` + codelist. Everything else produces a single
        field.
        """
        variable = self._qid_to_variable[q.QuestionID]

        # Matrix question — expand rows into N fields.
        if q.QuestionType == QuestionType.MATRIX and q.Choices:
            return self._expand_matrix(q, variable)

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
        if q.QuestionType == QuestionType.SBS:
            self.report.warn(
                f"qsf:{q.QuestionType.value}", f"redcap:{mapping.redcap_field_type.value}",
                "Qualtrics side-by-side collapsed to a single REDCap text field — "
                "reconstruct manually as a matrix group post-import.",
                variable,
            )
        if q.QuestionType in {QuestionType.HL, QuestionType.HOTSPOT, QuestionType.DRAW}:
            self.report.warn(
                f"qsf:{q.QuestionType.value}", f"redcap:{mapping.redcap_field_type.value}",
                "Qualtrics graphical question type has no REDCap equivalent — "
                "emitted as text for manual replacement.",
                variable,
            )

        return [field], ([code_list] if code_list else [])

    def _expand_matrix(
        self, q: Question, base_variable: str
    ) -> tuple[list[RedcapField], list[RedcapCodeList]]:
        """Expand a Matrix question into one REDCap field per row.

        Row layout follows Qualtrics conventions:
          - ``Choices`` = rows (one REDCap field each)
          - ``Answers`` = the shared response scale (one REDCap codelist)

        Selector determines the per-row field type:
          - ``Likert`` + ``SingleAnswer``  → radio with shared codelist
          - ``Likert`` + ``MultipleAnswer`` → checkbox with shared codelist
          - ``TE`` / ``TextEntry`` / ``Profile`` → free text per row (no codelist)
        """
        sub = q.SubSelector or ""
        selector = q.Selector or ""

        # Decide per-row field type from selector/sub-selector.
        is_text_matrix = selector.upper() in {"TE", "TEXTENTRY", "PROFILE"}
        is_multi = sub in {"MultipleAnswer", "MultiAnswer"}

        if is_text_matrix:
            row_field_type = RedcapFieldType.TEXT
        elif is_multi:
            row_field_type = RedcapFieldType.CHECKBOX
        else:
            row_field_type = RedcapFieldType.RADIO

        matrix_group = f"m_{base_variable}"[:40]

        # Shared codelist built from Answers (columns) — not used for text matrices.
        shared_code_list: RedcapCodeList | None = None
        if not is_text_matrix and q.Answers:
            items = []
            ordered = [str(i) for i in q.AnswerOrder] if q.AnswerOrder else list(q.Answers.keys())
            for idx, key in enumerate(ordered):
                ans = q.Answers.get(key)
                if ans is None:
                    continue
                display = ans.Display if isinstance(ans.Display, str) else str(ans.Display)
                items.append(RedcapCodeListItem(coded_value=key, decode=display, ordered_rank=idx))
            shared_code_list = RedcapCodeList(
                oid=f"{base_variable}.matrix_choices",
                name=base_variable,
                variable=base_variable,
                items=items,
            )

        required = False
        with contextlib.suppress(AttributeError):
            required = getattr(q.Validation.Settings, "ForceResponse", "OFF") == "ON"

        branching = qsf_display_logic_to_redcap(
            q.DisplayLogic if isinstance(q.DisplayLogic, dict) else None,
            self._qid_to_variable.get,
            self.report,
            base_variable,
        )

        row_keys = [str(i) for i in q.ChoiceOrder] if q.ChoiceOrder else list(q.Choices.keys())
        fields: list[RedcapField] = []
        used_variables: set[str] = set()
        for idx, row_key in enumerate(row_keys):
            row = q.Choices.get(row_key)
            if row is None:
                continue
            row_label = row.Display if isinstance(row.Display, str) else str(row.Display)
            row_slug = _sanitize_variable(row_label, fallback=f"row{idx + 1}") or f"row{idx + 1}"
            row_var = f"{base_variable}_{row_slug}"[:40]
            # Disambiguate collisions within this matrix
            counter = 1
            original = row_var
            while row_var in used_variables:
                row_var = f"{original[:37]}_{counter}"
                counter += 1
            used_variables.add(row_var)

            fields.append(
                RedcapField(
                    oid=row_var,
                    variable=row_var,
                    field_type=row_field_type,
                    label=row_label,
                    data_type="text",
                    required=required,
                    branching_logic=branching if idx == 0 else None,
                    matrix_group_name=matrix_group,
                    section_header=q.QuestionText if idx == 0 else None,
                    code_list_ref=shared_code_list.oid if shared_code_list else None,
                )
            )

        # Re-point the QID → variable lookup to the first row so later DisplayLogic
        # translations referencing this QID resolve to a real REDCap variable.
        if fields:
            self._qid_to_variable[q.QuestionID] = fields[0].variable

        self.report.info(
            f"qsf:Matrix/{selector}", f"redcap:{row_field_type.value}",
            f"Expanded Matrix into {len(fields)} row fields sharing matrix group "
            f"{matrix_group!r}" + (f" and codelist {shared_code_list.oid!r}" if shared_code_list else "") + ".",
            base_variable,
        )

        return fields, ([shared_code_list] if shared_code_list else [])

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
