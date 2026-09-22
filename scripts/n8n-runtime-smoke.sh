#!/bin/sh
set -eu

workflow=/opt/competitive-intelligence/n8n/workflows/competitive-intelligence-demo.json
result=/demo-output/runtime-execution.json

mkdir -p /demo-output
rm -f "$result"
n8n import:workflow --input="$workflow"
n8n execute --id=competitive-intelligence-demo-v2 --rawOutput > "$result"
python3 /opt/competitive-intelligence/scripts/validate_n8n_runtime.py \
  --output-dir /demo-output \
  --execution-output "$result"

