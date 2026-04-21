# CLI usage

## Install

```bash
pip install surveywizard                  # once published
# or
pip install -e ".[dev]"                   # from the repo
```

## Global options

```
surveywizard --version        # print version and exit
surveywizard --help           # show commands
```

## `convert`

Convert a survey file from one format to the other.

```
surveywizard convert INPUT [OPTIONS]
```

### Arguments

- `INPUT` (path): The source file. REDCap `.xml` or Qualtrics `.qsf` / `.json`.

### Options

- `-o, --output PATH` — destination file. Defaults to sibling with the other extension (`study.xml` → `study.qsf`).
- `--to [redcap|qualtrics|auto]` — target format. `auto` (default) infers from the input extension.
- `--strict` — exit non-zero (code 2) if the conversion produces any warning or error. Useful in CI.
- `--force` — allow overwriting an existing output or report file.
- `--report PATH` — write a sidecar Markdown conversion report to this path. If omitted, SurveyWizard auto-writes one when warnings or errors are detected.
- `--report-json PATH` — write the structured JSON report to this path.
- `--seed N` — seed the Qualtrics ID minter for reproducible output (REDCap → Qualtrics direction only).

### Examples

```bash
# Bare minimum: auto-detect + auto-output
surveywizard convert study.xml

# Explicit output + sidecar report
surveywizard convert study.xml -o /tmp/study.qsf --report /tmp/study.report.md

# Reverse direction
surveywizard convert my_qualtrics.qsf -o my_qualtrics.xml

# Override auto-detection (rare; only for ambiguous extensions)
surveywizard convert data.json --to redcap -o data.xml

# Strict mode for CI
surveywizard convert study.xml --strict

# Overwrite an existing output intentionally
surveywizard convert study.xml -o /tmp/study.qsf --force
```

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Parse error — the input is malformed |
| 2 | `--strict` was set and the conversion produced warnings or errors |
| 3 | I/O error writing the output file |

## `wizard`

Guided interactive conversion flow for users who prefer a menu-driven interface.

```
surveywizard wizard [OPTIONS]
```

Typical flow:

1. Select the source file.
2. Choose the file type you have.
3. Choose the file type you want.
4. Confirm or edit the output path.
5. Review the preflight summary and likely sticking points.
6. Confirm overwrite if needed.
7. Run the conversion.

Useful options:

- `-i, --input PATH` — prefill the source file.
- `-o, --output PATH` — prefill the output file.
- `--report PATH` — prefill a Markdown report destination.
- `--report-json PATH` — also write the JSON report.
- `--seed N` — seed reproducible REDCap → Qualtrics IDs.

## `validate`

Parse the input and confirm it conforms to the expected schema. Does **not** write an output file.

```
surveywizard validate INPUT
```

### Examples

```bash
surveywizard validate study.xml
# ✓ Valid REDCap XML — 50 fields, 7 instruments, 7 events.

surveywizard validate broken.xml
# ✗ Invalid: REDCap XML parse error: Document is empty, line 1, column 1
```

## `info`

Print a summary of what the file contains. Useful before committing to a conversion.

```
surveywizard info INPUT [OPTIONS]
```

### Options

- `-f, --format [table|json]` — output format. Default: `table`.
- `--preview-to [redcap|qualtrics|auto]` — run an in-memory conversion preview and show readiness for that target format.
- `--seed N` — seed preview IDs for REDCap → Qualtrics previews.

### Examples

```bash
surveywizard info study.xml
# ╭────────────────────── REDCap survey — study.xml ──────────────────────╮
# │ Property             │ Value                                          │
# ├──────────────────────┼────────────────────────────────────────────────┤
# │ title                │ DemoTrial                                      │
# │ field_count          │ 50                                             │
# │ instruments          │ 7                                              │
# │ events               │ 7                                              │
# │ field_types          │ text:27, select:13, radio:8, textarea:1, ...   │
# │ fields_with_branching│ 4                                              │
# ╰───────────────────────────────────────────────────────────────────────╯

surveywizard info study.xml -f json | jq '.field_types'
# {
#   "text": 27,
#   "select": 13,
#   "radio": 8,
#   ...
# }

surveywizard info study.xml --preview-to qualtrics
# Shows estimated output shape, warning/error counts, overwrite risk,
# and the top likely sticking points before conversion.
```

## The conversion report

When `--report PATH` is passed, SurveyWizard writes a Markdown file describing every field that couldn't be perfectly translated. If `--report` is omitted, SurveyWizard still auto-writes a default `<output>.report.md` file when warnings or errors are detected. Example:

```markdown
# SurveyWizard Conversion Report — redcap→qualtrics

- **Source:** `DemoTrial`
- **Generated:** 2026-04-21 19:58:31Z
- **Totals:** 2 info, 3 warnings, 0 errors

## Details

| Level   | Category                | Field           | From → To                 | Detail                                                      |
|---------|-------------------------|-----------------|---------------------------|-------------------------------------------------------------|
| WARNING | `lossy field mapping`   | `age_group`     | `redcap:calc` → `qsf:DB`  | REDCap calc equations cannot be natively evaluated...       |
| WARNING | `lossy field mapping`   | `site_options`  | `redcap:sql` → `qsf:MC`   | REDCap SQL fields pull options from a database at runtime.  |
| WARNING | `unsupported branch...` | `parent_form`   | `redcap:branching` → ...  | Function call `datediff(...)` has no direct equivalent.     |
```

Legend:

- **INFO** — expected semantic match, logged for traceability.
- **WARNING** — the target approximates the source; review before trusting.
- **ERROR** — the field cannot be represented; the importer may drop or misread it.

Under `--strict`, any warning or error causes exit code 2.

## JSON report output

When `--report-json PATH` is used, SurveyWizard writes a structured payload with:

- report counts by severity
- stable category IDs
- recommended action (`safe`, `review_report`, `manual_cleanup_needed`)
- per-item detail for automation or downstream tooling
