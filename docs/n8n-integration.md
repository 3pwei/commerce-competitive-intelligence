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
Manual Trigger -> Select Demo Options -> Execute Python Demo Pipeline
-> Read and Parse Demo Bundle
-> Collect / Replay Product Pages [checkpoint]
-> Parse Retailer HTML [checkpoint]
-> Build STG / ODS / TGT [checkpoint]
-> Collect / Replay Reviews [checkpoint]
-> Analyze Recent Reviews with LLM [checkpoint]
-> Apply Business Rules [checkpoint]
-> Generate AI Recommendations [checkpoint]
-> Validate Output Bundle -> Sheets Dry-Run -> Build Email Preview -> Execution Summary
```

The fixed command runs from `/opt/competitive-intelligence` and writes to `/demo-output`. The
default path does not call Google, Gmail, an LLM, or retailer sites and requires no credentials.

The seven named Code nodes are fail-closed stage checkpoints, not duplicate implementations of the
Python business logic. `Execute Python Demo Pipeline` owns collection/replay, retailer HTML parsing,
review-source normalization, LLM-provider invocation, deterministic rules, and recommendations.
Each checkpoint makes that boundary visible on the n8n canvas and verifies the corresponding bundle
output before delivery continues. The offline path uses saved HTML/review fixtures and the
deterministic mock LLM; configured live adapters remain explicit opt-in boundaries.

## Execute Command boundary

n8n 2.x excludes Execute Command and local-file nodes by default. This local-only image enables the
two nodes required by the Demo through an explicit `NODES_EXCLUDE` setting while continuing to
exclude `Local File Trigger`. It does not use `NODES_EXCLUDE=[]`.

Execute Command is limited by the fixed workflow command, fixed working directory, non-root `node`
user, bundled fixtures, and dedicated output mount. Do not expose this Demo instance to untrusted
users or the public internet. File-node access is explicitly restricted to `/demo-output`. This
configuration is not a production deployment.

## Import and execution

The smoke service imports the workflow and executes its deterministic ID inside the custom image:

```text
n8n import:workflow --input=/opt/competitive-intelligence/n8n/workflows/competitive-intelligence-demo.json
n8n execute --id=competitive-intelligence-demo-v2 --rawOutput
```

It then validates the six Sheet JSON files against the Python contracts, checks row counts,
confirms the Email preview, records the n8n execution ID/status, and writes
`output/n8n/runtime-smoke-report.json`.

Google Sheets and Gmail nodes remain optional and inactive in the default dry-run route. Configuring
real delivery requires a separate security review, explicit credentials, and deliberate workflow
changes; it is outside the local acceptance path.
