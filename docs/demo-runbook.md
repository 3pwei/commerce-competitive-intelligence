# Demo Runbook

## Prerequisites

- Windows 10/11
- Docker Desktop 4.x configured for Linux containers
- Docker Compose v2 (`docker compose version`)
- Git

The supported image is pinned to `n8nio/n8n:2.4.4`. Python and all application dependencies are
installed while the custom image is built. No `.env`, API key, Google account, paid service, or
manual installation inside the container is required.

All commands below run in Windows PowerShell from the repository root.

## Start

```powershell
docker compose up --build -d n8n
```

Open `http://localhost:5678`. The named volume `n8n_data` holds n8n state; `output\\n8n` receives
Demo artifacts.

## Import and run the offline workflow

The runtime smoke command performs the one-time import and real n8n execution automatically:

```powershell
docker compose --profile test run --rm n8n-smoke
```

For import only:

```powershell
docker compose exec n8n n8n import:workflow --input=/opt/competitive-intelligence/n8n/workflows/competitive-intelligence-demo.json
```

No workflow field needs to be repaired in the UI. The smoke run uses fixture mode, mock LLM,
dry-run Sheets, and Email preview only. It contacts no Google, Gmail, LLM, or retailer API.

To demonstrate the Manual Trigger in the UI after importing, open **Competitive Intelligence —
Manual Demo** and select **Execute Workflow**. The successful node path ends at **Execution
Summary**.

## Inspect outputs

```powershell
Get-Content .\\output\\n8n\\runtime-smoke-report.json
Get-Content .\\output\\n8n\\validation_report.json
Start-Process .\\output\\n8n\\email_preview.html
Get-ChildItem .\\output\\n8n\\sheets
```

Required artifacts include:

```text
output/n8n/runtime-execution.json
output/n8n/runtime-smoke-report.json
output/n8n/demo_bundle.json
output/n8n/run_summary.json
output/n8n/validation_report.json
output/n8n/email_preview.html
output/n8n/sheets/{stg,ods,tgt,comment,overall_trend,recent_suggestion}.{json,csv}
```

Both report files must say `passed`; the runtime report must say workflow status `completed`.

## Logs and lifecycle

```powershell
# Logs
docker compose logs -f n8n

# Stop containers but retain n8n_data and host output
docker compose down

# Restart with existing data
docker compose up -d n8n

# Fully remove containers and persistent n8n data
docker compose down --volumes --remove-orphans
Remove-Item -Recurse -Force .\\output\\n8n
```

The final two commands are destructive. The `Remove-Item` command deletes generated Demo evidence,
but does not modify fixtures or source files.

## Troubleshooting

| Symptom | Check | Recovery |
|---|---|---|
| Port 5678 is already used | `docker compose ps` | Stop the conflicting local service or change the host-side port |
| Image build fails | Docker Desktop engine and network access | Restart Docker Desktop and rerun `docker compose build --pull n8n` |
| Workflow is duplicated | Previous import remains in `n8n_data` | Use the existing imported workflow; the smoke run remains safe |
| Execute Command is unknown | Wrong image/compose configuration | Confirm image tag `2.4.4` and start through this Compose file |
| Python module is missing | A stock n8n image was started | Rebuild with `Dockerfile.n8n`; do not install packages manually |
| Validation fails | Mixed or stale generated outputs | Remove only `output\\n8n`, then rerun the smoke command |

## Security and deployment boundary

Execute Command can run local processes and is enabled only for this isolated, local Demo. The
container runs as the non-root `node` user, uses a fixed command/path, keeps environment access from
Code nodes blocked, and leaves `Local File Trigger` excluded. Do not publish port 5678 to the public
internet and do not treat this Compose setup as Production. Scheduling, live crawling, configured
LLM calls, Google Sheets writes, Gmail sending, and Production deployment are outside this runbook.
