#!/usr/bin/env python3
"""Validate artifacts produced by a real n8n CLI execution."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from competitive_intelligence.contracts import SHEET_MODELS, sheet_headers

SHEETS = {
    "STG": "stg",
    "ODS": "ods",
    "TGT": "tgt",
    "Comment": "comment",
    "Overall Trend": "overall_trend",
    "Recent Suggestion": "recent_suggestion",
}


def validate(output_dir: Path, execution_output: Path) -> dict[str, object]:
    validation = json.loads((output_dir / "validation_report.json").read_text(encoding="utf-8"))
    summary = json.loads((output_dir / "run_summary.json").read_text(encoding="utf-8"))
    if validation["status"] != "passed":
        raise ValueError("Python bundle validation did not pass")

    rows: dict[str, int] = {}
    for sheet_name, slug in SHEETS.items():
        path = output_dir / "sheets" / f"{slug}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not payload:
            raise ValueError(f"{sheet_name} output is empty")
        if list(payload[0]) != sheet_headers(SHEET_MODELS[sheet_name]):
            raise ValueError(f"{sheet_name} headers do not match the contract")
        rows[sheet_name] = len(payload)

    if rows != summary["sheet_row_counts"]:
        raise ValueError("Sheet row counts do not match run_summary.json")
    if not (output_dir / "email_preview.html").is_file():
        raise ValueError("Email preview was not generated")

    raw = execution_output.read_text(encoding="utf-8")
    if '"status":"completed"' not in raw.replace(" ", ""):
        raise ValueError("Execution Summary did not report completed")
    match = re.search(r'"executionId"\s*:\s*"?([^",}]+)', raw)
    execution_id = match.group(1) if match else "cli-manual-execution"
    report: dict[str, object] = {
        "status": "passed",
        "workflow_status": "completed",
        "execution_id": execution_id,
        "sheet_row_counts": rows,
        "email_preview": "/demo-output/email_preview.html",
        "persistence_volume": "/home/node/.n8n",
    }
    (output_dir / "runtime-smoke-report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--execution-output", type=Path, required=True)
    args = parser.parse_args()
    validate(args.output_dir, args.execution_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
