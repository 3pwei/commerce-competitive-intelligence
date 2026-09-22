#!/bin/sh
set -eu

parent_workflow=/opt/competitive-intelligence/n8n/workflows/competitive-intelligence-demo.json
processing_workflow=/opt/competitive-intelligence/n8n/workflows/competitive-intelligence-processing.json
sheets_workflow=/opt/competitive-intelligence/n8n/workflows/competitive-intelligence-sheets.json
result=/demo-output/runtime-execution.json

mkdir -p /demo-output
rm -f "$result"
n8n import:workflow --input="$processing_workflow"
n8n import:workflow --input="$sheets_workflow"
n8n import:workflow --input="$parent_workflow"
set +e
n8n execute --id=competitive-intelligence-demo-v2 --rawOutput > "$result" 2>&1
execution_status=$?
set -e
cat "$result"
if [ "$execution_status" -ne 0 ]; then
  exit "$execution_status"
fi
python3 /opt/competitive-intelligence/scripts/validate_n8n_runtime.py \
  --output-dir /demo-output \
  --execution-output "$result"
