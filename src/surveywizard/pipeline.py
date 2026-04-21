"""Shared conversion/preflight pipeline for CLI and interactive workflows."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TypeAlias

from surveywizard.converters.qualtrics_to_redcap import convert_qualtrics_to_redcap
from surveywizard.converters.redcap_to_qualtrics import convert_redcap_to_qualtrics
from surveywizard.errors import PathConflictError
from surveywizard.models.qualtrics import QualtricsSurvey
from surveywizard.models.redcap import RedcapProject
from surveywizard.qualtrics.reader import parse_qsf
from surveywizard.qualtrics.writer import dump_qsf
from surveywizard.redcap.reader import parse_redcap_xml
from surveywizard.redcap.writer import dump_redcap_xml
from surveywizard.report import Level, Report

ParsedSurvey: TypeAlias = RedcapProject | QualtricsSurvey
ConvertedSurvey: TypeAlias = RedcapProject | QualtricsSurvey


class SurveyFormat(StrEnum):
    REDCAP = "redcap"
    QUALTRICS = "qualtrics"


class RecommendedAction(StrEnum):
    SAFE = "safe"
    REVIEW_REPORT = "review_report"
    MANUAL_CLEANUP_NEEDED = "manual_cleanup_needed"


@dataclass(frozen=True)
class PreflightResult:
    input_path: Path
    source_format: SurveyFormat
    target_format: SurveyFormat
    output_path: Path
    report_path: Path
    parsed_source: ParsedSurvey
    converted_survey: ConvertedSurvey
    source_summary: dict[str, object]
    target_summary: dict[str, object]
    report: Report
    recommended_action: RecommendedAction

    @property
    def output_exists(self) -> bool:
        return self.output_path.exists()

    @property
    def report_exists(self) -> bool:
        return self.report_path.exists()

    @property
    def will_write_default_report(self) -> bool:
        return self.report.has_problems()

    @property
    def requires_force(self) -> bool:
        if self.output_exists:
            return True
        return self.will_write_default_report and self.report_exists


@dataclass(frozen=True)
class WriteResult:
    output_path: Path
    report_path: Path | None
    report_json_path: Path | None
    wrote_markdown_report: bool
    wrote_json_report: bool


def detect_format(path: Path) -> SurveyFormat:
    suffix = path.suffix.lower()
    if suffix == ".xml":
        return SurveyFormat.REDCAP
    if suffix in {".qsf", ".json"}:
        return SurveyFormat.QUALTRICS
    raise ValueError(
        f"Cannot auto-detect direction from extension {suffix!r}. "
        "Pass --to redcap|qualtrics explicitly."
    )


def other_format(format_: SurveyFormat) -> SurveyFormat:
    return SurveyFormat.QUALTRICS if format_ == SurveyFormat.REDCAP else SurveyFormat.REDCAP


def default_output_path(input_path: Path, target_format: SurveyFormat) -> Path:
    stem = input_path.stem
    suffix = ".qsf" if target_format == SurveyFormat.QUALTRICS else ".xml"
    return input_path.with_name(f"{stem}{suffix}")


def default_report_path(output_path: Path) -> Path:
    return output_path.with_name(f"{output_path.stem}.report.md")


def summarize_survey(survey: ParsedSurvey, format_: SurveyFormat) -> dict[str, object]:
    if format_ == SurveyFormat.REDCAP:
        project = survey
        assert isinstance(project, RedcapProject)
        type_counts: dict[str, int] = {}
        for field in project.fields:
            type_counts[field.field_type.value] = type_counts.get(field.field_type.value, 0) + 1
        return {
            "title": project.globals.study_name,
            "field_count": len(project.fields),
            "instruments": len(project.instruments),
            "events": len(project.events),
            "code_lists": len(project.code_lists),
            "field_types": type_counts,
            "fields_with_branching": sum(1 for field in project.fields if field.branching_logic),
            "identifiers": sum(1 for field in project.fields if field.identifier),
            "source": f"{project.source_system} {project.source_version or ''}".strip(),
        }

    qsf = survey
    assert isinstance(qsf, QualtricsSurvey)
    questions = qsf.questions()
    question_type_counts: dict[str, int] = {}
    for question in questions:
        question_type_counts[question.QuestionType.value] = (
            question_type_counts.get(question.QuestionType.value, 0) + 1
        )
    return {
        "title": qsf.SurveyEntry.SurveyName,
        "survey_id": qsf.SurveyEntry.SurveyID,
        "question_count": len(questions),
        "blocks": len(qsf.blocks()),
        "question_types": question_type_counts,
        "has_flow": qsf.flow() is not None,
    }


def preflight_conversion(
    input_path: Path,
    *,
    source_format: SurveyFormat | None = None,
    target_format: SurveyFormat | None = None,
    output_path: Path | None = None,
    report_path: Path | None = None,
    seed: int | None = None,
) -> PreflightResult:
    if source_format is not None and target_format is not None:
        if source_format == target_format:
            raise ValueError("Source and target formats must be different.")
        resolved_source = source_format
        resolved_target = target_format
    elif source_format is not None:
        resolved_source = source_format
        resolved_target = other_format(source_format)
    elif target_format is not None:
        resolved_target = target_format
        resolved_source = other_format(target_format)
    else:
        resolved_source = detect_format(input_path)
        resolved_target = other_format(resolved_source)

    resolved_output = output_path or default_output_path(input_path, resolved_target)
    resolved_report = report_path or default_report_path(resolved_output)
    parsed_source: ParsedSurvey
    converted_survey: ConvertedSurvey

    if resolved_source == SurveyFormat.REDCAP:
        parsed_source = parse_redcap_xml(input_path)
        converted_survey, report = convert_redcap_to_qualtrics(parsed_source, seed=seed)
    else:
        parsed_source = parse_qsf(input_path)
        converted_survey, report = convert_qualtrics_to_redcap(parsed_source)

    counts = report.counts()
    if counts[Level.ERROR]:
        action = RecommendedAction.MANUAL_CLEANUP_NEEDED
    elif counts[Level.WARNING]:
        action = RecommendedAction.REVIEW_REPORT
    else:
        action = RecommendedAction.SAFE

    return PreflightResult(
        input_path=input_path,
        source_format=resolved_source,
        target_format=resolved_target,
        output_path=resolved_output,
        report_path=resolved_report,
        parsed_source=parsed_source,
        converted_survey=converted_survey,
        source_summary=summarize_survey(parsed_source, resolved_source),
        target_summary=summarize_survey(converted_survey, resolved_target),
        report=report,
        recommended_action=action,
    )


def write_conversion(
    preflight: PreflightResult,
    *,
    force: bool = False,
    markdown_report_path: Path | None = None,
    json_report_path: Path | None = None,
    always_write_markdown_report: bool = False,
) -> WriteResult:
    report_path = markdown_report_path
    if report_path is None and preflight.report.has_problems():
        report_path = preflight.report_path

    _validate_write_targets(
        input_path=preflight.input_path,
        output_path=preflight.output_path,
        markdown_report_path=report_path,
        json_report_path=json_report_path,
        force=force,
    )

    preflight.output_path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(preflight.converted_survey, QualtricsSurvey):
        dump_qsf(preflight.converted_survey, preflight.output_path)
    else:
        dump_redcap_xml(preflight.converted_survey, preflight.output_path)

    wrote_markdown = False
    if report_path is not None and (
        always_write_markdown_report or preflight.report.has_problems()
    ):
        report_path.parent.mkdir(parents=True, exist_ok=True)
        preflight.report.write(report_path)
        wrote_markdown = True

    wrote_json = False
    if json_report_path is not None:
        json_report_path.parent.mkdir(parents=True, exist_ok=True)
        preflight.report.write_json(json_report_path)
        wrote_json = True

    return WriteResult(
        output_path=preflight.output_path,
        report_path=report_path if wrote_markdown else None,
        report_json_path=json_report_path if wrote_json else None,
        wrote_markdown_report=wrote_markdown,
        wrote_json_report=wrote_json,
    )


def _validate_write_targets(
    *,
    input_path: Path,
    output_path: Path,
    markdown_report_path: Path | None,
    json_report_path: Path | None,
    force: bool,
) -> None:
    input_resolved = input_path.resolve()
    output_resolved = output_path.resolve(strict=False)
    if output_resolved == input_resolved:
        raise PathConflictError("Output path would overwrite the input file.")

    protected_paths = {input_resolved, output_resolved}
    if output_path.exists() and not force:
        raise PathConflictError(
            f"Output path already exists: {output_path}. Pass --force to overwrite it."
        )

    for label, path in (
        ("Markdown report", markdown_report_path),
        ("JSON report", json_report_path),
    ):
        if path is None:
            continue
        resolved = path.resolve(strict=False)
        if resolved in protected_paths:
            raise PathConflictError(f"{label} path must be distinct from the input and output.")
        if path.exists() and not force:
            raise PathConflictError(
                f"{label} path already exists: {path}. Pass --force to overwrite it."
            )


__all__ = [
    "PreflightResult",
    "RecommendedAction",
    "SurveyFormat",
    "WriteResult",
    "default_output_path",
    "default_report_path",
    "detect_format",
    "preflight_conversion",
    "summarize_survey",
    "write_conversion",
]
