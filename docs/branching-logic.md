# Branching logic

REDCap and Qualtrics describe conditional visibility in very different ways:

- **REDCap** uses a compact expression DSL stored verbatim on each field's
  `redcap:BranchingLogic` attribute — e.g. `[age] >= 18 and [consent] = '1'`.
- **Qualtrics** uses a deeply-nested JSON structure on the question's
  `DisplayLogic` key with URI-style operand locators — e.g.
  `q://QID7/SelectableChoice/1`.

SurveyWizard parses the REDCap DSL into an AST, translates the AST into QSF
`BooleanExpression` JSON, and walks the JSON back in the reverse direction.

## REDCap mini-DSL grammar

```
expr       := or_expr
or_expr    := and_expr ('or' and_expr)*
and_expr   := cmp_expr ('and' cmp_expr)*
cmp_expr   := add_expr (cmp_op add_expr)?
cmp_op     := '=' | '<>' | '<' | '>' | '<=' | '>='
add_expr   := mul_expr (('+' | '-') mul_expr)*
mul_expr   := unary (('*' | '/') unary)*
unary      := '-' unary | 'not' unary | atom
atom       := field_ref | literal | func_call | '(' expr ')'
field_ref  := '[' IDENT ']' ( '[' IDENT ']' )? | '[' IDENT '(' code ')' ']'
literal    := STRING | NUMBER
func_call  := IDENT '(' arg_list? ')'
arg_list   := expr (',' expr)*
```

Operators are case-insensitive. String literals use single quotes by convention
(`'1'`, `'active'`). Numbers are plain (`42`, `3.14`).

### Field reference variants

| Syntax | Meaning |
|---|---|
| `[age]` | Current field's `age` |
| `[baseline_arm_1][age]` | Event-qualified reference (longitudinal studies) |
| `[race(1)]` | Checkbox option `1` selected |
| `[baseline_arm_1][race(1)]` | Event-qualified checkbox option |

## QSF DisplayLogic shape

```json
{
  "Type": "BooleanExpression",
  "inPage": false,
  "0": {
    "Type": "If",
    "0": {
      "LogicType": "Question",
      "Type": "Expression",
      "Operator": "Selected",
      "QuestionID": "QID2",
      "LeftOperand": "q://QID2/SelectableChoice/1",
      "ChoiceLocator": "q://QID2/SelectableChoice/1"
    },
    "1": {
      "Conjuction": "And",
      "LogicType": "Question",
      "Type": "Expression",
      "Operator": "Selected",
      "QuestionID": "QID4",
      "LeftOperand": "q://QID4/SelectableChoice/1"
    }
  }
}
```

### Structural contract

- Top-level numeric-string keys (`"0"`, `"1"`, ...) are OR-joined condition groups.
- Within a group, sibling expressions use `Conjuction` (sic — the canonical
  Qualtrics typo, preserved exactly). The first expression in a group has no
  `Conjuction`; subsequent ones have `"Conjuction": "And"` or `"Or"`.
- Operand URIs:
  - `q://QID<n>/SelectableChoice/<k>` — a specific choice selected
  - `q://QID<n>/ChoiceTextEntryValue[/<k>]` — the text entry value on a choice
  - `ed://<field_name>` — an embedded-data field
  - `g://...` — global variables (IP, Location, etc.)

## Translation mapping

| REDCap | Qualtrics |
|---|---|
| `[f] = 'v'` (choice code comparison) | `Operator: Selected` + `ChoiceLocator` |
| `[f] <> 'v'` | `Operator: NotSelected` |
| `[f(c)] = '1'` (checkbox) | `Operator: Selected` on choice `c` |
| `[f] > 18` (numeric) | `Operator: GreaterThan` + `RightOperand: "18"` |
| `[f] = 'x' and [g] = 'y'` | One AND-group with two expressions |
| `[f] = 'x' or [g] = 'y'` | Two OR-groups each with one expression |

## What isn't translated

These REDCap constructs have **no direct Qualtrics equivalent** — they're
logged as `warning` in the conversion report and silently dropped:

- `datediff([a], [b], 'y')` and other function calls
- Arithmetic inside conditions (`[a] + [b] > 10`)
- Nested `if()` calls
- REDCap Smart Variables (`[user-name]`, `[record-dag-name]`)

For these, the survey author should reconstruct the logic in Qualtrics using
custom JavaScript or EmbeddedData.

## What the reverse direction drops

QSF-side constructs **without a REDCap equivalent**:

- `MatchesRegex` operator (could map to REDCap custom validation regex but
  REDCap expression language has no regex primitive)
- `ed://` operands referencing Qualtrics-only embedded data (REDCap has field
  references only; the embedded data is translated to a REDCap field reference
  and flagged in the report)
- Flow-level `Branch` conditions that reference non-question operands

## Debugging

When converting fails to produce the expected visibility behavior, examine the
sidecar `.report.md` — every dropped expression is logged with the field OID
and reason.

If you need to inspect the AST produced by the parser, you can do it
programmatically:

```python
from surveywizard.redcap.expressions import parse, to_dict, render

ast = parse("[age] >= 18 and ([consent] = '1' or [waiver(1)] = '1')")
print(to_dict(ast))   # nested dict you can inspect
print(render(ast))    # canonical string form
```
