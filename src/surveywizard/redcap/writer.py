"""Serialize a ``RedcapProject`` back to CDISC ODM 1.3.1 XML.

The writer emits the canonical REDCap export shape: ``<ODM>`` root with the
CDISC namespace as default and ``redcap:`` namespace for REDCap-specific
attributes. Consumers (REDCap's project-XML importer) are strict about the
namespace declarations, attribute casing, and element ordering.
"""

from __future__ import annotations

from pathlib import Path

from lxml import etree

from surveywizard.models.redcap import (
    RedcapCodeList,
    RedcapEvent,
    RedcapField,
    RedcapGlobalVariables,
    RedcapInstrument,
    RedcapItemGroup,
    RedcapProject,
    RedcapRangeCheck,
)
from surveywizard.redcap.field_types import NAMESPACES, ODM_NS, REDCAP_NS

_NSMAP = {
    None: ODM_NS,
    "redcap": REDCAP_NS,
    "xsi": NAMESPACES["xsi"],
    "ds": NAMESPACES["ds"],
}


def _rc(name: str) -> str:
    return f"{{{REDCAP_NS}}}{name}"


def _odm(name: str) -> str:
    return f"{{{ODM_NS}}}{name}"


def _bool_yn(value: bool | None) -> str | None:
    if value is None:
        return None
    return "y" if value else "n"


def _set_attr(el: etree._Element, attr: str, value: str | None) -> None:
    if value is not None:
        el.set(attr, value)


def _set_redcap_attr(el: etree._Element, attr: str, value: str | None) -> None:
    if value is not None and value != "":
        el.set(_rc(attr), value)


def _translated(parent: etree._Element, tag: str, text: str | None) -> None:
    """Append a ``<tag><TranslatedText>...</TranslatedText></tag>`` child."""
    if text is None:
        return
    wrapper = etree.SubElement(parent, _odm(tag))
    tt = etree.SubElement(wrapper, _odm("TranslatedText"))
    tt.text = text


def build_redcap_xml(project: RedcapProject) -> etree._Element:
    """Build the ``<ODM>`` etree root for ``project``."""
    root = etree.Element(_odm("ODM"), nsmap=_NSMAP)  # type: ignore[arg-type]
    root.set("ODMVersion", project.odm_version)
    root.set("FileOID", project.file_oid)
    root.set("FileType", "Snapshot")
    root.set("CreationDateTime", project.creation_datetime)
    root.set("SourceSystem", project.source_system)
    if project.source_version:
        root.set("SourceSystemVersion", project.source_version)

    study = etree.SubElement(root, _odm("Study"))
    study.set("OID", f"Project.{project.globals.study_name or 'Study'}")

    _append_globals(study, project.globals)
    _append_metadata(study, project)

    return root


def dump_redcap_xml(project: RedcapProject, path: str | Path, *, pretty: bool = True) -> None:
    root = build_redcap_xml(project)
    tree = etree.ElementTree(root)
    tree.write(str(path), xml_declaration=True, encoding="UTF-8", pretty_print=pretty)


def dumps_redcap_xml(project: RedcapProject, *, pretty: bool = True) -> bytes:
    root = build_redcap_xml(project)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=pretty)


def _append_globals(parent: etree._Element, globals_: RedcapGlobalVariables) -> None:
    el = etree.SubElement(parent, _odm("GlobalVariables"))
    name = etree.SubElement(el, _odm("StudyName"))
    name.text = globals_.study_name or ""
    if globals_.study_description:
        desc = etree.SubElement(el, _odm("StudyDescription"))
        desc.text = globals_.study_description
    if globals_.protocol_name:
        prot = etree.SubElement(el, _odm("ProtocolName"))
        prot.text = globals_.protocol_name
    auto = etree.SubElement(el, _rc("RecordAutonumberingEnabled"))
    auto.text = _bool_yn(globals_.record_autonumbering_enabled)
    if globals_.custom_record_label:
        cr = etree.SubElement(el, _rc("CustomRecordLabel"))
        cr.text = globals_.custom_record_label
    if globals_.purpose is not None:
        p = etree.SubElement(el, _rc("Purpose"))
        p.text = globals_.purpose
    if globals_.purpose_other:
        po = etree.SubElement(el, _rc("PurposeOther"))
        po.text = globals_.purpose_other


def _append_metadata(parent: etree._Element, project: RedcapProject) -> None:
    mdv = etree.SubElement(parent, _odm("MetaDataVersion"))
    mdv.set("OID", "Metadata")
    mdv.set("Name", "Metadata")
    _set_redcap_attr(mdv, "RecordIdField", project.record_id_field)

    for event in project.events:
        _append_event(mdv, event)

    for inst in project.instruments:
        _append_instrument(mdv, inst)

    for ig in project.item_groups:
        _append_item_group(mdv, ig)

    for field in project.fields:
        _append_field(mdv, field)

    for cl in project.code_lists:
        _append_code_list(mdv, cl)


def _append_event(parent: etree._Element, event: RedcapEvent) -> None:
    el = etree.SubElement(parent, _odm("StudyEventDef"))
    el.set("OID", event.oid)
    el.set("Name", event.label)
    el.set("Repeating", "Yes" if event.repeating else "No")
    el.set("Type", "Common")
    _set_redcap_attr(el, "UniqueEventName", event.name)
    _set_redcap_attr(el, "EventName", event.label)
    _set_redcap_attr(el, "ArmNum", str(event.arm_num))
    _set_redcap_attr(el, "ArmName", event.arm_name)
    if event.day_offset is not None:
        el.set(_rc("DayOffset"), str(event.day_offset))
    if event.offset_min is not None:
        el.set(_rc("OffsetMin"), str(event.offset_min))
    if event.offset_max is not None:
        el.set(_rc("OffsetMax"), str(event.offset_max))
    for form_oid in event.form_refs:
        fr = etree.SubElement(el, _odm("FormRef"))
        fr.set("FormOID", form_oid)
        fr.set("Mandatory", "Yes")


def _append_instrument(parent: etree._Element, inst: RedcapInstrument) -> None:
    el = etree.SubElement(parent, _odm("FormDef"))
    el.set("OID", inst.oid)
    el.set("Name", inst.name)
    el.set("Repeating", "Yes" if inst.repeating else "No")
    _set_redcap_attr(el, "FormName", inst.name)
    _translated(el, "Description", inst.title)
    if inst.survey_enabled:
        el.set(_rc("SurveyEnabled"), "y")
    _set_redcap_attr(el, "SurveyTitle", inst.survey_title)
    _set_redcap_attr(el, "SurveyInstructions", inst.survey_instructions)
    if inst.survey_time_limit is not None:
        el.set(_rc("SurveyTimeLimit"), str(inst.survey_time_limit))
    if inst.save_and_return:
        el.set(_rc("SaveAndReturn"), "y")
    _set_redcap_attr(el, "SurveyThemeName", inst.survey_theme)
    for ig_oid in inst.item_group_oids:
        igr = etree.SubElement(el, _odm("ItemGroupRef"))
        igr.set("ItemGroupOID", ig_oid)
        igr.set("Mandatory", "Yes")


def _append_item_group(parent: etree._Element, ig: RedcapItemGroup) -> None:
    el = etree.SubElement(parent, _odm("ItemGroupDef"))
    el.set("OID", ig.oid)
    el.set("Name", ig.name)
    el.set("Repeating", "Yes" if ig.repeating else "No")
    _set_redcap_attr(el, "SectionHeader", ig.section_header)
    for item_oid in ig.item_oids:
        ir = etree.SubElement(el, _odm("ItemRef"))
        ir.set("ItemOID", item_oid)
        ir.set("Mandatory", "No")


def _append_field(parent: etree._Element, field: RedcapField) -> None:
    el = etree.SubElement(parent, _odm("ItemDef"))
    el.set("OID", field.oid)
    el.set("Name", field.variable)
    el.set("DataType", field.data_type)
    if field.length is not None:
        el.set("Length", str(field.length))

    _set_redcap_attr(el, "Variable", field.variable)
    _set_redcap_attr(el, "FieldType", field.field_type.value)
    if field.validation_type.value:
        _set_redcap_attr(el, "TextValidationType", field.validation_type.value)
    _set_redcap_attr(el, "TextValidationMin", field.validation_min)
    _set_redcap_attr(el, "TextValidationMax", field.validation_max)
    if field.required:
        el.set(_rc("RequiredField"), "y")
    if field.identifier:
        el.set(_rc("Identifier"), "y")
    _set_redcap_attr(el, "FieldNote", field.field_note)
    _set_redcap_attr(el, "FieldAnnotation", field.field_annotation)
    _set_redcap_attr(el, "BranchingLogic", field.branching_logic)
    _set_redcap_attr(el, "SectionHeader", field.section_header)
    _set_redcap_attr(el, "MatrixGroupName", field.matrix_group_name)
    if field.matrix_ranking:
        el.set(_rc("MatrixRanking"), "y")
    _set_redcap_attr(el, "CustomAlignment", field.custom_alignment)
    _set_redcap_attr(el, "QuestionNumber", field.question_number)
    _set_redcap_attr(el, "CalculationEquation", field.calculation_equation)
    _set_redcap_attr(el, "SqlQuery", field.sql_query)
    _set_redcap_attr(el, "SliderLabelMin", field.slider_min_label)
    _set_redcap_attr(el, "SliderLabelMid", field.slider_mid_label)
    _set_redcap_attr(el, "SliderLabelMax", field.slider_max_label)

    _translated(el, "Question", field.label)

    for rc in field.range_checks:
        _append_range_check(el, rc)

    if field.code_list_ref:
        clr = etree.SubElement(el, _odm("CodeListRef"))
        clr.set("CodeListOID", field.code_list_ref)


def _append_range_check(parent: etree._Element, rc: RedcapRangeCheck) -> None:
    el = etree.SubElement(parent, _odm("RangeCheck"))
    el.set("Comparator", rc.comparator)
    el.set("SoftHard", rc.soft_hard)
    cv = etree.SubElement(el, _odm("CheckValue"))
    cv.text = rc.value
    if rc.error_message:
        _translated(el, "ErrorMessage", rc.error_message)


def _append_code_list(parent: etree._Element, cl: RedcapCodeList) -> None:
    el = etree.SubElement(parent, _odm("CodeList"))
    el.set("OID", cl.oid)
    el.set("Name", cl.name)
    el.set("DataType", cl.data_type)
    _set_redcap_attr(el, "Variable", cl.variable)
    for item in cl.items:
        li = etree.SubElement(el, _odm("CodeListItem"))
        li.set("CodedValue", item.coded_value)
        _translated(li, "Decode", item.decode)


__all__ = ["build_redcap_xml", "dump_redcap_xml", "dumps_redcap_xml"]
