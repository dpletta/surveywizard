"""Convert a ``QualtricsSurvey`` into a ``RedcapProject`` (+ Report)."""

from __future__ import annotations

import contextlib
import re
from datetime import UTC, datetime
from typing import Any

from surveywizard.converters.expression_translator import qsf_display_logic_to_redcap
from surveywizard.converters.field_mapping import lookup_from_qualtrics
from surveywizard.models.qualtrics import Block, FlowNode, QualtricsSurvey, Question, QuestionType
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


def _additional_questions_dict(q: Question) -> dict[str, Any] | None:
    raw = q.model_dump(mode="python")
    addq = raw.get("AdditionalQuestions")
    return addq if isinstance(addq, dict) and addq else None


class QualtricsToRedcap:
    def __init__(self, survey: QualtricsSurvey) -> None:
        self.survey = survey
        self.report = Report(
            direction="qualtrics→redcap",
            source_name=survey.SurveyEntry.SurveyName or survey.SurveyEntry.SurveyID,
        )
        self._qid_to_variable: dict[str, str] = {}
        #: Every REDCap field oid emitted for a given Qualtrics QuestionID (for item groups).
        self._question_id_to_oids: dict[str, list[str]] = {}

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
        self._report_flow_gaps()

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

        # Side-by-side matrix: one REDCap matrix group per column (embedded Matrix per AdditionalQuestions).
        if q.QuestionType == QuestionType.SBS and (q.Selector or "").upper() == "SBSMATRIX":
            addq = _additional_questions_dict(q)
            if addq:
                return self._expand_sbs_matrix(q, variable, addq)

        # TE + FORM — multi-line form; each choice is a text entry row (like a text matrix).
        if q.QuestionType == QuestionType.TE and (q.Selector or "").upper() == "FORM" and q.Choices:
            return self._expand_te_form(q, variable)

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
        branching = self._merge_custom_validation_branching(q, branching, variable)

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
                category="descriptive_text",
            )
        if q.QuestionType == QuestionType.SBS:
            self.report.warn(
                f"qsf:{q.QuestionType.value}", f"redcap:{mapping.redcap_field_type.value}",
                "Qualtrics side-by-side collapsed to a single REDCap text field — "
                "reconstruct manually as a matrix group post-import.",
                variable,
                category="side_by_side_fallback",
            )
        if q.QuestionType in {QuestionType.HL, QuestionType.HOTSPOT, QuestionType.DRAW}:
            self.report.warn(
                f"qsf:{q.QuestionType.value}", f"redcap:{mapping.redcap_field_type.value}",
                "Qualtrics graphical question type has no REDCap equivalent — "
                "emitted as text for manual replacement.",
                variable,
                category="graphical_question_fallback",
            )

        self._question_id_to_oids[q.QuestionID] = [field.oid]
        return [field], ([code_list] if code_list else [])

    def _expand_matrix(
        self, q: Question, base_variable: str, *, defer_qid_registration: bool = False
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
        is_text_matrix = selector.upper() in {"TE", "TEXTENTRY", "PROFILE", "FORM"}
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
        branching = self._merge_custom_validation_branching(q, branching, base_variable)

        row_keys = [str(i) for i in q.ChoiceOrder] if q.ChoiceOrder else list(q.Choices.keys())
        cfg = q.Configuration if isinstance(q.Configuration, dict) else {}
        sw_vars = cfg.get("SurveyWizardMatrixRowVariables")
        fields: list[RedcapField] = []
        used_variables: set[str] = set()
        for idx, row_key in enumerate(row_keys):
            row = q.Choices.get(row_key)
            if row is None:
                continue
            row_label = row.Display if isinstance(row.Display, str) else str(row.Display)
            if isinstance(sw_vars, list) and idx < len(sw_vars) and isinstance(sw_vars[idx], str):
                row_var = _sanitize_variable(sw_vars[idx], fallback=f"row{idx + 1}")[:40]
            else:
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
        if not defer_qid_registration:
            if fields:
                self._qid_to_variable[q.QuestionID] = fields[0].variable
            self._question_id_to_oids[q.QuestionID] = [f.oid for f in fields]

        if not defer_qid_registration:
            self.report.info(
                f"qsf:Matrix/{selector}", f"redcap:{row_field_type.value}",
                f"Expanded Matrix into {len(fields)} row fields sharing matrix group "
                f"{matrix_group!r}" + (f" and codelist {shared_code_list.oid!r}" if shared_code_list else "") + ".",
                base_variable,
                category="matrix_expansion",
            )

        return fields, ([shared_code_list] if shared_code_list else [])

    def _expand_sbs_matrix(
        self, q: Question, base_variable: str, addq: dict[str, Any]
    ) -> tuple[list[RedcapField], list[RedcapCodeList]]:
        """Expand SBS + SBSMatrix into one REDCap matrix group per column."""
        keys = sorted(addq.keys(), key=lambda k: (int(k) if str(k).isdigit() else 0, str(k)))
        all_fields: list[RedcapField] = []
        all_lists: list[RedcapCodeList] = []
        parent_val = q.Validation.model_dump(mode="python") if q.Validation else {}
        parent_fr = "OFF"
        with contextlib.suppress(AttributeError):
            parent_fr = getattr(q.Validation.Settings, "ForceResponse", "OFF") or "OFF"
        for col_idx, ck in enumerate(keys, start=1):
            col = addq[ck]
            if not isinstance(col, dict):
                continue
            if col.get("QuestionType") != "Matrix":
                self.report.warn(
                    "qsf:SBS", "redcap:unknown",
                    f"SBS AdditionalQuestions[{ck!r}] is not Matrix; skipped.",
                    base_variable,
                    category="side_by_side_fallback",
                )
                continue
            if col_idx == 1:
                val_for_col = col.get("Validation") or parent_val
            else:
                # Apply CustomValidation merge only on the first column; repeat would AND the same rule.
                val_for_col = col.get("Validation") or {
                    "Settings": {"ForceResponse": parent_fr, "Type": "None"}
                }
            col_payload: dict[str, Any] = {
                "QuestionID": q.QuestionID,
                "QuestionText": (
                    q.QuestionText if col_idx == 1 else (col.get("QuestionText") or "")
                ),
                "DataExportTag": f"{base_variable}_c{col_idx}",
                "QuestionType": "Matrix",
                "Selector": col.get("Selector", "Likert"),
                "SubSelector": col.get("SubSelector", ""),
                "Choices": col.get("Choices", {}),
                "ChoiceOrder": col.get("ChoiceOrder", []),
                "Answers": col.get("Answers", {}),
                "AnswerOrder": col.get("AnswerOrder", []),
                "Validation": val_for_col,
                "DisplayLogic": q.DisplayLogic,
            }
            col_q = Question.model_validate(col_payload)
            sub_base = f"{base_variable}_c{col_idx}"
            rows, cls = self._expand_matrix(
                col_q, sub_base, defer_qid_registration=True
            )
            all_fields.extend(rows)
            all_lists.extend(cls)

        if not all_fields:
            return self._fallback_sbs_warning(q, base_variable)

        if all_fields:
            self._qid_to_variable[q.QuestionID] = all_fields[0].variable
        self._question_id_to_oids[q.QuestionID] = [f.oid for f in all_fields]

        self.report.info(
            "qsf:SBS/SBSMatrix", "redcap:matrix",
            f"Expanded side-by-side into {len(all_fields)} fields across {len(keys)} column matrix groups.",
            base_variable,
            category="side_by_side_expansion",
        )
        return all_fields, all_lists

    def _fallback_sbs_warning(
        self, q: Question, base_variable: str
    ) -> tuple[list[RedcapField], list[RedcapCodeList]]:
        """Single text field + warning when SBS cannot be decomposed."""
        mapping = lookup_from_qualtrics(q.QuestionType, q.Selector, q.SubSelector, None)
        required = False
        with contextlib.suppress(AttributeError):
            required = getattr(q.Validation.Settings, "ForceResponse", "OFF") == "ON"
        branching = qsf_display_logic_to_redcap(
            q.DisplayLogic if isinstance(q.DisplayLogic, dict) else None,
            self._qid_to_variable.get,
            self.report,
            base_variable,
        )
        branching = self._merge_custom_validation_branching(q, branching, base_variable)
        field = RedcapField(
            oid=base_variable,
            variable=base_variable,
            field_type=mapping.redcap_field_type,
            label=q.QuestionText or "",
            data_type=self._infer_data_type(mapping.redcap_field_type, mapping.redcap_validation),
            validation_type=mapping.redcap_validation,
            required=required,
            branching_logic=branching,
        )
        self.report.warn(
            f"qsf:{q.QuestionType.value}", f"redcap:{mapping.redcap_field_type.value}",
            "Qualtrics side-by-side could not be expanded — emitted as a single REDCap text field.",
            base_variable,
            category="side_by_side_fallback",
        )
        self._question_id_to_oids[q.QuestionID] = [field.oid]
        return [field], []

    def _expand_te_form(
        self, q: Question, base_variable: str
    ) -> tuple[list[RedcapField], list[RedcapCodeList]]:
        """Expand TE + FORM into one REDCap text field per form row (shared matrix group)."""
        content_type = None
        with contextlib.suppress(AttributeError):
            content_type = getattr(q.Validation.Settings, "ContentType", None)
        mapping = lookup_from_qualtrics(
            QuestionType.TE, "SL", "", content_type
        )

        matrix_group = f"m_{base_variable}"[:40]

        required = False
        with contextlib.suppress(AttributeError):
            required = getattr(q.Validation.Settings, "ForceResponse", "OFF") == "ON"

        branching = qsf_display_logic_to_redcap(
            q.DisplayLogic if isinstance(q.DisplayLogic, dict) else None,
            self._qid_to_variable.get,
            self.report,
            base_variable,
        )
        branching = self._merge_custom_validation_branching(q, branching, base_variable)

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
                    field_type=mapping.redcap_field_type,
                    label=row_label,
                    data_type=self._infer_data_type(
                        mapping.redcap_field_type, mapping.redcap_validation
                    ),
                    validation_type=mapping.redcap_validation,
                    required=required,
                    branching_logic=branching if idx == 0 else None,
                    matrix_group_name=matrix_group,
                    section_header=q.QuestionText if idx == 0 else None,
                )
            )

        if fields:
            self._qid_to_variable[q.QuestionID] = fields[0].variable

        self.report.info(
            "qsf:TE/FORM", f"redcap:{mapping.redcap_field_type.value}",
            f"Expanded TE+FORM into {len(fields)} text fields sharing matrix group {matrix_group!r}.",
            base_variable,
            category="form_expansion",
        )

        self._question_id_to_oids[q.QuestionID] = [f.oid for f in fields]
        return fields, []

    def _merge_custom_validation_branching(
        self,
        q: Question,
        existing: str | None,
        variable: str,
    ) -> str | None:
        """Append CustomValidation.Logic as REDCap branching when translatable."""
        try:
            settings = q.Validation.Settings
        except AttributeError:
            return existing
        val_type = getattr(settings, "Type", None)
        if val_type != "CustomValidation":
            return existing
        raw_cv = getattr(settings, "CustomValidation", None)
        if not isinstance(raw_cv, dict):
            return existing
        logic = raw_cv.get("Logic")
        if not isinstance(logic, dict):
            return existing
        translated = qsf_display_logic_to_redcap(
            logic,
            self._qid_to_variable.get,
            self.report,
            variable,
        )
        if not translated:
            self.report.warn(
                "qsf:Validation.CustomValidation", "redcap:branching_logic",
                "Qualtrics CustomValidation logic was not translated to REDCap (unsupported "
                "or empty); review field after import.",
                variable,
                category="custom_validation_fallback",
            )
            return existing
        self.report.info(
            "qsf:Validation.CustomValidation", "redcap:branching_logic",
            "Merged CustomValidation.Logic into branching_logic as an approximation; "
            "REDCap cannot enforce custom error messages from Qualtrics.",
            variable,
            category="custom_validation_merge",
        )
        if existing and translated:
            return f"({existing}) and ({translated})"
        return translated or existing

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
                expanded = self._question_id_to_oids.get(element.QuestionID)
                if expanded:
                    for oid in expanded:
                        if oid not in field_oids:
                            field_oids.append(oid)
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

    def _report_flow_gaps(self) -> None:
        flow = self.survey.flow()
        if flow is None:
            return

        counts: dict[str, int] = {}

        def walk(node: FlowNode) -> None:
            counts[node.Type] = counts.get(node.Type, 0) + 1
            for child in node.Flow:
                walk(child)

        walk(flow)
        supported = {"Root", "Block", "Standard"}
        messages = {
            "Branch": (
                "Qualtrics flow-level Branch nodes do not map cleanly to REDCap event/form "
                "structure and were ignored."
            ),
            "EmbeddedData": (
                "Qualtrics EmbeddedData flow nodes were ignored; REDCap cannot preserve flow-only "
                "embedded data fields."
            ),
            "WebService": (
                "Qualtrics WebService flow nodes were dropped; REDCap has no WebService flow equivalent."
            ),
            "BlockRandomizer": (
                "Qualtrics block randomization was ignored; REDCap imports a fixed instrument order."
            ),
            "Randomizer": (
                "Qualtrics randomizer flow nodes were ignored; REDCap imports a fixed instrument order."
            ),
            "EndSurvey": (
                "Qualtrics EndSurvey flow branches were ignored; REDCap has no equivalent flow action."
            ),
            "Authenticator": (
                "Qualtrics Authenticator flow nodes were dropped; REDCap has no equivalent flow action."
            ),
            "TableOfContents": (
                "Qualtrics TableOfContents flow nodes were dropped; REDCap has no equivalent survey shell."
            ),
        }
        for node_type, count in sorted(counts.items()):
            if node_type in supported:
                continue
            detail = messages.get(
                node_type,
                f"Qualtrics flow node type {node_type!r} is not modeled in REDCap and was ignored.",
            )
            self.report.warn(
                "qsf:flow",
                "redcap:events",
                f"{detail} ({count} node{'s' if count != 1 else ''}).",
                self.survey.SurveyEntry.SurveyID,
                category="flow_node_ignored",
            )

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
            category="conversion_summary",
        )
    return project, c.report


__all__ = ["QualtricsToRedcap", "convert_qualtrics_to_redcap"]
