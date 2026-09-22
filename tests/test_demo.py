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
    assert "Duplicate SEQN Guard" in serialized
    assert "Validate Output Bundle" in serialized
    assert "Sheets Dry-Run" in serialized
    assert "Build Email Preview" in serialized
    assert "Execution Summary" in serialized


def test_workflow_command_matches_demo_cli_contract() -> None:
    workflow = json.loads(WORKFLOW.read_text(encoding="utf-8"))
    command = next(
        node["parameters"]["command"]
        for node in workflow["nodes"]
        if node["name"] == "Execute Python Demo Pipeline"
    )
    for token in (
        "demo-run",
        "--mode",
        "--provider",
        "--output-dir",
    ):
        assert token in command
    assert command.startswith("cd /opt/competitive-intelligence")
    assert "/demo-output" in command
    args = build_parser().parse_args(
        [
            "demo-run",
            "--mode",
            "fixture",
            "--provider",
            "mock",
            "--output-dir",
            "output/demo",
            "--sheet-url",
            "",
        ]
    )
    assert args.mode == "fixture"
    assert args.provider == "mock"


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
