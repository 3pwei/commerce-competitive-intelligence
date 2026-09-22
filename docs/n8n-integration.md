# n8n Demo Integration

Import `n8n/workflows/competitive-intelligence-demo.json` into a self-hosted n8n instance. The
workflow has a Manual Trigger only. Its editable **Select Demo Options** node defaults to fixture,
mock provider, dry run enabled, Sheets disabled, Email disabled, and a blank recipient.

## Setup

1. Install this project and its Python dependencies where n8n executes commands.
2. Set `projectDir` in **Select Demo Options** to the repository's absolute path.
3. Set `GOOGLE_SHEET_URL` in the n8n runtime environment; no Sheet ID is stored in the workflow.
4. Assign a Google Sheets OAuth2 credential to all Google Sheets nodes. Do not export it into Git.
5. Assign a Gmail OAuth2 credential to **Optional Gmail Send**.
6. Keep the recipient blank until sending is intentionally enabled.

The workflow calls `python -m competitive_intelligence demo-run`. Python owns capture replay,
normalization, rules, LLM validation, Sheet contracts, and email rendering. n8n validates the bundle
again, checks STG for the SEQN, appends the six datasets in order, and optionally sends the email.

## Safe first run

Run with defaults. It must reach **Run Summary** without contacting Google or Gmail. Inspect
`output/demo/demo_bundle.json` and the Email preview. Then enable `writeSheets` and disable `dryRun`
for a deliberate Sheet write. A repeated SEQN is rejected before the first append; existing rows are
never cleared. Email requires dry run off, `sendEmail` enabled, and a non-blank recipient.

If validation, duplicate protection, or an append fails, n8n stops that path and exposes the failing
node. Later writes and Gmail are not configured to continue on error.

## Offline contract validation

CI parses the exported JSON, requires exactly one Manual Trigger, rejects Schedule/Cron nodes and
embedded credentials, Email addresses, Sheet IDs, or API keys, and checks that the execute-command
arguments remain compatible with the Python `demo-run` CLI. The default dry-run path is exercised
without Google Sheets or Gmail access.
