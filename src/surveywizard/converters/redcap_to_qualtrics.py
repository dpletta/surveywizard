"""Convert a ``RedcapProject`` into a ``QualtricsSurvey`` (+ Report)."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import Any

from surveywizard.converters.expression_translator import redcap_ast_to_qsf_display_logic
from surveywizard.converters.field_mapping import FieldMapping, lookup_from_redcap
from surveywizard.models.qualtrics import (
    Block,
    BlockElement,
    BlockOptions,
    Choice,
    FlowNode,
    QSFElementCode,
    QualtricsSurvey,
    Question,
    QuestionValidation,
    SurveyElement,
    SurveyEntry,
    ValidationSettings,
)
from surveywizard.models.redcap import (
    RedcapCodeList,
    RedcapField,
    RedcapFieldType,
    RedcapProject,
    RedcapValidationType,
)
from surveywizard.qualtrics.ids import IdMinter
from surveywizard.redcap import expressions as rexpr
from surveywizard.report import Report


class RedcapToQualtrics:
    """Stateful converter — keeps the QID↔variable table + ID minter."""

    def __init__(self, project: RedcapProject, *, seed: int | None = None) -> None:
        self.project = project
        self.ids = IdMinter(seed=seed)
        self.survey_id = self.ids.survey()
        self.report = Report(direction="redcap→qualtrics",
                             source_name=project.globals.study_name or project.file_oid)
        self._var_to_qid: dict[str, str] = {}

    def convert(self) -> QualtricsSurvey:
        entry = self._build_survey_entry()

        # First pass — allocate a QID per REDCap field so branching logic can
        # reference them in the second pass.
        for field in self.project.fields:
            self._var_to_qid[field.variable] = self.ids.qid()

        questions: list[Question] = [self._convert_field(f) for f in self.project.fields]

        blocks, _block_elements_by_oid = self._build_blocks(questions)
        flow = self._build_flow(blocks)

        # Assemble SurveyElements array
        elements: list[SurveyElement] = []
        elements.append(SurveyElement(
            SurveyID=self.survey_id,
            Element=QSFElementCode.BL.value,
            PrimaryAttribute="Survey Blocks",
            SecondaryAttribute=None,
            Payload=[b.model_dump(mode="json") for b in blocks],
        ))
        elements.append(SurveyElement(
            SurveyID=self.survey_id,
            Element=QSFElementCode.FL.value,
            PrimaryAttribute="Survey Flow",
            SecondaryAttribute=None,
            Payload=flow.model_dump(mode="json"),
        ))
        elements.append(self._build_survey_options_element())
        elements.append(self._build_question_count_element(len(questions)))
        elements.append(self._build_response_set_element())
        elements.append(self._build_stat_element())

        for question in questions:
            elements.append(SurveyElement(
                SurveyID=self.survey_id,
                Element=QSFElementCode.SQ.value,
                PrimaryAttribute=question.QuestionID,
                SecondaryAttribute=question.QuestionText[:100] if question.QuestionText else "",
                Payload=question.model_dump(mode="json"),
            ))

        return QualtricsSurvey(SurveyEntry=entry, SurveyElements=elements)

    # ------------------------------------------------------------------

    def _build_survey_entry(self) -> SurveyEntry:
        now = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
        return SurveyEntry(
            SurveyID=self.survey_id,
            SurveyName=self.project.globals.study_name or "Converted REDCap Survey",
            SurveyDescription=self.project.globals.study_description or "",
            SurveyOwnerID=self.ids.user(),
            SurveyLanguage="EN",
            SurveyActiveResponseSet=self.ids.response_set(),
            SurveyCreationDate=now,
            LastModified=now,
        )

    def _convert_field(self, field: RedcapField) -> Question:
        mapping = lookup_from_redcap(field.field_type, field.validation_type)
        qid = self._var_to_qid[field.variable]

        question = Question(
            QuestionID=qid,
            QuestionText=field.label,
            DataExportTag=field.variable,
            QuestionType=mapping.qualtrics_question_type,
            Selector=mapping.qualtrics_selector,
            SubSelector=mapping.qualtrics_sub_selector,
            QuestionDescription=field.label[:255] if field.label else "",
            Configuration={"QuestionDescriptionOption": "UseText"},
            Validation=self._build_validation(field, mapping),
        )

        self._attach_choices(question, field)
        self._attach_display_logic(question, field)
        self._note_lossy_mapping(field, mapping)

        return question

    def _build_validation(
        self, field: RedcapField, mapping: FieldMapping
    ) -> QuestionValidation:
        settings = ValidationSettings(
            ForceResponse="ON" if field.required else "OFF",
            ForceResponseType="ON",
            Type="None",
        )
        extras: dict[str, Any] = {}
        if mapping.qualtrics_content_type:
            extras["Type"] = "ContentType"
            extras["ContentType"] = mapping.qualtrics_content_type
            if mapping.qualtrics_content_type == "ValidNumber":
                bounds: dict[str, Any] = {"Min": "", "Max": "", "NumDecimals": ""}
                if field.validation_min is not None:
                    bounds["Min"] = field.validation_min
                if field.validation_max is not None:
                    bounds["Max"] = field.validation_max
                if field.validation_type == RedcapValidationType.NUMBER_1DP:
                    bounds["NumDecimals"] = "1"
                elif field.validation_type == RedcapValidationType.NUMBER_2DP:
                    bounds["NumDecimals"] = "2"
                extras["ValidNumber"] = bounds
        # Merge known + extra keys by round-tripping through model_dump —
        # cleaner than mutating Pydantic's internal ``__pydantic_extra__`` dict.
        merged = settings.model_dump()
        merged.update(extras)
        return QuestionValidation(Settings=ValidationSettings.model_validate(merged))

    def _attach_choices(self, question: Question, field: RedcapField) -> None:
        if field.field_type == RedcapFieldType.YESNO:
            question.Choices = {"1": Choice(Display="Yes"), "0": Choice(Display="No")}
            question.ChoiceOrder = [1, 0]
            return
        if field.field_type == RedcapFieldType.TRUEFALSE:
            question.Choices = {"1": Choice(Display="True"), "0": Choice(Display="False")}
            question.ChoiceOrder = [1, 0]
            return
        if field.code_list_ref is None:
            return
        cl: RedcapCodeList | None = self.project.code_list_by_oid(field.code_list_ref)
        if cl is None:
            self.report.warn(
                "redcap:code_list", "qsf:Choices",
                f"CodeList {field.code_list_ref!r} missing — choices left empty.",
                field.oid,
            )
            return
        choices: dict[str, Choice] = {}
        order: list[int] = []
        for item in cl.items:
            key = item.coded_value
            choices[key] = Choice(Display=item.decode)
            with contextlib.suppress(ValueError):
                order.append(int(key))
        question.Choices = choices
        question.ChoiceOrder = order if order else list(range(1, len(choices) + 1))

    def _attach_display_logic(self, question: Question, field: RedcapField) -> None:
        if not field.branching_logic:
            return
        try:
            ast = rexpr.parse(field.branching_logic)
        except Exception as err:
            self.report.warn(
                "redcap:branching", "qsf:DisplayLogic",
                f"Could not parse branching logic `{field.branching_logic}` — dropped. {err}",
                field.oid,
            )
            return
        qid_lookup = self._var_to_qid.get
        display = redcap_ast_to_qsf_display_logic(ast, qid_lookup, self.report, field.oid)
        if display is not None:
            question.DisplayLogic = display

    def _note_lossy_mapping(self, field: RedcapField, mapping: FieldMapping) -> None:
        if mapping.loss:
            self.report.warn(
                f"redcap:{field.field_type.value}",
                f"qsf:{mapping.qualtrics_question_type.value}/{mapping.qualtrics_selector}",
                mapping.loss,
                field.oid,
            )

    # ---- Block / Flow assembly -----

    def _build_blocks(
        self, questions: list[Question]
    ) -> tuple[list[Block], dict[str, list[BlockElement]]]:
        blocks: list[Block] = []
        block_elements_by_instrument: dict[str, list[BlockElement]] = {}

        # Group fields by instrument via their item-group membership.
        instrument_for_field = self._instrument_for_field_lookup()

        for instrument in self.project.instruments:
            elements: list[BlockElement] = []
            section_seen: set[str] = set()
            for question in questions:
                field = self.project.field_by_variable(question.DataExportTag)
                if field is None:
                    continue
                owning = instrument_for_field.get(field.oid)
                if owning != instrument.oid:
                    continue

                # Insert a page break when we cross a new section header.
                if field.section_header and field.section_header not in section_seen:
                    if section_seen:  # don't lead with a break
                        elements.append(BlockElement(Type="Page Break"))
                    section_seen.add(field.section_header)
                elements.append(BlockElement(Type="Question", QuestionID=question.QuestionID))

            block = Block(
                Type="Default" if not blocks else "Standard",
                Description=instrument.title or instrument.name,
                ID=self.ids.block(),
                BlockElements=elements,
                Options=BlockOptions(),
            )
            blocks.append(block)
            block_elements_by_instrument[instrument.oid] = elements

        # Handle any fields that weren't in an instrument → bucket into a leftover block
        uncategorized: list[BlockElement] = []
        for question in questions:
            field = self.project.field_by_variable(question.DataExportTag)
            if field is None:
                continue
            if instrument_for_field.get(field.oid) is None:
                uncategorized.append(BlockElement(Type="Question", QuestionID=question.QuestionID))
        if uncategorized:
            blocks.append(Block(
                Type="Standard",
                Description="Uncategorized",
                ID=self.ids.block(),
                BlockElements=uncategorized,
                Options=BlockOptions(),
            ))

        return blocks, block_elements_by_instrument

    def _instrument_for_field_lookup(self) -> dict[str, str]:
        """Map field OID → instrument OID via item-group membership."""
        ig_by_oid = {ig.oid: ig for ig in self.project.item_groups}
        lookup: dict[str, str] = {}
        for inst in self.project.instruments:
            for ig_oid in inst.item_group_oids:
                ig = ig_by_oid.get(ig_oid)
                if ig is None:
                    continue
                for item_oid in ig.item_oids:
                    lookup[item_oid] = inst.oid
        return lookup

    def _build_flow(self, blocks: list[Block]) -> FlowNode:
        children: list[FlowNode] = []
        for block in blocks:
            children.append(FlowNode(Type="Standard", FlowID=self.ids.flow(), ID=block.ID))
        return FlowNode(Type="Root", FlowID=self.ids.flow(), Flow=children)

    def _build_survey_options_element(self) -> SurveyElement:
        return SurveyElement(
            SurveyID=self.survey_id,
            Element=QSFElementCode.SO.value,
            PrimaryAttribute="Survey Options",
            SecondaryAttribute=None,
            Payload={
                "BackButton": "true",
                "ShowProgressBar": "None",
                "SaveAndContinue": "true",
                "EOSRedirectURL": "",
                "Header": "",
                "Footer": "",
            },
        )

    def _build_question_count_element(self, count: int) -> SurveyElement:
        return SurveyElement(
            SurveyID=self.survey_id,
            Element=QSFElementCode.QC.value,
            PrimaryAttribute="Survey Question Count",
            SecondaryAttribute=str(count),
            Payload=None,
        )

    def _build_response_set_element(self) -> SurveyElement:
        rs_id = self.ids.response_set()
        return SurveyElement(
            SurveyID=self.survey_id,
            Element=QSFElementCode.RS.value,
            PrimaryAttribute=rs_id,
            SecondaryAttribute=None,
            Payload=None,
        )

    def _build_stat_element(self) -> SurveyElement:
        return SurveyElement(
            SurveyID=self.survey_id,
            Element=QSFElementCode.STAT.value,
            PrimaryAttribute="Survey Statistics",
            SecondaryAttribute=None,
            Payload={"MobileCompatible": True, "ID": self.ids.message()},
        )


def convert_redcap_to_qualtrics(
    project: RedcapProject, *, seed: int | None = None
) -> tuple[QualtricsSurvey, Report]:
    """Convenience wrapper returning both survey and report."""
    c = RedcapToQualtrics(project, seed=seed)
    survey = c.convert()
    # Record lossless-by-design facts as info entries
    if not c.report.has_problems() and not c.report.items:
        c.report.info("redcap:project", "qsf:survey",
                      f"Converted {len(project.fields)} fields into "
                      f"{len(survey.questions())} Qualtrics questions with no degradations.")
    return survey, c.report


__all__ = ["RedcapToQualtrics", "convert_redcap_to_qualtrics"]
