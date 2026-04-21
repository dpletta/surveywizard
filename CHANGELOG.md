# Changelog

All notable changes to SurveyWizard will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Matrix question expansion**: Qualtrics Matrix questions with N rows × M columns now expand into N REDCap fields sharing a matrix_group_name + shared codelist. Likert/SingleAnswer → radio, Likert/MultipleAnswer → checkbox, TE/Profile → text. The first row receives the original question text as its section header so the grouping is visible on import. Surfaced by team_skills.qsf (8 Matrix questions × 13 rows each = 104 new rows) and productivity_experiment.qsf (14 Matrix questions).
- **Display-semantic operators** in the expression translator: Displayed, NotDisplayed, IsEmpty, IsNotEmpty, Answered, NotAnswered, Skipped, NotSkipped. Translated as REDCap presence checks ([var] = ''  / [var] <> '') with an INFO-level report entry explaining the loss of choice-specific semantic. Surfaced by productivity_experiment.qsf (18 previously-dropped NotDisplayed conditions now preserved).
- SBS (side-by-side) questions now emit a dedicated WARNING instead of being conflated with generic matrix loss.

## [0.1.0] — 2026-04-21

### Added

- **Phase 1 — Scaffold**: `pyproject.toml` (Hatchling, Python 3.11–3.13), `src/` layout,
  ruff + mypy + pytest config, GitHub Actions CI (`ci.yml`) and release (`release.yml`)
  workflows, `.gitignore`, exception hierarchy in `errors.py`, and a Typer CLI stub
  with `--version` support.
- **Phase 2 — Fixtures**: Downloaded six real survey files into `tests/fixtures/` —
  one 28k-line REDCap XML export (lsgs/REDCap-API-and-Stata) and five Qualtrics QSF
  samples (leeper/conjoint-example, UWStout/TeamSkillsSurveyGenerator, tszberkowitz,
  ignaciourbina/qualtrics-builder, irenepap2/prompt_based_qa).
- **Phase 3 — IR models**: Pydantic v2 typed models for the common IR
  (`CommonSurvey`, `Field`, `Choice`, `Validation`, `Branching`, …), the REDCap
  domain (`RedcapProject`, `RedcapField`, `RedcapEvent`, `RedcapInstrument`, …),
  and the Qualtrics domain (`QualtricsSurvey`, `SurveyElement`, `Question`, `Block`,
  `FlowNode`, …). `extra="allow"` preserves unknown keys across round-trips.
- **Phase 4 — REDCap XML reader** (`redcap/reader.py`): Parses CDISC ODM 1.3.1 with
  the `redcap:` namespace into a typed `RedcapProject`. Handles all 12 field types,
  events/arms, matrix groups, section headers, range checks, branching-logic strings,
  and synthetic form-complete fields. Verified against the full 28k-line fixture.
- **Phase 5 — REDCap branching-logic parser** (`redcap/expressions.py`): Full
  tokenizer + recursive-descent parser with precedence climbing. Handles field
  references (`[var]`, `[event][var]`, `[var(code)]`), logical operators (`and`,
  `or`, `not`), comparison (`=`, `<>`, `<`, `>`, `<=`, `>=`), arithmetic (`+`, `-`,
  `*`, `/`), function calls (`datediff`, `sum`, `if`, etc.), and parenthesized
  expressions. AST → canonical string round-trip is idempotent.
- **Phase 6 — Qualtrics QSF reader** (`qualtrics/reader.py`): JSON → `QualtricsSurvey`
  with validation. Tolerates the wild-west typing of real QSFs (string/int/bool
  mixing, `null` strings). Preserves unknown keys at every level.
- **Phase 7 — Qualtrics QSF writer + ID minting + DisplayLogic builders**
  (`qualtrics/writer.py`, `qualtrics/ids.py`, `qualtrics/logic.py`): Serializer
  preserves `ChoiceOrder`/`AnswerOrder` + canonical `Conjuction` typo. Seedable
  `IdMinter` mints QID, BL_, FL_, SV_, RS_, UR_, MS_, VE_ IDs per the Qualtrics
  conventions. `logic` module exposes builders for `DisplayLogic` /
  `BranchLogic` / operand URIs.
- **Phase 8 — REDCap XML writer** (`redcap/writer.py`): Emits CDISC ODM 1.3.1 XML
  with correct `xmlns` + `xmlns:redcap` declarations using lxml. Full round-trip
  against the 28k-line example fixture preserves every field and codelist.
- **Phase 9 — Field mapping table** (`converters/field_mapping.py`): 24-row
  bidirectional type-mapping table with `FieldMapping` dataclasses, loss
  annotations, and lookup helpers both directions.
- **Phase 10 — Expression translator** (`converters/expression_translator.py`):
  REDCap AST ↔ Qualtrics DisplayLogic JSON. Handles OR/AND grouping, checkbox
  option refs, comparison operators, and embedded-data references. Unsupported
  constructs (function calls, arithmetic) logged as degradations.
- **Phase 11 — REDCap → Qualtrics converter** (`converters/redcap_to_qualtrics.py`):
  End-to-end pipeline mapping instruments → blocks, sections → page breaks, fields
  → questions. Wires branching logic through the expression translator, assembles
  the full `SurveyElements` array (BL/FL/SO/QC/RS/STAT/SQ), and emits a
  conversion `Report`.
- **Phase 12 — Qualtrics → REDCap converter** (`converters/qualtrics_to_redcap.py`):
  Inverse pipeline. Generates sanitized REDCap variable names, rebuilds codelists
  from QSF Choices, translates DisplayLogic → REDCap branching strings, synthesizes
  a single arm/event grouping every block into an instrument.
- **Phase 13 — Conversion report** (`report.py`): `Report` collects `Degradation`
  records (info/warning/error), renders Markdown with summary stats + per-field
  table + legend. `--strict` mode surfaces warnings/errors as non-zero exit.
- **Phase 14 — CLI** (`cli.py`): Typer app with `convert`, `validate`, and `info`
  commands. Auto-detects direction from file extension, supports `--strict`,
  `--report`, `--seed`, `--format`, and `-o/--output` flags. Rich-formatted
  console output. Exit codes per `docs/cli-usage.md`.
- **Phase 15 — Documentation**: `README.md`, `docs/field-type-mapping.md`,
  `docs/branching-logic.md`, `docs/cli-usage.md`, `docs/architecture.md`,
  `CONTRIBUTING.md`.
- **Phase 16 — Release prep**: rolled `[Unreleased]` into `[0.1.0]`, verified
  `python -m build`, wrote release workflow for tag-triggered PyPI publish +
  GitHub Release.

### Tests

- 167 tests passing (unit + integration + e2e CLI) at ~87% line coverage
- Round-trip fidelity verified against real-world fixtures in both directions
- End-to-end CLI tests via `typer.testing.CliRunner`

### Project tracking

- Linear project `DRP` (SurveyWizard — REDCap↔Qualtrics Converter) with 16 phase issues (`DRP-29`–`DRP-44`).
