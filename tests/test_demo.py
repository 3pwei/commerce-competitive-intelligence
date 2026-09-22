"""End-to-end demo bundle and offline n8n validation tests."""

import json
from pathlib import Path

import pytest

from competitive_intelligence.cli import main
from competitive_intelligence.contracts import SHEET_MODELS, sheet_headers
from competitive_intelligence.demo import validate_bundle

ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / "n8n/workflows/competitive-intelligence-demo.json"


def test_demo_run_writes_one_reconciled_bundle(tmp_path: Path, capsys) -> None:
    args = ["demo-run", "--mode", "fixture", "--provider", "mock", "--output-dir", str(tmp_path)]
    assert main(args) == 0
    payload = json.loads((tmp_path / "demo_bundle.json").read_text(encoding="utf-8"))
    assert payload["seqn"] == payload["run_summary"]["seqn"]
    mapping = {
        "STG": "stg_rows",
        "ODS": "ods_rows",
        "TGT": "tgt_rows",
        "Comment": "comment_rows",
        "Overall Trend": "overall_trend_rows",
        "Recent Suggestion": "recent_suggestion_rows",
    }
    for sheet, key in mapping.items():
        assert payload[key]
        assert list(payload[key][0]) == sheet_headers(SHEET_MODELS[sheet])
        assert payload["run_summary"]["sheet_row_counts"][sheet] == len(payload[key])
    assert payload["email_content"]["html"].startswith("<h1>")
    assert payload["seqn"] in payload["email_content"]["subject"]
    assert '"bundle"' in capsys.readouterr().out


def test_bundle_validation_rejects_header_drift(tmp_path: Path) -> None:
    main(["demo-run", "--output-dir", str(tmp_path)])
    from competitive_intelligence.demo import DemoBundle

    payload = json.loads((tmp_path / "demo_bundle.json").read_text(encoding="utf-8"))
    payload["stg_rows"][0]["Unexpected"] = "value"
    bundle = DemoBundle.model_validate(payload)
    with pytest.raises(ValueError, match="headers do not match"):
        validate_bundle(bundle)


def test_exported_workflow_is_manual_safe_and_credential_free() -> None:
    workflow = json.loads(WORKFLOW.read_text(encoding="utf-8"))
    nodes = workflow["nodes"]
    types = {node["type"] for node in nodes}
    serialized = WORKFLOW.read_text(encoding="utf-8")
    assert "n8n-nodes-base.manualTrigger" in types
    assert not any("schedule" in node["type"].lower() for node in nodes)
    assert "credentials" not in serialized
    assert "@gmail.com" not in serialized
    assert "dryRun" in serialized and '"booleanValue": true' in serialized
    assert "writeSheets" in serialized and "sendEmail" in serialized
    assert "Duplicate SEQN Guard" in serialized
    assert "Validate Output Bundle" in serialized
