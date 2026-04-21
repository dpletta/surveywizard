"""Unit tests for the REDCap XML writer and round-trip fidelity."""

from __future__ import annotations

from pathlib import Path

from surveywizard.redcap.reader import parse_redcap_xml
from surveywizard.redcap.writer import build_redcap_xml, dumps_redcap_xml


class TestWriter:
    def test_namespaces_declared(self) -> None:
        from tests.unit.test_redcap_reader import MINIMAL_XML

        project = parse_redcap_xml(MINIMAL_XML)
        out = dumps_redcap_xml(project, pretty=False)
        assert b'xmlns="http://www.cdisc.org/ns/odm/v1.3"' in out
        assert b'xmlns:redcap="https://projectredcap.org"' in out

    def test_round_trip_minimal(self) -> None:
        from tests.unit.test_redcap_reader import MINIMAL_XML

        original = parse_redcap_xml(MINIMAL_XML)
        xml = dumps_redcap_xml(original)
        reparsed = parse_redcap_xml(xml)

        assert reparsed.file_oid == original.file_oid
        assert reparsed.globals.study_name == original.globals.study_name
        assert len(reparsed.fields) == len(original.fields)
        assert len(reparsed.code_lists) == len(original.code_lists)
        assert len(reparsed.events) == len(original.events)

    def test_field_types_preserved(self) -> None:
        from tests.unit.test_redcap_reader import MINIMAL_XML

        original = parse_redcap_xml(MINIMAL_XML)
        xml = dumps_redcap_xml(original)
        reparsed = parse_redcap_xml(xml)

        for original_field in original.fields:
            reparsed_field = reparsed.field_by_oid(original_field.oid)
            assert reparsed_field is not None
            assert reparsed_field.field_type == original_field.field_type
            assert reparsed_field.validation_type == original_field.validation_type
            assert reparsed_field.required == original_field.required
            assert reparsed_field.identifier == original_field.identifier
            assert reparsed_field.branching_logic == original_field.branching_logic

    def test_code_list_items_preserved(self) -> None:
        from tests.unit.test_redcap_reader import MINIMAL_XML

        original = parse_redcap_xml(MINIMAL_XML)
        xml = dumps_redcap_xml(original)
        reparsed = parse_redcap_xml(xml)

        for cl in original.code_lists:
            r_cl = reparsed.code_list_by_oid(cl.oid)
            assert r_cl is not None
            assert [i.coded_value for i in r_cl.items] == [i.coded_value for i in cl.items]
            assert [i.decode for i in r_cl.items] == [i.decode for i in cl.items]

    def test_range_checks_preserved(self) -> None:
        from tests.unit.test_redcap_reader import MINIMAL_XML

        original = parse_redcap_xml(MINIMAL_XML)
        xml = dumps_redcap_xml(original)
        reparsed = parse_redcap_xml(xml)

        age_orig = original.field_by_variable("age")
        age_re = reparsed.field_by_variable("age")
        assert age_orig is not None and age_re is not None
        assert len(age_re.range_checks) == len(age_orig.range_checks) == 2

    def test_round_trip_full_fixture(self, redcap_example_xml: Path) -> None:
        original = parse_redcap_xml(redcap_example_xml)
        xml = dumps_redcap_xml(original)
        reparsed = parse_redcap_xml(xml)

        assert len(reparsed.fields) == len(original.fields)
        assert len(reparsed.code_lists) == len(original.code_lists)
        assert len(reparsed.instruments) == len(original.instruments)
        assert len(reparsed.events) == len(original.events)

        # Field-by-field invariants
        for of in original.fields:
            rf = reparsed.field_by_oid(of.oid)
            assert rf is not None, f"field {of.oid} missing after round-trip"
            assert rf.field_type == of.field_type
            assert rf.variable == of.variable


class TestBuildTree:
    def test_builds_etree_root(self) -> None:
        from tests.unit.test_redcap_reader import MINIMAL_XML

        project = parse_redcap_xml(MINIMAL_XML)
        root = build_redcap_xml(project)
        assert root.tag.endswith("}ODM")
        assert root.get("SourceSystem") == "REDCap"
