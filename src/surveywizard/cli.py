"""SurveyWizard command-line interface."""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from rich.console import Console
from rich.table import Table

from surveywizard import __version__
from surveywizard.converters.qualtrics_to_redcap import convert_qualtrics_to_redcap
from surveywizard.converters.redcap_to_qualtrics import convert_redcap_to_qualtrics
from surveywizard.errors import ParseError, SurveyWizardError
from surveywizard.qualtrics.reader import parse_qsf
from surveywizard.qualtrics.writer import dump_qsf
from surveywizard.redcap.reader import parse_redcap_xml
from surveywizard.redcap.writer import dump_redcap_xml
from surveywizard.report import Level, Report

if TYPE_CHECKING:
    from surveywizard.models.qualtrics import QualtricsSurvey
    from surveywizard.models.redcap import RedcapProject


class Direction(StrEnum):
    REDCAP = "redcap"
    QUALTRICS = "qualtrics"
    AUTO = "auto"


app = typer.Typer(
    name="surveywizard",
    help="Bidirectional converter between REDCap XML and Qualtrics QSF.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()
err_console = Console(stderr=True)


EXIT_OK = 0
EXIT_PARSE_ERROR = 1
EXIT_STRICT_DEGRADATION = 2
EXIT_IO_ERROR = 3


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"surveywizard {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version: bool = typer.Option(
        False, "--version", "-V",
        callback=_version_callback, is_eager=True,
        help="Print version and exit.",
    ),
) -> None:
    if ctx.invoked_subcommand is None and not version:
        typer.echo(ctx.get_help())
        raise typer.Exit()


def _detect_direction(path: Path) -> Direction:
    suffix = path.suffix.lower()
    if suffix in {".xml"}:
        return Direction.REDCAP
    if suffix in {".qsf", ".json"}:
        return Direction.QUALTRICS
    raise typer.BadParameter(
        f"Cannot auto-detect direction from extension {suffix!r}. "
        "Pass --to redcap|qualtrics explicitly.",
        param_hint="INPUT",
    )


def _default_output(input_path: Path, target_direction: Direction) -> Path:
    stem = input_path.stem
    if target_direction == Direction.QUALTRICS:
        return input_path.with_name(f"{stem}.qsf")
    return input_path.with_name(f"{stem}.xml")


def _render_report_summary(report: Report) -> None:
    counts = report.counts()
    if counts[Level.WARNING] or counts[Level.ERROR]:
        color = "yellow" if not counts[Level.ERROR] else "red"
        console.print(
            f"[{color}]Report:[/] "
            f"{counts[Level.INFO]} info · "
            f"[yellow]{counts[Level.WARNING]} warnings[/] · "
            f"[red]{counts[Level.ERROR]} errors[/]"
        )
    else:
        console.print(
            f"[green]Report:[/] {counts[Level.INFO]} info · no warnings or errors."
        )


@app.command()
def convert(
    input_path: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True,
                                       help="Source file (REDCap .xml or Qualtrics .qsf)."),
    output: Path | None = typer.Option(
        None, "--output", "-o",
        help="Destination path. Defaults to sibling file with the other extension.",
    ),
    to: Direction = typer.Option(
        Direction.AUTO, "--to",
        help="Target format. AUTO detects from the input extension.",
    ),
    strict: bool = typer.Option(
        False, "--strict",
        help="Exit non-zero if any warning or error is reported.",
    ),
    report: Path | None = typer.Option(
        None, "--report",
        help="Write a Markdown conversion report to this path.",
    ),
    seed: int | None = typer.Option(
        None, "--seed",
        help="Seed the ID minter for reproducible output (REDCap → Qualtrics only).",
    ),
) -> None:
    """Convert a survey between REDCap XML and Qualtrics QSF."""
    source_direction = _detect_direction(input_path) if to == Direction.AUTO else (
        Direction.QUALTRICS if to == Direction.REDCAP else Direction.REDCAP
    )
    target_direction = (
        Direction.QUALTRICS if source_direction == Direction.REDCAP else Direction.REDCAP
    )
    if output is None:
        output = _default_output(input_path, target_direction)

    console.print(
        f"Converting [bold]{input_path}[/] → [bold]{output}[/] "
        f"([cyan]{source_direction.value}[/] → [cyan]{target_direction.value}[/])"
    )

    try:
        if source_direction == Direction.REDCAP:
            project = parse_redcap_xml(input_path)
            survey, conversion_report = convert_redcap_to_qualtrics(project, seed=seed)
            dump_qsf(survey, output)
        else:
            qsf_survey = parse_qsf(input_path)
            reverted_project, conversion_report = convert_qualtrics_to_redcap(qsf_survey)
            dump_redcap_xml(reverted_project, output)
    except ParseError as err:
        err_console.print(f"[red]Parse error:[/] {err}")
        raise typer.Exit(EXIT_PARSE_ERROR) from err
    except SurveyWizardError as err:
        err_console.print(f"[red]Conversion error:[/] {err}")
        raise typer.Exit(EXIT_IO_ERROR) from err

    _render_report_summary(conversion_report)

    if report is not None:
        conversion_report.write(report)
        console.print(f"[green]✓[/] Report written to [bold]{report}[/]")

    if strict and conversion_report.has_problems():
        err_console.print(
            "[red]--strict:[/] conversion produced warnings or errors — exiting non-zero."
        )
        raise typer.Exit(EXIT_STRICT_DEGRADATION)

    console.print(f"[green]✓[/] Wrote [bold]{output}[/]")


@app.command()
def validate(
    input_path: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True,
                                       help="File to validate."),
) -> None:
    """Parse the input and check it conforms to the expected schema."""
    direction = _detect_direction(input_path)
    try:
        if direction == Direction.REDCAP:
            project = parse_redcap_xml(input_path)
            console.print(
                f"[green]✓[/] Valid REDCap XML — "
                f"{len(project.fields)} fields, {len(project.instruments)} instruments, "
                f"{len(project.events)} events."
            )
        else:
            survey = parse_qsf(input_path)
            console.print(
                f"[green]✓[/] Valid QSF — "
                f"{len(survey.questions())} questions, {len(survey.blocks())} blocks."
            )
    except ParseError as err:
        err_console.print(f"[red]✗ Invalid:[/] {err}")
        raise typer.Exit(EXIT_PARSE_ERROR) from err


@app.command()
def info(
    input_path: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True,
                                       help="File to inspect."),
    format: str = typer.Option(
        "table", "--format", "-f",
        help="Output format: table or json.",
    ),
) -> None:
    """Summarize the file's contents and lossy-conversion preview."""
    direction = _detect_direction(input_path)
    try:
        if direction == Direction.REDCAP:
            project = parse_redcap_xml(input_path)
            payload = _info_redcap(project)
        else:
            survey = parse_qsf(input_path)
            payload = _info_qualtrics(survey)
    except ParseError as err:
        err_console.print(f"[red]Parse error:[/] {err}")
        raise typer.Exit(EXIT_PARSE_ERROR) from err

    if format == "json":
        console.print_json(json.dumps(payload))
        return

    table = Table(title=f"{direction.value.title()} survey — {input_path.name}")
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="bold")
    for key, value in payload.items():
        if isinstance(value, dict):
            rendered = ", ".join(f"{k}:{v}" for k, v in value.items())
        elif isinstance(value, list):
            rendered = ", ".join(str(v) for v in value[:10])
            if len(value) > 10:
                rendered += f", ...(+{len(value) - 10})"
        else:
            rendered = str(value)
        table.add_row(key, rendered or "—")
    console.print(table)


def _info_redcap(project: RedcapProject) -> dict[str, object]:
    type_counts: dict[str, int] = {}
    for f in project.fields:
        type_counts[f.field_type.value] = type_counts.get(f.field_type.value, 0) + 1
    branching = sum(1 for f in project.fields if f.branching_logic)
    return {
        "title": project.globals.study_name,
        "field_count": len(project.fields),
        "instruments": len(project.instruments),
        "events": len(project.events),
        "code_lists": len(project.code_lists),
        "field_types": type_counts,
        "fields_with_branching": branching,
        "identifiers": sum(1 for f in project.fields if f.identifier),
        "source": f"{project.source_system} {project.source_version or ''}".strip(),
    }


def _info_qualtrics(survey: QualtricsSurvey) -> dict[str, object]:
    questions = survey.questions()
    type_counts: dict[str, int] = {}
    for q in questions:
        type_counts[q.QuestionType.value] = type_counts.get(q.QuestionType.value, 0) + 1
    return {
        "title": survey.SurveyEntry.SurveyName,
        "survey_id": survey.SurveyEntry.SurveyID,
        "question_count": len(questions),
        "blocks": len(survey.blocks()),
        "question_types": type_counts,
        "has_flow": survey.flow() is not None,
    }


if __name__ == "__main__":
    app()
