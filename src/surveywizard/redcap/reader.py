"""Parse REDCap CDISC ODM 1.3.1 XML into a typed ``RedcapProject``."""

from __future__ import annotations

from pathlib import Path

from lxml import etree

from surveywizard.errors import ParseError
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
    RedcapRangeCheck,
    RedcapValidationType,
)
from surveywizard.redcap.field_types import NAMESPACES, rc_attr


def _text(el: etree._Element | None) -> str | None:
    if el is None:
        return None
    text = el.text
    return text.strip() if text else None


def _as_bool(value: str | None) -> bool:
    """REDCap encodes booleans as ``y``/``n`` (lowercase)."""
    return (value or "").lower() in {"y", "yes", "true", "1"}


def _as_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _translated_text(el: etree._Element | None) -> str | None:
    """Extract ``<TranslatedText>`` content from a wrapper element."""
    if el is None:
        return None
    tt = el.find("odm:TranslatedText", NAMESPACES)
    if tt is not None and tt.text:
        return tt.text
    return _text(el)


def parse_redcap_xml(source: str | Path | bytes) -> RedcapProject:
    """Parse a REDCap ODM XML export and return a typed RedcapProject.

    ``source`` may be a file path, a raw bytes buffer, or an already-open
    file. Any parse error is wrapped in ``surveywizard.errors.ParseError``.
    """
    try:
        if isinstance(source, (str, Path)):
            tree = etree.parse(str(source))
            root = tree.getroot()
        elif isinstance(source, bytes):
            root = etree.fromstring(source)
        else:
            raise TypeError(f"Unsupported source type: {type(source)!r}")
    except (etree.XMLSyntaxError, OSError) as err:
        raise ParseError(f"REDCap XML parse error: {err}") from err

    if root.tag != f"{{{NAMESPACES['odm']}}}ODM":
        raise ParseError(f"Expected root <ODM>, got {root.tag!r}")

    return _parse_odm(root)


def _parse_odm(root: etree._Element) -> RedcapProject:
    study = root.find("odm:Study", NAMESPACES)
    if study is None:
        raise ParseError("Missing <Study> element")

    globals_el = study.find("odm:GlobalVariables", NAMESPACES)
    globals_model = _parse_globals(globals_el)

    metadata = study.find("odm:MetaDataVersion", NAMESPACES)
    if metadata is None:
        raise ParseError("Missing <MetaDataVersion> element")

    record_id_field = metadata.get(rc_attr("RecordIdField")) or "record_id"

    events = _parse_events(metadata)
    instruments = _parse_instruments(metadata)
    item_groups = _parse_item_groups(metadata)
    fields = _parse_fields(metadata)
    code_lists = _parse_code_lists(metadata)

    return RedcapProject(
        file_oid=root.get("FileOID", ""),
        creation_datetime=root.get("CreationDateTime", ""),
        source_system=root.get("SourceSystem", "REDCap"),
        source_version=root.get("SourceSystemVersion"),
        odm_version=root.get("ODMVersion", "1.3.1"),
        globals=globals_model,
        record_id_field=record_id_field,
        events=events,
        instruments=instruments,
        item_groups=item_groups,
        fields=fields,
        code_lists=code_lists,
    )


def _parse_globals(el: etree._Element | None) -> RedcapGlobalVariables:
    if el is None:
        return RedcapGlobalVariables(study_name="")
    return RedcapGlobalVariables(
        study_name=_text(el.find("odm:StudyName", NAMESPACES)) or "",
        study_description=_text(el.find("odm:StudyDescription", NAMESPACES)),
        protocol_name=_text(el.find("odm:ProtocolName", NAMESPACES)),
        record_autonumbering_enabled=_as_bool(
            _text(el.find("redcap:RecordAutonumberingEnabled", NAMESPACES))
        ),
        custom_record_label=_text(el.find("redcap:CustomRecordLabel", NAMESPACES)),
        purpose=_text(el.find("redcap:Purpose", NAMESPACES)),
        purpose_other=_text(el.find("redcap:PurposeOther", NAMESPACES)),
    )


def _parse_events(metadata: etree._Element) -> list[RedcapEvent]:
    out: list[RedcapEvent] = []
    for sed in metadata.findall("odm:StudyEventDef", NAMESPACES):
        form_refs = [fr.get("FormOID", "") for fr in sed.findall("odm:FormRef", NAMESPACES)]
        out.append(
            RedcapEvent(
                oid=sed.get("OID", ""),
                name=sed.get(rc_attr("UniqueEventName")) or sed.get("Name") or "",
                label=sed.get(rc_attr("EventName")) or sed.get("Name") or "",
                arm_num=int(sed.get(rc_attr("ArmNum")) or "1"),
                arm_name=sed.get(rc_attr("ArmName")),
                repeating=sed.get("Repeating", "No") == "Yes",
                day_offset=_as_int(sed.get(rc_attr("DayOffset"))),
                offset_min=_as_int(sed.get(rc_attr("OffsetMin"))),
                offset_max=_as_int(sed.get(rc_attr("OffsetMax"))),
                form_refs=form_refs,
            )
        )
    return out


def _parse_instruments(metadata: etree._Element) -> list[RedcapInstrument]:
    out: list[RedcapInstrument] = []
    for fd in metadata.findall("odm:FormDef", NAMESPACES):
        item_group_refs = [
            igr.get("ItemGroupOID", "") for igr in fd.findall("odm:ItemGroupRef", NAMESPACES)
        ]
        out.append(
            RedcapInstrument(
                oid=fd.get("OID", ""),
                name=fd.get(rc_attr("FormName")) or fd.get("Name") or "",
                title=(
                    _translated_text(fd.find("odm:Description", NAMESPACES))
                    or fd.get("Name")
                    or ""
                ),
                repeating=fd.get("Repeating", "No") == "Yes",
                item_group_oids=item_group_refs,
                survey_enabled=_as_bool(fd.get(rc_attr("SurveyEnabled"))),
                survey_title=fd.get(rc_attr("SurveyTitle")),
                survey_instructions=fd.get(rc_attr("SurveyInstructions")),
                survey_time_limit=_as_int(fd.get(rc_attr("SurveyTimeLimit"))),
                save_and_return=_as_bool(fd.get(rc_attr("SaveAndReturn"))),
                survey_theme=fd.get(rc_attr("SurveyThemeName")),
            )
        )
    return out


def _parse_item_groups(metadata: etree._Element) -> list[RedcapItemGroup]:
    out: list[RedcapItemGroup] = []
    for ig in metadata.findall("odm:ItemGroupDef", NAMESPACES):
        items = [ir.get("ItemOID", "") for ir in ig.findall("odm:ItemRef", NAMESPACES)]
        out.append(
            RedcapItemGroup(
                oid=ig.get("OID", ""),
                name=ig.get("Name", ""),
                repeating=ig.get("Repeating", "No") == "Yes",
                section_header=ig.get(rc_attr("SectionHeader")),
                item_oids=items,
            )
        )
    return out


def _parse_range_checks(item: etree._Element) -> list[RedcapRangeCheck]:
    out: list[RedcapRangeCheck] = []
    for rc in item.findall("odm:RangeCheck", NAMESPACES):
        value = _text(rc.find("odm:CheckValue", NAMESPACES)) or ""
        err = _translated_text(rc.find("odm:ErrorMessage", NAMESPACES))
        out.append(
            RedcapRangeCheck(
                comparator=rc.get("Comparator", ""),
                soft_hard=rc.get("SoftHard", "Soft"),
                value=value,
                error_message=err,
            )
        )
    return out


def _field_type_from_attr(value: str | None) -> RedcapFieldType:
    if not value:
        return RedcapFieldType.TEXT
    try:
        return RedcapFieldType(value)
    except ValueError:
        return RedcapFieldType.TEXT


def _validation_from_attr(value: str | None) -> RedcapValidationType:
    if not value:
        return RedcapValidationType.NONE
    try:
        return RedcapValidationType(value)
    except ValueError:
        return RedcapValidationType.NONE


def _parse_fields(metadata: etree._Element) -> list[RedcapField]:
    out: list[RedcapField] = []
    for item in metadata.findall("odm:ItemDef", NAMESPACES):
        code_ref = item.find("odm:CodeListRef", NAMESPACES)
        code_list_oid = code_ref.get("CodeListOID") if code_ref is not None else None

        field = RedcapField(
            oid=item.get("OID", ""),
            variable=item.get(rc_attr("Variable")) or item.get("OID") or "",
            field_type=_field_type_from_attr(item.get(rc_attr("FieldType"))),
            label=_translated_text(item.find("odm:Question", NAMESPACES)) or "",
            data_type=item.get("DataType", "text"),
            length=_as_int(item.get("Length")),
            validation_type=_validation_from_attr(item.get(rc_attr("TextValidationType"))),
            validation_min=item.get(rc_attr("TextValidationMin")),
            validation_max=item.get(rc_attr("TextValidationMax")),
            required=_as_bool(item.get(rc_attr("RequiredField"))),
            identifier=_as_bool(item.get(rc_attr("Identifier"))),
            field_note=item.get(rc_attr("FieldNote")),
            field_annotation=item.get(rc_attr("FieldAnnotation")),
            branching_logic=item.get(rc_attr("BranchingLogic")),
            section_header=item.get(rc_attr("SectionHeader")),
            matrix_group_name=item.get(rc_attr("MatrixGroupName")),
            matrix_ranking=_as_bool(item.get(rc_attr("MatrixRanking"))),
            custom_alignment=item.get(rc_attr("CustomAlignment")),
            question_number=item.get(rc_attr("QuestionNumber")),
            code_list_ref=code_list_oid,
            range_checks=_parse_range_checks(item),
            calculation_equation=item.get(rc_attr("CalculationEquation")),
            sql_query=item.get(rc_attr("SqlQuery")),
            slider_min_label=item.get(rc_attr("SliderLabelMin")),
            slider_mid_label=item.get(rc_attr("SliderLabelMid")),
            slider_max_label=item.get(rc_attr("SliderLabelMax")),
        )
        out.append(field)
    return out


def _parse_code_lists(metadata: etree._Element) -> list[RedcapCodeList]:
    out: list[RedcapCodeList] = []
    for cl in metadata.findall("odm:CodeList", NAMESPACES):
        items: list[RedcapCodeListItem] = []
        for idx, li in enumerate(cl.findall("odm:CodeListItem", NAMESPACES)):
            items.append(
                RedcapCodeListItem(
                    coded_value=li.get("CodedValue", ""),
                    decode=_translated_text(li.find("odm:Decode", NAMESPACES)) or "",
                    ordered_rank=idx,
                )
            )
        out.append(
            RedcapCodeList(
                oid=cl.get("OID", ""),
                name=cl.get("Name", ""),
                data_type=cl.get("DataType", "text"),
                variable=cl.get(rc_attr("Variable")),
                items=items,
            )
        )
    return out


__all__ = ["parse_redcap_xml"]
