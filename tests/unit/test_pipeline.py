"""Unit tests for the shared conversion pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

from surveywizard.errors import PathConflictError
from surveywizard.pipeline import SurveyFormat, preflight_conversion, write_conversion


class TestPreflightConversion:
    def test_redcap_fixture_defaults(self, redcap_example_xml: Path) -> None:
        preflight = preflight_conversion(redcap_example_xml, seed=42)

        assert preflight.source_format == SurveyFormat.REDCAP
        assert preflight.target_format == SurveyFormat.QUALTRICS
        assert preflight.output_path.suffix == ".qsf"
        assert preflight.report_path.name.endswith(".report.md")
        assert preflight.will_write_default_report is False

    def test_write_conversion_auto_writes_problem_report(
        self, qualtrics_fixtures: Path, tmp_path: Path
    ) -> None:
        conjoint = qualtrics_fixtures / "conjoint.qsf"
        out_path = tmp_path / "out.xml"
        preflight = preflight_conversion(conjoint, output_path=out_path)

        result = write_conversion(preflight)

        assert result.output_path.exists()
        assert result.wrote_markdown_report is True
        assert result.report_path == tmp_path / "out.report.md"
        assert result.report_path.exists()

    def test_write_conversion_rejects_input_output_collision(
        self, redcap_example_xml: Path
    ) -> None:
        preflight = preflight_conversion(
            redcap_example_xml,
            target_format=SurveyFormat.QUALTRICS,
            output_path=redcap_example_xml,
        )

        with pytest.raises(PathConflictError, match="overwrite the input"):
            write_conversion(preflight)
