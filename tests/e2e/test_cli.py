"""End-to-end CLI tests using Typer's ``CliRunner``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from surveywizard.cli import app


@pytest.fixture(scope="module")
def runner() -> CliRunner:
    return CliRunner()


class TestVersion:
    def test_version_flag(self, runner: CliRunner) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "surveywizard" in result.stdout
        assert "0.1.0" in result.stdout

    def test_no_args_shows_help(self, runner: CliRunner) -> None:
        result = runner.invoke(app, [])
        # Typer exits with 0 or 2 depending on help flow; we just need output
        assert "Usage" in result.stdout or "Usage" in (result.stderr or "")


class TestValidate:
    def test_validate_redcap_fixture(
        self, runner: CliRunner, redcap_example_xml: Path
    ) -> None:
        result = runner.invoke(app, ["validate", str(redcap_example_xml)])
        assert result.exit_code == 0
        assert "Valid REDCap" in result.stdout

    def test_validate_qsf_fixture(
        self, runner: CliRunner, qualtrics_fixtures: Path
    ) -> None:
        conjoint = qualtrics_fixtures / "conjoint.qsf"
        result = runner.invoke(app, ["validate", str(conjoint)])
        assert result.exit_code == 0
        assert "Valid QSF" in result.stdout

    def test_validate_bad_file(self, runner: CliRunner, tmp_path: Path) -> None:
        bad = tmp_path / "garbage.xml"
        bad.write_text("<not-odm/>")
        result = runner.invoke(app, ["validate", str(bad)])
        assert result.exit_code == 1


class TestInfo:
    def test_info_redcap(self, runner: CliRunner, redcap_example_xml: Path) -> None:
        result = runner.invoke(app, ["info", str(redcap_example_xml)])
        assert result.exit_code == 0
        assert "field_count" in result.stdout.lower() or "Field" in result.stdout

    def test_info_json(self, runner: CliRunner, redcap_example_xml: Path) -> None:
        result = runner.invoke(app, ["info", str(redcap_example_xml), "-f", "json"])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["field_count"] == 50

    def test_info_preview_json(
        self, runner: CliRunner, qualtrics_fixtures: Path
    ) -> None:
        conjoint = qualtrics_fixtures / "conjoint.qsf"
        result = runner.invoke(
            app, ["info", str(conjoint), "-f", "json", "--preview-to", "redcap"]
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["preview"]["target_format"] == "redcap"
        assert payload["preview"]["report_counts"]["warning"] >= 1
        assert payload["preview"]["overwrite_risk"]["requires_force"] is False


class TestConvert:
    def test_redcap_to_qualtrics(
        self, runner: CliRunner, redcap_example_xml: Path, tmp_path: Path
    ) -> None:
        out_path = tmp_path / "out.qsf"
        report_path = tmp_path / "out.report.md"
        result = runner.invoke(
            app,
            [
                "convert", str(redcap_example_xml),
                "-o", str(out_path),
                "--report", str(report_path),
                "--seed", "42",
            ],
        )
        assert result.exit_code == 0, result.stdout + (result.stderr or "")
        assert out_path.exists()
        with open(out_path, encoding="utf-8") as fp:
            data = json.load(fp)
        assert "SurveyEntry" in data
        assert "SurveyElements" in data
        assert report_path.exists()
        md = report_path.read_text(encoding="utf-8")
        assert "SurveyWizard Conversion Report" in md

    def test_qualtrics_to_redcap(
        self, runner: CliRunner, qualtrics_fixtures: Path, tmp_path: Path
    ) -> None:
        conjoint = qualtrics_fixtures / "conjoint.qsf"
        out_path = tmp_path / "out.xml"
        result = runner.invoke(
            app, ["convert", str(conjoint), "-o", str(out_path)]
        )
        assert result.exit_code == 0
        assert out_path.exists()
        content = out_path.read_text(encoding="utf-8")
        assert '<ODM' in content
        assert 'xmlns:redcap="https://projectredcap.org"' in content

    def test_auto_report_written_for_problematic_conversion(
        self, runner: CliRunner, qualtrics_fixtures: Path, tmp_path: Path
    ) -> None:
        conjoint = qualtrics_fixtures / "conjoint.qsf"
        out_path = tmp_path / "out.xml"
        result = runner.invoke(app, ["convert", str(conjoint), "-o", str(out_path)])
        assert result.exit_code == 0
        auto_report = tmp_path / "out.report.md"
        assert auto_report.exists()
        assert "flow node ignored" in auto_report.read_text(encoding="utf-8")

    def test_existing_output_requires_force(
        self, runner: CliRunner, redcap_example_xml: Path, tmp_path: Path
    ) -> None:
        out_path = tmp_path / "out.qsf"
        out_path.write_text("placeholder", encoding="utf-8")
        result = runner.invoke(
            app,
            ["convert", str(redcap_example_xml), "-o", str(out_path), "--seed", "7"],
        )
        assert result.exit_code == 3
        assert "already exists" in (result.stdout + (result.stderr or ""))
        assert out_path.read_text(encoding="utf-8") == "placeholder"

    def test_force_overwrites_existing_output(
        self, runner: CliRunner, redcap_example_xml: Path, tmp_path: Path
    ) -> None:
        out_path = tmp_path / "out.qsf"
        out_path.write_text("placeholder", encoding="utf-8")
        result = runner.invoke(
            app,
            ["convert", str(redcap_example_xml), "-o", str(out_path), "--seed", "7", "--force"],
        )
        assert result.exit_code == 0
        data = json.loads(out_path.read_text(encoding="utf-8"))
        assert "SurveyEntry" in data

    def test_strict_fails_on_warnings(
        self, runner: CliRunner, qualtrics_fixtures: Path, tmp_path: Path
    ) -> None:
        # conjoint includes unsupported flow nodes and approximation warnings
        conjoint = qualtrics_fixtures / "conjoint.qsf"
        out_path = tmp_path / "out.xml"
        result = runner.invoke(
            app, ["convert", str(conjoint), "-o", str(out_path), "--strict"]
        )
        assert result.exit_code == 2


class TestWizard:
    def test_wizard_happy_path(
        self, runner: CliRunner, redcap_example_xml: Path, tmp_path: Path
    ) -> None:
        out_path = tmp_path / "wizard-out.qsf"
        result = runner.invoke(
            app,
            ["wizard", "-i", str(redcap_example_xml), "-o", str(out_path)],
            input="1\n2\nn\ny\n",
        )
        assert result.exit_code == 0, result.stdout + (result.stderr or "")
        assert "SurveyWizard Wizard" in result.stdout
        assert out_path.exists()
