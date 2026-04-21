# Field-type mapping

How each REDCap field type is translated to Qualtrics, and vice versa. Lossy conversions are highlighted.

## REDCap → Qualtrics

| REDCap `FieldType` | REDCap validation | Qualtrics `QuestionType` + `Selector` | Qualtrics content type | Notes |
|---|---|---|---|---|
| `radio` | — | `MC` / `SAVR` | — | Codelist items become `Choices` with integer-string keys matching REDCap codes. |
| `select` (dropdown) | — | `MC` / `DL` | — | Same as radio, dropdown selector. |
| `checkbox` | — | `MC` / `MAVR` | — | REDCap `var___code` columns ↔ QSF choice keys preserve per-option codes. |
| `yesno` | — | `MC` / `SAVR` | — | Synthesized `{1: "Yes", 0: "No"}` choice list. |
| `truefalse` | — | `MC` / `SAVR` | — | Synthesized `{1: "True", 0: "False"}` choice list. |
| `text` | _none_ | `TE` / `SL` | `None` | Plain single-line text. |
| `text` | `email` | `TE` / `SL` | `ValidEmailAddress` | |
| `text` | `int` | `TE` / `SL` | `ValidNumber` | RangeCheck bounds copied into `ValidNumber.{Min,Max}`. |
| `text` | `number` / `number_1dp` / `number_2dp` | `TE` / `SL` | `ValidNumber` | `NumDecimals` set from the suffix. |
| `text` | `phone` | `TE` / `SL` | `ValidUSPhone` | US format default; override manually for intl surveys. |
| `text` | `zipcode` | `TE` / `SL` | `ValidUSZip` | |
| `text` | `date_*` | `TE` / `SL` | `ValidDate` | Format token loss — Qualtrics uses its own date-format tokens. |
| `text` | `datetime_*` | `TE` / `SL` | `ValidDate` | Seconds precision not preserved. |
| `text` | `time` / `time_hh_mm_ss` | `TE` / `SL` | `ValidDate` | |
| `textarea` (notes) | — | `TE` / `ESTB` | — | Multi-line form field. |
| `slider` | — | `Slider` / `HSLIDER` | — | Min/mid/max labels carried into `Configuration`. |
| `descriptive` | — | `DB` / `TB` | — | Display-only text block. |
| `file` | — | `FileUpload` / — | — | File-upload question. |
| **`calc`** | — | `DB` / `TB` | — | **Lossy** — Qualtrics has no native REDCap-style calc engine. The equation is preserved in the descriptive block's question text for the survey author to replace with Qualtrics piped-text or embedded-data math. |
| **`sql`** | — | `MC` / `DL` | — | **Lossy** — REDCap SQL fields pull options from an external database at runtime. Qualtrics cannot do this; the question is emitted with an empty option list. The survey author must populate it manually or wire up a Qualtrics WebService flow. |

## Qualtrics → REDCap

The reverse mapping uses the same table. Qualtrics question types that have no REDCap analogue are emitted as REDCap `text` fields with a warning in the conversion report:

| Qualtrics type | REDCap mapping | Notes |
|---|---|---|
| `SBS` (side-by-side) | `text` | No REDCap equivalent; report flags for manual rebuild. |
| `HotSpot` / `HL` (heatmap) | `text` | Graphical input — manual replacement required. |
| `Draw` | `text` | Drawing input — manual replacement required. |
| `RO` (rank order) | `text` | Rank-ordering would map to a REDCap matrix+ranking but is left as text for clarity. |
| `Timing` / `Meta` | `text` | Auto-generated metadata; usually not needed in REDCap. |
| `Captcha` | `text` | REDCap has no captcha question type. |

## Branching / Display Logic

See [branching-logic.md](./branching-logic.md) for expression-level translation rules.

## What's preserved losslessly

- Field identifiers (`redcap:Variable` ↔ `DataExportTag`)
- Field labels and section headers
- Codelist items (codes + display labels + order)
- Required / identifier flags (REDCap) ↔ ForceResponse (Qualtrics)
- Number / date bounds on `RangeCheck`
- Matrix group memberships (when both fields are present)

## What's approximated

- Slider step size and tick marks (Qualtrics has fewer knobs than REDCap)
- Custom validation regex (REDCap regex → Qualtrics `MatchesRegex` if supported)
- HTML-in-question-text (mostly passes through; some REDCap-specific piping loses meaning)

## What we flag as degraded

- `calc` fields (no Qualtrics equivalent)
- `sql` fields (no Qualtrics equivalent)
- REDCap action tags beyond `@HIDDEN` and `@READONLY`
- Qualtrics `WebService` / `Authenticator` / `TableOfContents` flow nodes (no REDCap equivalent)
