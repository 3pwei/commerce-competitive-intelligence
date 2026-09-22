"""End-to-end demo bundle and offline n8n validation tests."""

import json
import re
from pathlib import Path

import pytest

from competitive_intelligence.cli import build_parser, main
from competitive_intelligence.contracts import SHEET_MODELS, sheet_headers
from competitive_intelligence.demo import validate_bundle

ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / "n8n/workflows/competitive-intelligence-demo.json"
PROCESSING_WORKFLOW = ROOT / "n8n/workflows/competitive-intelligence-processing.json"
SHEETS_WORKFLOW = ROOT / "n8n/workflows/competitive-intelligence-sheets.json"
FIXTURES = ROOT / "fixtures"


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
    for slug in ("stg", "ods", "tgt", "comment", "overall_trend", "recent_suggestion"):
        assert (tmp_path / "sheets" / f"{slug}.json").is_file()
        assert (tmp_path / "sheets" / f"{slug}.csv").is_file()
    report = json.loads((tmp_path / "validation_report.json").read_text(encoding="utf-8"))
    assert report["status"] == "passed"
    assert report["cross_sheet_reconciliation"] == "passed"
    assert (tmp_path / "email_preview.html").is_file()
    assert (tmp_path / "email_preview.txt").is_file()
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
    serialized = WORKFLOW.read_text(encoding="utf-8")
    assert [node["type"] for node in nodes].count("n8n-nodes-base.manualTrigger") == 1
    assert not any(
        trigger in node["type"].lower() for node in nodes for trigger in ("schedule", "cron")
    )
    assert "credentials" not in serialized
    assert "@gmail.com" not in serialized
    assert not re.search(r"docs\.google\.com/spreadsheets/d/[A-Za-z0-9_-]+", serialized)
    assert "$env" not in serialized
    options = next(node for node in nodes if node["name"] == "Select Demo Options")
    assignments = {
        item["name"]: item for item in options["parameters"]["assignments"]["assignments"]
    }
    for name, expected in {
        "fixtureMode": True,
        "mockLlm": True,
        "dryRun": True,
        "writeSheets": False,
        "sendEmail": False,
    }.items():
        assert assignments[name]["type"] == "boolean"
        assert assignments[name]["value"] is expected
    assert "writeSheets" in serialized and "sendEmail" in serialized
    assert "Write Six Google Sheets" in serialized
    assert "Validate Output Bundle" in serialized
    assert "const b=$json.data" in serialized
    assert "Sheets Dry-Run" in serialized
    assert "Build Email Preview" in serialized
    assert "Execution Summary" in serialized


def test_parent_workflow_calls_real_processing_subworkflow() -> None:
    workflow = json.loads(WORKFLOW.read_text(encoding="utf-8"))
    nodes = {node["name"]: node for node in workflow["nodes"]}
    assert "Execute Python Demo Pipeline" not in nodes
    assert "Execute Intelligence Pipeline" in nodes
    node = nodes["Execute Intelligence Pipeline"]
    assert node["type"] == "n8n-nodes-base.executeWorkflow"
    assert node["parameters"]["workflowId"]["value"] == ("competitive-intelligence-processing-v1")
    assert workflow["connections"]["Execute Intelligence Pipeline"]["main"][0][0]["node"] == (
        "Validate Output Bundle"
    )
    sheets_node = nodes["Write Six Google Sheets"]
    assert sheets_node["type"] == "n8n-nodes-base.executeWorkflow"
    assert sheets_node["parameters"]["workflowId"]["value"] == (
        "competitive-intelligence-sheets-v1"
    )


def test_processing_subworkflow_executes_each_business_stage_once() -> None:
    workflow = json.loads(PROCESSING_WORKFLOW.read_text(encoding="utf-8"))
    nodes = {node["name"]: node for node in workflow["nodes"]}
    expected = (
        "Collect / Replay Product Pages",
        "Parse Retailer HTML",
        "Build STG / ODS / TGT",
        "Collect / Replay Reviews",
        "Analyze Recent Reviews with LLM",
        "Apply Business Rules",
        "Generate AI Recommendations",
    )
    for name in expected:
        node = nodes[name]
        assert node["type"] == "n8n-nodes-base.executeCommand"
        assert " n8n-stage " in node["parameters"]["command"]

    serialized = PROCESSING_WORKFLOW.read_text(encoding="utf-8")
    assert "Execute Python Demo Pipeline" not in serialized
    assert "checkpoint" not in serialized.lower()
    assert "n8n-nodes-base.executeWorkflowTrigger" in serialized
    assert "credentials" not in serialized
    assert not any(
        trigger in node["type"].lower()
        for node in workflow["nodes"]
        for trigger in ("schedule", "cron")
    )

    connections = workflow["connections"]
    previous = "When Executed by Another Workflow"
    for name in expected:
        assert connections[previous]["main"][0][0]["node"] == name
        previous = name
    assert connections[previous]["main"][0][0]["node"] == "Assemble Demo Bundle"


def test_sheets_delivery_is_isolated_in_subworkflow() -> None:
    parent = json.loads(WORKFLOW.read_text(encoding="utf-8"))
    sheets = json.loads(SHEETS_WORKFLOW.read_text(encoding="utf-8"))
    parent_types = {node["type"] for node in parent["nodes"]}
    assert "n8n-nodes-base.googleSheets" not in parent_types
    assert [node["type"] for node in sheets["nodes"]].count("n8n-nodes-base.googleSheets") == 7
    names = {node["name"] for node in sheets["nodes"]}
    assert "Read Existing STG SEQN" in names
    assert "Duplicate SEQN Guard" in names
    assert "Write Recent Suggestion" in names
    assert "Return Validated Bundle" in names
    serialized = SHEETS_WORKFLOW.read_text(encoding="utf-8")
    assert "credentials" not in serialized
    assert "docs.google.com/spreadsheets/d/" not in serialized


def test_n8n_stage_cli_contract() -> None:
    args = build_parser().parse_args(
        [
            "n8n-stage",
            "analyze-reviews",
            "--provider",
            "mock",
            "--output-dir",
            "output/demo",
        ]
    )
    assert args.stage == "analyze-reviews"
    assert args.provider == "mock"


def test_n8n_stages_produce_same_validated_bundle(tmp_path: Path) -> None:
    stages = (
        "collect-product-pages",
        "parse-retailer-html",
        "build-data-layers",
        "collect-reviews",
        "analyze-reviews",
        "apply-business-rules",
        "generate-recommendations",
        "assemble-bundle",
    )
    for stage in stages:
        assert main(["n8n-stage", stage, "--output-dir", str(tmp_path)]) == 0
    payload = json.loads((tmp_path / "demo_bundle.json").read_text(encoding="utf-8"))
    assert payload["seqn"] == payload["run_summary"]["seqn"]
    assert payload["stg_rows"]
    assert payload["comment_rows"]
    assert payload["recent_suggestion_rows"]
    assert json.loads((tmp_path / "validation_report.json").read_text())["status"] == "passed"


def test_fixtures_contain_no_delivery_identifiers_or_credentials() -> None:
    serialized = "\n".join(
        path.read_text(encoding="utf-8") for path in FIXTURES.rglob("*") if path.is_file()
    )
    forbidden = (
        r"docs\.google\.com/spreadsheets/d/[A-Za-z0-9_-]+",
        r"(?i)[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}",
        r"""(?i)(api[_-]?key|access[_-]?token|client[_-]?secret)\s*[:=]\s*["'][^"']+["']""",
    )
    assert not any(re.search(pattern, serialized) for pattern in forbidden)


def test_bundle_validation_rejects_empty_and_cross_sheet_drift(tmp_path: Path) -> None:
    main(["demo-run", "--output-dir", str(tmp_path)])
    from competitive_intelligence.demo import DemoBundle

    payload = json.loads((tmp_path / "demo_bundle.json").read_text(encoding="utf-8"))
    payload["comment_rows"] = []
    payload["run_summary"]["sheet_row_counts"]["Comment"] = 0
    with pytest.raises(ValueError, match="Comment must contain"):
        validate_bundle(DemoBundle.model_validate(payload))

    payload = json.loads((tmp_path / "demo_bundle.json").read_text(encoding="utf-8"))
    payload["overall_trend_rows"][0]["Vendor"] = "walmart"
    with pytest.raises(ValueError, match="identities do not reconcile"):
        validate_bundle(DemoBundle.model_validate(payload))


def test_fixture_demo_repeats_without_external_state(tmp_path: Path) -> None:
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    assert main(["demo-run", "--output-dir", str(first_dir)]) == 0
    assert main(["demo-run", "--output-dir", str(second_dir)]) == 0
    first = json.loads((first_dir / "demo_bundle.json").read_text(encoding="utf-8"))
    second = json.loads((second_dir / "demo_bundle.json").read_text(encoding="utf-8"))
    assert first["run_summary"]["sheet_row_counts"] == second["run_summary"]["sheet_row_counts"]
    assert {
        key: len(first[key])
        for key in (
            "stg_rows",
            "ods_rows",
            "tgt_rows",
            "comment_rows",
            "overall_trend_rows",
            "recent_suggestion_rows",
        )
    } == {
        key: len(second[key])
        for key in (
            "stg_rows",
            "ods_rows",
            "tgt_rows",
            "comment_rows",
            "overall_trend_rows",
            "recent_suggestion_rows",
        )
    }
