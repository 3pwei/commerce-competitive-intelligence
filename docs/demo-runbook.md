# Demo Runbook

## 1. Install and verify

Use Python 3.12 from the repository root:

```bash
python --version
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m competitive_intelligence --help
```

No `.env`, API key, Google account, paid service, or external API is required for the safe path.

## 2. Run the offline Demo

```bash
python -m competitive_intelligence demo-run \
  --mode fixture --provider mock --output-dir output/demo
```

This is the fixture/mock/dry-run flow. It replays nine synthetic product pages and sanitized review
fixtures, executes every Python stage, and performs contract validation before writing artifacts.

## 3. Inspect the outputs

Confirm these files exist:

```text
output/demo/demo_bundle.json
output/demo/run_summary.json
output/demo/validation_report.json
output/demo/detected_events.json
output/demo/email_preview.html
output/demo/email_preview.txt
output/demo/sheets/{stg,ods,tgt,comment,overall_trend,recent_suggestion}.{json,csv}
```

`validation_report.json` must contain `"status": "passed"`. Its six row counts must match
`run_summary.json`. Open `email_preview.html` locally to review the message without sending it.
The committed [`../examples/demo`](../examples/demo) directory is the sanitized reference run.

## 4. Import and run n8n

1. Import `n8n/workflows/competitive-intelligence-demo.json` into self-hosted n8n.
2. Open **Select Demo Options** and set `projectDir` to the checkout path used by n8n.
3. Keep `mode=fixture`, `provider=mock`, `dryRun=true`, `writeSheets=false`, and `sendEmail=false`.
4. Select **Execute Workflow** from the Manual Trigger.
5. Inspect **Validate Output Bundle**, **Email Preview**, and **Run Summary**.

The safe run does not reach Google Sheets or Gmail.

## 5. Optional Google Sheets and Gmail

Only after the dry-run succeeds:

1. Create a spreadsheet containing the six exact tab names from `config/sheet-schema.v1.json`.
2. Set `GOOGLE_SHEET_URL` in the n8n runtime; do not paste a Sheet ID into the workflow export.
3. Assign Google Sheets OAuth2 credentials to every Sheets node in the n8n UI.
4. Set `dryRun=false` and `writeSheets=true`; keep Email disabled for the first write.
5. Confirm all six appends and the final SEQN guard result.
6. Assign Gmail OAuth2 credentials, enter an intended recipient, and then set `sendEmail=true`.

The workflow never clears rows. Reusing an existing SEQN is rejected before the first append.

## 6. Optional one-time live capture

```bash
python -m competitive_intelligence capture --mode live
```

Live capture is not part of the public Demo. Raw results stay under the Git-ignored `fixtures/live/`.
Review legality and retailer terms, sanitize content, remove identifiers, and obtain approval before
turning any capture into a committed fixture.

## Troubleshooting and recovery

| Symptom | Likely cause | Recovery |
|---|---|---|
| `python` is not 3.12 | Wrong interpreter | Recreate `.venv` with Python 3.12 |
| Import/module error | Package not installed | Run `python -m pip install -e ".[dev]"` |
| Contract/header failure | Sheet schema or artifact drift | Restore the v1 manifest; do not rename columns |
| Cross-sheet reconciliation failure | Inputs from different runs | Delete `output/demo` and rerun once |
| n8n command fails | Incorrect `projectDir` or Python environment | Use the checkout path visible to n8n and install the package there |
| Duplicate SEQN | Batch already appended | Inspect the existing STG rows; do not bypass the guard |
| Sheets/Gmail auth error | Missing or expired OAuth credential | Reconnect only in n8n; never export credentials |
| Partial Sheet append | External failure after validation | Stop Email, inspect the SEQN across all tabs, remove only that partial batch manually, then rerun |

For a clean local retry, remove only the generated `output/demo` directory and run the offline
command again. Never delete or overwrite an external Sheet as an automated recovery step.
