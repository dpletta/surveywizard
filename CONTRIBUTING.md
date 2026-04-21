# Contributing

Thanks for your interest in SurveyWizard!

## Development setup

```bash
git clone https://github.com/dpletta/surveywizard
cd surveywizard
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Running the test suite

```bash
pytest                              # full suite with coverage
pytest tests/unit                   # unit tests only
pytest tests/integration            # integration tests
pytest tests/e2e                    # CLI end-to-end tests
pytest -k "expression"              # match by name
```

If `pytest` is not on your `PATH`, run the venv-local binary instead:

```bash
.venv/bin/pytest
```

Target coverage is >85% overall, >95% on converters/ and models/.

## Lint and type-check

```bash
ruff check src tests                # static checks
ruff format src tests               # auto-format
mypy src                            # strict type checking
```

## Adding a new field-type mapping

1. Add the enum value to `src/surveywizard/models/redcap.py::RedcapFieldType` or `src/surveywizard/models/qualtrics.py::QuestionType`.
2. Add a row to `src/surveywizard/converters/field_mapping.TABLE`.
3. Update `docs/field-type-mapping.md`.
4. Add a round-trip test in `tests/integration/test_converters.py`.
5. Add a `CHANGELOG.md` entry under `[Unreleased]`.

## Adding a new fixture

Publicly-licensed (MIT / BSD / CC-BY / public-domain) only. Drop the file into `tests/fixtures/redcap/` or `tests/fixtures/qualtrics/` and add a note to the fixture's provenance in `docs/architecture.md`.

## Commit & PR conventions

- Keep PRs focused — one feature or bugfix per PR.
- Each PR must pass CI (`ci.yml`) — ruff + mypy + pytest on Python 3.11, 3.12, 3.13.
- Reference the Linear issue (e.g. `DRP-42`) in the commit message or PR description when available.
- Update `CHANGELOG.md`'s `[Unreleased]` section.

## Release process

See [docs/architecture.md](./docs/architecture.md) for the high-level layout.

Releases are triggered by pushing a semver tag:

```bash
# 1. Roll Unreleased → vX.Y.Z in CHANGELOG.md, set today's date
# 2. Commit the CHANGELOG update
git commit -am "release: vX.Y.Z"
git tag vX.Y.Z
git push origin main --tags
```

CI's `release.yml` then builds wheel + sdist, publishes to PyPI, and creates a GitHub Release.

## Reporting bugs

Please include:

1. The exact command you ran.
2. The input file (or a minimal reproducer).
3. The generated `.report.md` if any.
4. Python version (`python --version`) and SurveyWizard version (`surveywizard --version`).

## Code of conduct

Be kind. This is volunteer work across research groups — assume good faith.
