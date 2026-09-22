# n8n 2.x Demo Integration

## Supported runtime

- Docker Desktop 4.x using Linux containers and Docker Compose v2
- n8n `2.4.4` (`n8nio/n8n:2.4.4`, never `latest`)
- Python 3.12-compatible project runtime installed in the custom image
- Windows 10/11 PowerShell as the documented host shell

`Dockerfile.n8n` installs Python and the project at `/opt/competitive-intelligence`.
`compose.yaml` mounts persistent n8n state at `/home/node/.n8n` and Demo artifacts at
`/demo-output`. The matching host directory is `output/n8n`.

## Safe offline flow

The imported workflow has one Manual Trigger and no Schedule/Cron trigger. Its n8n 2.x Set node
stores `fixtureMode`, `mockLlm`, and `dryRun` as actual `true` Booleans, and `writeSheets` and
`sendEmail` as actual `false` Booleans. It does not read environment variables from a Code node.

```text
Parent: Manual Trigger -> Select Demo Options -> Execute Intelligence Pipeline
        -> Validate Output Bundle -> Dry Run or Sheets Disabled
        -> Sheets Dry-Run / Write Six Google Sheets
        -> Build Email Preview -> Execution Summary

Processing sub-workflow:
When Executed by Another Workflow
-> Collect / Replay Product Pages
-> Parse Retailer HTML
-> Build STG / ODS / TGT
-> Collect / Replay Reviews
-> Analyze Recent Reviews with LLM
-> Apply Business Rules
-> Generate AI Recommendations
-> Assemble Demo Bundle -> Read Demo Bundle -> Parse Demo Bundle

Google Sheets delivery sub-workflow:
When Executed by Another Workflow -> Read Existing STG SEQN -> Duplicate SEQN Guard
-> Prepare / Write STG -> Prepare / Write ODS -> Prepare / Write TGT
-> Prepare / Write Comment -> Prepare / Write Overall Trend
-> Prepare / Write Recent Suggestion -> Return Validated Bundle
```

Each named processing node executes one `n8n-stage` CLI command and writes a durable artifact under
`/demo-output/stages`. The next node consumes that artifact, so no all-in-one pipeline or visual-only
checkpoint remains. The default path does not call Google, Gmail, an external LLM, or retailer sites
and requires no credentials. It uses saved HTML/review fixtures and the deterministic mock LLM.

## Execute Command boundary

n8n 2.x excludes Execute Command and local-file nodes by default. This local-only image enables the
two nodes required by the Demo through an explicit `NODES_EXCLUDE` setting while continuing to
exclude `Local File Trigger`. It does not use `NODES_EXCLUDE=[]`.

Execute Command is limited by the fixed workflow command, fixed working directory, non-root `node`
user, bundled fixtures, and dedicated output mount. Do not expose this Demo instance to untrusted
users or the public internet. File-node access is explicitly restricted to `/demo-output`. This
configuration is not a production deployment.

## Import and execution

The smoke service imports the processing workflow first, imports the parent second, and executes the
parent's deterministic ID inside the custom image:

```text
n8n import:workflow --input=/opt/competitive-intelligence/n8n/workflows/competitive-intelligence-processing.json
n8n import:workflow --input=/opt/competitive-intelligence/n8n/workflows/competitive-intelligence-sheets.json
n8n import:workflow --input=/opt/competitive-intelligence/n8n/workflows/competitive-intelligence-demo.json
n8n execute --id=competitive-intelligence-demo-v2 --rawOutput
```

It then validates the six Sheet JSON files against the Python contracts, checks row counts,
confirms the Email preview, records the n8n execution ID/status, and writes
`output/n8n/runtime-smoke-report.json`.

Google Sheets and Gmail nodes remain optional and inactive in the default dry-run route. Configuring
real delivery requires a separate security review, explicit credentials, and deliberate workflow
changes; it is outside the local acceptance path.
