"""Unit tests for the REDCap XML reader."""

from __future__ import annotations

from pathlib import Path

import pytest

from surveywizard.errors import ParseError
from surveywizard.models.redcap import RedcapFieldType, RedcapValidationType
from surveywizard.redcap.reader import parse_redcap_xml

MINIMAL_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<ODM xmlns="http://www.cdisc.org/ns/odm/v1.3"
     xmlns:redcap="https://projectredcap.org"
     ODMVersion="1.3.1" FileOID="test-1" CreationDateTime="2026-04-21T00:00:00"
     SourceSystem="REDCap" SourceSystemVersion="13.0">
  <Study OID="Project.Test">
    <GlobalVariables>
      <StudyName>Test Study</StudyName>
      <redcap:RecordAutonumberingEnabled>y</redcap:RecordAutonumberingEnabled>
      <redcap:Purpose>0</redcap:Purpose>
    </GlobalVariables>
    <MetaDataVersion OID="Metadata.Test" Name="Metadata" redcap:RecordIdField="subject_id">
      <StudyEventDef OID="Event.baseline" Name="Event 1"
                     redcap:UniqueEventName="baseline_arm_1"
                     redcap:EventName="Baseline" redcap:ArmNum="1"
                     Repeating="No" Type="Common">
        <FormRef FormOID="Form.demographics"/>
      </StudyEventDef>
      <FormDef OID="Form.demographics" Name="demographics" redcap:FormName="demographics">
        <ItemGroupRef ItemGroupOID="Group.demographics"/>
      </FormDef>
      <ItemGroupDef OID="Group.demographics" Name="demographics">
        <ItemRef ItemOID="age" redcap:Variable="age" Mandatory="Yes"/>
        <ItemRef ItemOID="sex" redcap:Variable="sex" Mandatory="No"/>
        <ItemRef ItemOID="consent" redcap:Variable="consent" Mandatory="Yes"/>
      </ItemGroupDef>
      <ItemDef OID="age" Name="age" DataType="integer" Length="3"
               redcap:Variable="age" redcap:FieldType="text"
               redcap:TextValidationType="int" redcap:RequiredField="y"
               redcap:FieldNote="(0-120)">
        <Question><TranslatedText>Age in years</TranslatedText></Question>
        <RangeCheck Comparator="GE" SoftHard="Soft">
          <CheckValue>0</CheckValue>
          <ErrorMessage><TranslatedText>Must be non-negative</TranslatedText></ErrorMessage>
        </RangeCheck>
        <RangeCheck Comparator="LE" SoftHard="Soft">
          <CheckValue>120</CheckValue>
          <ErrorMessage><TranslatedText>Must be under 120</TranslatedText></ErrorMessage>
        </RangeCheck>
      </ItemDef>
      <ItemDef OID="sex" Name="sex" DataType="text" Length="1"
               redcap:Variable="sex" redcap:FieldType="radio">
        <Question><TranslatedText>Sex</TranslatedText></Question>
        <CodeListRef CodeListOID="sex.choices"/>
      </ItemDef>
      <ItemDef OID="consent" Name="consent" DataType="text" Length="1"
               redcap:Variable="consent" redcap:FieldType="yesno"
               redcap:BranchingLogic="[age] &gt;= 18"
               redcap:Identifier="y">
        <Question><TranslatedText>Consent to participate?</TranslatedText></Question>
      </ItemDef>
      <CodeList OID="sex.choices" Name="sex" DataType="text" redcap:Variable="sex">
        <CodeListItem CodedValue="1"><Decode><TranslatedText>Male</TranslatedText></Decode></CodeListItem>
        <CodeListItem CodedValue="2"><Decode><TranslatedText>Female</TranslatedText></Decode></CodeListItem>
        <CodeListItem CodedValue="3"><Decode><TranslatedText>Other</TranslatedText></Decode></CodeListItem>
      </CodeList>
    </MetaDataVersion>
  </Study>
</ODM>
"""


class TestMinimalParse:
    def test_parses_top_level_metadata(self) -> None:
        p = parse_redcap_xml(MINIMAL_XML)
        assert p.file_oid == "test-1"
        assert p.source_system == "REDCap"
        assert p.source_version == "13.0"
        assert p.record_id_field == "subject_id"

    def test_parses_globals(self) -> None:
        p = parse_redcap_xml(MINIMAL_XML)
        assert p.globals.study_name == "Test Study"
        assert p.globals.record_autonumbering_enabled is True
        assert p.globals.purpose == "0"

    def test_parses_event(self) -> None:
        p = parse_redcap_xml(MINIMAL_XML)
        assert len(p.events) == 1
        e = p.events[0]
        assert e.name == "baseline_arm_1"
        assert e.label == "Baseline"
        assert e.arm_num == 1
        assert e.form_refs == ["Form.demographics"]

    def test_parses_instrument(self) -> None:
        p = parse_redcap_xml(MINIMAL_XML)
        assert len(p.instruments) == 1
        inst = p.instruments[0]
        assert inst.name == "demographics"
        assert inst.item_group_oids == ["Group.demographics"]

    def test_parses_item_group(self) -> None:
        p = parse_redcap_xml(MINIMAL_XML)
        assert len(p.item_groups) == 1
        ig = p.item_groups[0]
        assert ig.item_oids == ["age", "sex", "consent"]

    def test_parses_text_field_with_validation(self) -> None:
        p = parse_redcap_xml(MINIMAL_XML)
        age = p.field_by_variable("age")
        assert age is not None
        assert age.field_type == RedcapFieldType.TEXT
        assert age.validation_type == RedcapValidationType.INT
        assert age.required is True
        assert age.field_note == "(0-120)"
        assert age.data_type == "integer"
        assert len(age.range_checks) == 2
        assert age.range_checks[0].comparator == "GE"
        assert age.range_checks[0].value == "0"

    def test_parses_radio_with_codelist(self) -> None:
        p = parse_redcap_xml(MINIMAL_XML)
        sex = p.field_by_variable("sex")
        assert sex is not None
        assert sex.field_type == RedcapFieldType.RADIO
        assert sex.code_list_ref == "sex.choices"
        cl = p.code_list_by_oid("sex.choices")
        assert cl is not None
        assert len(cl.items) == 3
        assert cl.items[0].coded_value == "1"
        assert cl.items[0].decode == "Male"

    def test_parses_yesno_with_branching(self) -> None:
        p = parse_redcap_xml(MINIMAL_XML)
        consent = p.field_by_variable("consent")
        assert consent is not None
        assert consent.field_type == RedcapFieldType.YESNO
        assert consent.branching_logic == "[age] >= 18"
        assert consent.identifier is True


class TestErrorHandling:
    def test_invalid_xml_raises_parse_error(self) -> None:
        with pytest.raises(ParseError):
            parse_redcap_xml(b"<not-odm/>")

    def test_non_odm_root_raises(self) -> None:
        with pytest.raises(ParseError, match="Expected root"):
            parse_redcap_xml(b'<?xml version="1.0"?><something/>')

    def test_malformed_xml_raises(self) -> None:
        with pytest.raises(ParseError, match="parse error"):
            parse_redcap_xml(b"<ODM><Study></ODM>")


class TestExampleFixture:
    """Parse the real REDCap fixture downloaded in phase 2."""

    def test_parses_full_fixture(self, redcap_example_xml: Path) -> None:
        p = parse_redcap_xml(redcap_example_xml)

        assert p.source_system == "REDCap"
        assert len(p.fields) == 50
        assert len(p.code_lists) == 21
        assert len(p.instruments) == 7
        assert len(p.events) == 7

    def test_fixture_has_expected_field_types(self, redcap_example_xml: Path) -> None:
        p = parse_redcap_xml(redcap_example_xml)
        types: dict[str, int] = {}
        for f in p.fields:
            types[f.field_type.value] = types.get(f.field_type.value, 0) + 1
        assert types["text"] >= 20
        assert types["radio"] >= 5
        assert types["select"] >= 5

    def test_fixture_has_branching_logic(self, redcap_example_xml: Path) -> None:
        p = parse_redcap_xml(redcap_example_xml)
        with_branching = [f for f in p.fields if f.branching_logic]
        assert len(with_branching) >= 2

    def test_fixture_has_code_list_links(self, redcap_example_xml: Path) -> None:
        p = parse_redcap_xml(redcap_example_xml)
        fields_with_cl = [f for f in p.fields if f.code_list_ref]
        assert len(fields_with_cl) >= 5
        for f in fields_with_cl:
            assert p.code_list_by_oid(f.code_list_ref) is not None
