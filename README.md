# SurveyWizard

**Bidirectional command-line converter between REDCap XML and Qualtrics QSF surveys.**

[![CI](https://github.com/dpletta/surveywizard/actions/workflows/ci.yml/badge.svg)](https://github.com/dpletta/surveywizard/actions/workflows/ci.yml)
[![Python versions](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

Export a survey design from one platform, convert it, and import it into the other —
without rebuilding the survey by hand. SurveyWizard handles real-world, high-dimensional
REDCap exports (hundreds of fields, branching logic, matrix groups, events/arms) and
produces a Qualtrics-compatible QSF (and vice versa), with a Markdown conversion report
that lists every degradation.

## Features

- **Full-fidelity round-tripping**: parse → convert → serialize keeps field OIDs, labels,
  codelists, section headers, and matrix groups intact.
- **Branching-logic translation**: REDCap's `[field] = '1' and [age] >= 18` DSL is
  tokenized, parsed into an AST, and emitted as Qualtrics `DisplayLogic` JSON (and the
  reverse direction too).
- **Best-effort approximation with a report**: fields without a clean 1:1 mapping (e.g.
  REDCap `calc`, Qualtrics `WebService` flows) are translated where possible and
  every degradation is listed in a sidecar `.report.md`.
- **Guided conversion wizard**: `surveywizard wizard` walks users through file type
  selection, target format, output path, overwrite confirmation, and a preflight
  review before writing anything.
- **Preflight compatibility preview**: `surveywizard info --preview-to ...` runs an
  in-memory conversion and surfaces likely sticking points, estimated output shape,
  and overwrite risk before the real conversion.
- **Strict mode for CI**: `--strict` exits non-zero when any warning or error is
  reported, so you never silently ship a lossy conversion.
- **Safer output handling**: existing outputs are protected by default; use `--force`
  when you intentionally want to overwrite a file.
- **No surprises on unknown keys**: Pydantic's `extra="allow"` preserves Qualtrics
  internal fields (`NextChoiceId`, `GradingData`, custom `Conjuction` logic) verbatim
  across round-trips.

## Installation

```bash
pip install surveywizard                       # once published to PyPI
# or from source:
git clone https://github.com/dpletta/surveywizard
cd surveywizard
pip install -e ".[dev]"
```

Requires Python 3.11+.

## Quickstart

```bash
# REDCap → Qualtrics (auto-detect direction from extension)
surveywizard convert study.xml

# Qualtrics → REDCap, explicit output + conversion report
surveywizard convert study.qsf -o study.xml --report study.report.md

# Preview what would convert
surveywizard info study.xml

# Preview compatibility before writing anything
surveywizard info study.xml --preview-to qualtrics

# Guided interactive flow
surveywizard wizard

# Strict mode for CI
surveywizard convert study.xml --strict
```

## What it handles

| REDCap | Qualtrics |
|---|---|
| `radio`, `select`, `checkbox`, `yesno`, `truefalse` | `MC` (SAVR/DL/MAVR) |
| `text` + all 20+ `TextValidationType` subtypes | `TE` + `ContentType` validation |
| `textarea` (notes) | `TE` + `ESTB` |
| `slider` | `Slider` / `HSLIDER` |
| `descriptive` | `DB` / `TB` |
| `file` | `FileUpload` |
| Branching logic DSL | `DisplayLogic` JSON |
| Sections (`redcap:SectionHeader`) | Page breaks within a block |
| Matrix groups (`redcap:MatrixGroupName`) | `Matrix` / `Likert` |
| Events / arms | Survey blocks + flow |

Lossy (flagged in the report):
- REDCap `calc` → Qualtrics DB block with equation preserved as text
- REDCap `sql` → Qualtrics dropdown with empty options (manual repopulation needed)
- Qualtrics `WebService` / `Authenticator` / `TableOfContents` flow → dropped (no REDCap analogue)

See [`docs/field-type-mapping.md`](./docs/field-type-mapping.md) for the full table.

## Documentation

- [Field-type mapping](./docs/field-type-mapping.md) — the authoritative translation table
- [Branching logic](./docs/branching-logic.md) — REDCap DSL + Qualtrics DisplayLogic round-trip rules
- [CLI usage](./docs/cli-usage.md) — commands, wizard flow, preview mode, and examples
- [Architecture](./docs/architecture.md) — IR design + module boundaries + extension points
- [Contributing](./CONTRIBUTING.md) — dev setup, testing, release process
- [Changelog](./CHANGELOG.md)

## Why an IR?

SurveyWizard doesn't convert XML directly to JSON. It parses each format into a
typed Pydantic **Intermediate Representation**, then translates between two IRs via
a central type-mapping table and expression translator. This keeps readers, writers,
converters, and tests independent — and leaves the door open for a third format
(SurveyMonkey, LimeSurvey) without a combinatorial explosion of pairwise converters.

## Testing

```bash
pytest                        # 167 tests, ~87% coverage
ruff check src tests
mypy src
```

Real fixtures in `tests/fixtures/` include:

- A 28k-line REDCap project export (50 fields, 7 instruments, 7 events)
- 5 Qualtrics QSF samples covering MC, Matrix/Likert, Sliders, DisplayLogic, Branch, BlockRandomizer

## License

[MIT](./LICENSE) — use it, fork it, ship it.

## Project status

Early beta (v0.1.0). Round-trip fidelity on the core types is strong; edge cases on
exotic REDCap action tags and Qualtrics flow types are now surfaced earlier via
preflight preview, inline CLI summaries, and sidecar reports for manual review.
Bug reports welcome — see [CONTRIBUTING.md](./CONTRIBUTING.md).
