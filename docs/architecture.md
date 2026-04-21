# Architecture

SurveyWizard is a three-layer Python library:

1. **Typed models** — Pydantic v2 representations of REDCap XML, Qualtrics QSF, and a common IR.
2. **Readers / writers** — format-specific parsers and serializers that transform files into typed models (and back).
3. **Converters** — map between REDCap and Qualtrics models via a central field-mapping table + expression translator.

```
        ┌───────────────────┐                  ┌──────────────────────┐
        │   REDCap XML      │                  │   Qualtrics QSF      │
        │  (CDISC ODM 1.3.1 │                  │   (JSON, undocumented)│
        └─────────┬─────────┘                  └──────────┬───────────┘
                  │                                       │
            redcap/reader                          qualtrics/reader
                  │                                       │
                  ▼                                       ▼
        ┌───────────────────┐    converters    ┌──────────────────────┐
        │   RedcapProject   │ <──────────────> │   QualtricsSurvey    │
        │      (typed)      │   (field_mapping │       (typed)        │
        └─────────┬─────────┘    + expr_trans) └──────────┬───────────┘
                  │                                       │
            redcap/writer                          qualtrics/writer
                  │                                       │
                  ▼                                       ▼
        ┌───────────────────┐                  ┌──────────────────────┐
        │   REDCap XML      │                  │   Qualtrics QSF      │
        └───────────────────┘                  └──────────────────────┘
```

## Package layout

```
src/surveywizard/
├── __init__.py                # __version__
├── __main__.py                # python -m surveywizard
├── cli.py                     # Typer app (convert / validate / info)
├── errors.py                  # exception hierarchy
├── report.py                  # Report + Degradation + Markdown renderer
├── models/
│   ├── common.py              # CommonSurvey IR (pivot for future formats)
│   ├── redcap.py              # RedcapProject / RedcapField / ...
│   └── qualtrics.py           # QualtricsSurvey / Question / Block / Flow
├── redcap/
│   ├── reader.py              # ODM XML → RedcapProject (lxml)
│   ├── writer.py              # RedcapProject → ODM XML
│   ├── field_types.py         # enum + namespace constants
│   └── expressions.py         # tokenizer + parser + AST for branching logic
├── qualtrics/
│   ├── reader.py              # QSF JSON → QualtricsSurvey
│   ├── writer.py              # QualtricsSurvey → QSF JSON
│   ├── ids.py                 # QID/BL_/FL_ etc. minters
│   └── logic.py               # DisplayLogic / BranchLogic builders
└── converters/
    ├── field_mapping.py       # central bidirectional type-mapping table
    ├── expression_translator.py  # REDCap AST ↔ QSF DisplayLogic
    ├── redcap_to_qualtrics.py # orchestrator: RedcapProject → QualtricsSurvey
    └── qualtrics_to_redcap.py # orchestrator: QualtricsSurvey → RedcapProject
```

## Why an IR?

An intermediate representation isolates each concern:

- **Readers** only need to understand one file format.
- **Writers** only need to understand one file format.
- **Converters** work on typed objects, never strings or XML trees.
- **Tests** can exercise each layer independently — bad input goes in, typed objects come out; typed objects go in, bad output (or a report entry) comes out.

A third format (e.g. SurveyMonkey, LimeSurvey) could be added by building one reader + one writer + one converter pair that touches the IR — no touching of the existing REDCap or Qualtrics code.

## Extension points

- **New field type**: add a row to `converters/field_mapping.TABLE`, plus a branch in `redcap_to_qualtrics.RedcapToQualtrics._convert_field` if the field needs special handling (e.g. yesno → synthetic choice list).
- **New validation type**: add an enum entry in `models/redcap.RedcapValidationType` and a mapping row.
- **New Qualtrics question type**: add to `models/qualtrics.QuestionType` and, if needed, loosen the Pydantic models to accept its payload shape.
- **New branching-logic function**: extend `redcap/expressions.py`'s tokenizer / parser (if the syntax is novel) and `converters/expression_translator.py` to emit a sensible Qualtrics approximation.

## Error handling

All SurveyWizard errors inherit from `SurveyWizardError`:

- `ParseError` — malformed source file
- `ConversionError` — base for converter failures
  - `UnsupportedFieldError` — raised in `--strict` mode when a field can't be mapped
- `ExpressionError` — branching-logic tokenizer/parser failure

Readers wrap low-level library errors (`lxml.etree.XMLSyntaxError`, `json.JSONDecodeError`, `pydantic.ValidationError`) into `ParseError` so callers see one exception type.

## Why Pydantic v2?

- Schema validation at load time catches malformed inputs early.
- `extra="allow"` at every level preserves unknown keys for round-trip fidelity.
- Models double as typed intermediate data structures (no ad-hoc dicts flowing through the code).
- `model_dump(mode="json")` produces JSON-safe outputs for the QSF writer.

## Testing philosophy

- **Unit tests** exercise each module in isolation with hand-crafted minimal inputs.
- **Integration tests** drive the readers, writers, and converters against real fixtures downloaded from public open-source repos.
- **End-to-end tests** invoke the CLI with `typer.testing.CliRunner` and check output files exist and are valid.
- **Round-trip tests** assert that `parse(write(parse(x)))` produces a semantically equivalent object — catching serializer bugs that would quietly corrupt data.
