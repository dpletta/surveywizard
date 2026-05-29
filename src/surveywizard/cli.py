"""SurveyWizard command-line interface."""

from __future__ import annotations

import contextlib
import json
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from surveywizard import __version__
from surveywizard.errors import ParseError, SurveyWizardError
from surveywizard.pipeline import (
    PreflightResult,
    SurveyFormat,
    default_output_path,
    default_report_path,
    detect_format,
    preflight_conversion,
    summarize_survey,
    write_conversion,
)
from surveywizard.qualtrics.reader import parse_qsf
from surveywizard.redcap.reader import parse_redcap_xml
from surveywizard.report import Level, Report


class Direction(StrEnum):
    REDCAP = "redcap"
    QUALTRICS = "qualtrics"
    AUTO = "auto"


class OutputFormat(StrEnum):
    TABLE = "table"
    JSON = "json"


app = typer.Typer(
    name="surveywizard",
    help="Bidirectional converter between REDCap XML and Qualtrics QSF.",
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
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Print version and exit.",
    ),
) -> None:
    if ctx.invoked_subcommand is None and not version:
        # Bare ``surveywizard`` launches the interactive wizard. ``--help`` and
        # ``--version`` are eager options that exit before reaching this point.
        _run_wizard()
        raise typer.Exit()


def _source_format_for_cli(path: Path) -> SurveyFormat:
    try:
        return detect_format(path)
    except ValueError as err:
        raise typer.BadParameter(str(err), param_hint="INPUT") from err


def _direction_to_format(direction: Direction) -> SurveyFormat | None:
    if direction == Direction.AUTO:
        return None
    return SurveyFormat(direction.value)


def _target_format_for_cli(input_path: Path, direction: Direction) -> SurveyFormat | None:
    target = _direction_to_format(direction)
    if target is None:
        return None

    with contextlib.suppress(ValueError):
        detected = detect_format(input_path)
        if detected == target:
            raise typer.BadParameter(
                f"Input already appears to be {target.value}. Choose the opposite target format.",
                param_hint="--to",
            )
    return target


def _load_summary(input_path: Path) -> tuple[SurveyFormat, dict[str, object]]:
    source_format = _source_format_for_cli(input_path)
    if source_format == SurveyFormat.REDCAP:
        project = parse_redcap_xml(input_path)
        return source_format, summarize_survey(project, source_format)
    survey = parse_qsf(input_path)
    return source_format, summarize_survey(survey, source_format)


def _render_key_value_table(title: str, payload: Mapping[str, object]) -> None:
    table = Table(title=title)
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
        console.print(f"[green]Report:[/] {counts[Level.INFO]} info · no warnings or errors.")


def _render_issue_digest(report: Report) -> None:
    problems = report.problem_items()
    if not problems:
        return

    categories = [
        bucket
        for bucket in report.category_breakdown()
        if bucket["levels"][Level.WARNING.value] or bucket["levels"][Level.ERROR.value]
    ][:5]
    table = Table(title="Likely Sticking Points")
    table.add_column("Category", style="yellow")
    table.add_column("Count", justify="right")
    table.add_column("Affected Fields")
    for bucket in categories:
        fields = ", ".join(bucket["fields"]) if bucket["fields"] else "survey-level"
        table.add_row(
            bucket["category"],
            str(bucket["count"]),
            fields,
        )
    console.print(table)


def _preview_payload(preflight: PreflightResult) -> dict[str, object]:
    counts = preflight.report.counts()
    return {
        "target_format": preflight.target_format.value,
        "recommended_action": preflight.recommended_action.value,
        "planned_output": str(preflight.output_path),
        "planned_report": str(preflight.report_path),
        "report_behavior": (
            "auto-written because issues were detected"
            if preflight.report.has_problems()
            else "only written if you explicitly request one"
        ),
        "overwrite_risk": {
            "output_exists": preflight.output_exists,
            "report_exists": preflight.report_exists,
            "requires_force": preflight.requires_force,
        },
        "estimated_target_shape": preflight.target_summary,
        "report_counts": {
            "info": counts[Level.INFO],
            "warning": counts[Level.WARNING],
            "error": counts[Level.ERROR],
        },
        "top_categories": preflight.report.category_breakdown()[:5],
    }


def _render_preview(preflight: PreflightResult) -> None:
    payload = {
        "target_format": preflight.target_format.value,
        "recommended_action": preflight.recommended_action.value,
        "planned_output": str(preflight.output_path),
        "planned_report": str(preflight.report_path),
        "requires_force": preflight.requires_force,
    }
    _render_key_value_table("Conversion Preview", payload)
    _render_key_value_table(
        f"Estimated {preflight.target_format.value.title()} Output",
        preflight.target_summary,
    )
    _render_report_summary(preflight.report)
    _render_issue_digest(preflight.report)


def _prompt_existing_file(initial: Path | None = None) -> Path:
    default = str(initial) if initial is not None else None
    while True:
        raw = Prompt.ask("Source file", default=default or "")
        path = Path(raw).expanduser()
        if path.exists() and path.is_file():
            return path
        err_console.print(f"[red]File not found:[/] {path}")
        default = None


def _prompt_format(prompt: str, *, default: SurveyFormat | None = None) -> SurveyFormat:
    options = {
        "1": SurveyFormat.REDCAP,
        "2": SurveyFormat.QUALTRICS,
    }
    lines = [
        "1. REDCap XML (.xml)",
        "2. Qualtrics QSF (.qsf/.json)",
    ]
    console.print(Panel.fit("\n".join(lines), title=prompt))
    default_choice = None
    if default is not None:
        default_choice = "1" if default == SurveyFormat.REDCAP else "2"
    choice = Prompt.ask(prompt, choices=["1", "2"], default=default_choice or "1")
    return options[choice]


def _prompt_target_format(source_format: SurveyFormat) -> SurveyFormat:
    other = SurveyFormat.QUALTRICS if source_format == SurveyFormat.REDCAP else SurveyFormat.REDCAP
    lines = [
        "1. REDCap XML (.xml)",
        "2. Qualtrics QSF (.qsf/.json)",
    ]
    console.print(Panel.fit("\n".join(lines), title="Convert To"))
    default_choice = "2" if other == SurveyFormat.QUALTRICS else "1"
    while True:
        choice = Prompt.ask("Target format", choices=["1", "2"], default=default_choice)
        target = SurveyFormat.REDCAP if choice == "1" else SurveyFormat.QUALTRICS
        if target != source_format:
            return target
        err_console.print("[red]Source and target formats must be different.[/]")


def _prompt_output_path(default_path: Path) -> Path:
    raw = Prompt.ask("Output file", default=str(default_path))
    return Path(raw).expanduser()


@app.command()
def convert(
    input_path: Path = typer.Argument(
        ...,
        exists=True,
        dir_okay=False,
        readable=True,
        help="Source file (REDCap .xml or Qualtrics .qsf).",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Destination path. Defaults to sibling file with the other extension.",
    ),
    to: Direction = typer.Option(
        Direction.AUTO,
        "--to",
        help="Target format. AUTO detects from the input extension.",
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Exit non-zero if any warning or error is reported.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite an existing output/report file.",
    ),
    report: Path | None = typer.Option(
        None,
        "--report",
        help="Write a Markdown conversion report to this path. If omitted, one is auto-written when issues are found.",
    ),
    report_json: Path | None = typer.Option(
        None,
        "--report-json",
        help="Write a JSON conversion report to this path.",
    ),
    seed: int | None = typer.Option(
        None,
        "--seed",
        help="Seed the ID minter for reproducible output (REDCap → Qualtrics only).",
    ),
) -> None:
    """Convert a survey between REDCap XML and Qualtrics QSF."""
    target_format = _target_format_for_cli(input_path, to)

    try:
        preflight = preflight_conversion(
            input_path,
            target_format=target_format,
            output_path=output,
            report_path=report,
            seed=seed,
        )
    except ParseError as err:
        err_console.print(f"[red]Parse error:[/] {err}")
        raise typer.Exit(EXIT_PARSE_ERROR) from err
    except ValueError as err:
        raise typer.BadParameter(str(err), param_hint="INPUT") from err
    except SurveyWizardError as err:
        err_console.print(f"[red]Conversion error:[/] {err}")
        raise typer.Exit(EXIT_IO_ERROR) from err

    console.print(
        f"Converting [bold]{input_path}[/] → [bold]{preflight.output_path}[/] "
        f"([cyan]{preflight.source_format.value}[/] → [cyan]{preflight.target_format.value}[/])"
    )
    _render_report_summary(preflight.report)
    _render_issue_digest(preflight.report)

    try:
        write_result = write_conversion(
            preflight,
            force=force,
            markdown_report_path=report,
            json_report_path=report_json,
            always_write_markdown_report=report is not None,
        )
    except SurveyWizardError as err:
        err_console.print(f"[red]Conversion error:[/] {err}")
        raise typer.Exit(EXIT_IO_ERROR) from err

    if write_result.wrote_markdown_report and write_result.report_path is not None:
        console.print(f"[green]✓[/] Report written to [bold]{write_result.report_path}[/]")
    if write_result.wrote_json_report and write_result.report_json_path is not None:
        console.print(f"[green]✓[/] JSON report written to [bold]{write_result.report_json_path}[/]")

    if strict and preflight.report.has_problems():
        err_console.print(
            "[red]--strict:[/] conversion produced warnings or errors — exiting non-zero."
        )
        raise typer.Exit(EXIT_STRICT_DEGRADATION)

    console.print(f"[green]✓[/] Wrote [bold]{write_result.output_path}[/]")


@app.command()
def validate(
    input_path: Path = typer.Argument(
        ...,
        exists=True,
        dir_okay=False,
        readable=True,
        help="File to validate.",
    ),
) -> None:
    """Parse the input and check it conforms to the expected schema."""
    direction = _source_format_for_cli(input_path)
    try:
        if direction == SurveyFormat.REDCAP:
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
    input_path: Path = typer.Argument(
        ...,
        exists=True,
        dir_okay=False,
        readable=True,
        help="File to inspect.",
    ),
    format: OutputFormat = typer.Option(
        OutputFormat.TABLE,
        "--format",
        "-f",
        help="Output format: table or json.",
    ),
    preview_to: Direction = typer.Option(
        Direction.AUTO,
        "--preview-to",
        help="Run an in-memory conversion preview to a target format.",
    ),
    seed: int | None = typer.Option(
        None,
        "--seed",
        help="Seed the preview conversion ids when previewing REDCap → Qualtrics.",
    ),
) -> None:
    """Summarize the file and optionally preview conversion readiness."""
    preview_target = _target_format_for_cli(input_path, preview_to)

    try:
        if preview_target is None:
            direction, payload = _load_summary(input_path)
            preview: PreflightResult | None = None
        else:
            preview = preflight_conversion(input_path, target_format=preview_target, seed=seed)
            direction = preview.source_format
            payload = dict(preview.source_summary)
            payload_json = dict(payload)
            payload_json["preview"] = _preview_payload(preview)
    except ParseError as err:
        err_console.print(f"[red]Parse error:[/] {err}")
        raise typer.Exit(EXIT_PARSE_ERROR) from err
    except ValueError as err:
        raise typer.BadParameter(str(err), param_hint="INPUT") from err

    if format == OutputFormat.JSON:
        if preview is not None:
            console.print_json(json.dumps(payload_json))
        else:
            console.print_json(json.dumps(payload))
        return

    _render_key_value_table(f"{direction.value.title()} survey — {input_path.name}", payload)
    if preview is not None:
        _render_preview(preview)


@app.command()
def wizard(
    input_path: Path | None = typer.Option(
        None,
        "--input",
        "-i",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Optional source file to prefill.",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Optional output file to prefill.",
    ),
    report: Path | None = typer.Option(
        None,
        "--report",
        help="Optional Markdown report path to prefill.",
    ),
    report_json: Path | None = typer.Option(
        None,
        "--report-json",
        help="Optional JSON report path to write.",
    ),
    seed: int | None = typer.Option(
        None,
        "--seed",
        help="Seed the ID minter for reproducible output (REDCap → Qualtrics only).",
    ),
) -> None:
    """Guided interactive conversion wizard."""
    _run_wizard(
        input_path=input_path,
        output=output,
        report=report,
        report_json=report_json,
        seed=seed,
    )


def _run_wizard(
    input_path: Path | None = None,
    output: Path | None = None,
    report: Path | None = None,
    report_json: Path | None = None,
    seed: int | None = None,
) -> None:
    """Run the interactive conversion wizard. Shared by ``wizard`` and bare invocation."""
    console.print(
        Panel.fit(
            "Select the file you have, the format you want, and review likely sticking points "
            "before anything is written.",
            title="SurveyWizard Wizard",
        )
    )

    chosen_input = input_path or _prompt_existing_file()
    detected: SurveyFormat | None = None
    with contextlib.suppress(ValueError):
        detected = detect_format(chosen_input)

    source_format = _prompt_format("What type of file do you have?", default=detected)
    target_format = _prompt_target_format(source_format)
    chosen_output = output or _prompt_output_path(default_output_path(chosen_input, target_format))

    always_write_report = report is not None
    chosen_report = report
    if chosen_report is None and Confirm.ask(
        "Always write a Markdown report, even if the conversion is clean?",
        default=False,
    ):
        chosen_report = _prompt_output_path(default_report_path(chosen_output))
        always_write_report = True

    try:
        preflight = preflight_conversion(
            chosen_input,
            source_format=source_format,
            target_format=target_format,
            output_path=chosen_output,
            report_path=chosen_report,
            seed=seed,
        )
    except ParseError as err:
        err_console.print(f"[red]Parse error:[/] {err}")
        raise typer.Exit(EXIT_PARSE_ERROR) from err
    except ValueError as err:
        err_console.print(f"[red]Configuration error:[/] {err}")
        raise typer.Exit(EXIT_IO_ERROR) from err

    _render_preview(preflight)

    force = False
    if preflight.output_exists:
        force = Confirm.ask(
            f"Output exists at {preflight.output_path}. Overwrite it?",
            default=False,
        )
        if not force:
            err_console.print("[yellow]Cancelled.[/]")
            raise typer.Exit(EXIT_OK)
    elif preflight.report_exists and (preflight.report.has_problems() or always_write_report):
        force = Confirm.ask(
            f"Report exists at {preflight.report_path}. Overwrite it if needed?",
            default=False,
        )
        if not force:
            err_console.print("[yellow]Cancelled.[/]")
            raise typer.Exit(EXIT_OK)

    if not Confirm.ask("Run this conversion now?", default=True):
        err_console.print("[yellow]Cancelled.[/]")
        raise typer.Exit(EXIT_OK)

    try:
        write_result = write_conversion(
            preflight,
            force=force,
            markdown_report_path=chosen_report,
            json_report_path=report_json,
            always_write_markdown_report=always_write_report,
        )
    except SurveyWizardError as err:
        err_console.print(f"[red]Conversion error:[/] {err}")
        raise typer.Exit(EXIT_IO_ERROR) from err

    console.print(f"[green]✓[/] Wrote [bold]{write_result.output_path}[/]")
    if write_result.report_path is not None:
        console.print(f"[green]✓[/] Report written to [bold]{write_result.report_path}[/]")
    if write_result.report_json_path is not None:
        console.print(f"[green]✓[/] JSON report written to [bold]{write_result.report_json_path}[/]")


if __name__ == "__main__":
    app()
