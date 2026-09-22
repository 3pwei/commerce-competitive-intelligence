# Comment Sheet output

PR #7 converts the validated PR #6 review analyses into files ready for a later Google Sheets
adapter. It does not call an LLM during transformation and never connects to Google Sheets.

## Mapping

`config/sheet-schema.v1.json` remains the only source of truth for column names and order.

| Comment column | Source |
| --- | --- |
| `Product Name` | matching enabled product configuration |
| `Vendor` | `amazon`, because PR #6 reviews are Amazon-only |
| `Pros1`–`Pros3` | first three unique positive theme labels |
| `Cons1`–`Cons3` | unique negative theme labels, then recurring issue labels |
| `Summary` | validated analysis summary |

Supporting review IDs, analyzed count, prompt version, provider/model, warnings, negative-trend
enum and its explicit boolean interpretation are kept in `comment_evidence.json`; they are not
added to the Sheet schema. An insufficient-data analysis is recorded there with
`status=insufficient_data` and does not create a misleading Comment row. Missing, duplicate, or
unknown product analyses fail the transformation.

## Run context and outputs

Use the PR #5 run context when the workflows are orchestrated together:

```bash
python -m competitive_intelligence comment-output \
  --mode fixture --provider mock \
  --run-summary output/demo/run_summary.json \
  --output-dir output/demo
```

`--seqn VALUE` is available when the orchestrator already has the value. The two options are
mutually exclusive. Only a standalone run without either option generates a new SEQN.

The command always writes:

- `comment.json`
- `comment.csv`
- `comment_evidence.json`
- `comment_summary.json`

Rows follow enabled product configuration order. JSON and CSV carry the same business fields;
CSV quoting preserves punctuation and commas within summary/theme values. Fixture + mock mode is
fully offline and deterministic when given the same SEQN.
