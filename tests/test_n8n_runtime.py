"""n8n 2.x container contract and runtime-report tests."""

import json
from pathlib import Path

from competitive_intelligence.cli import main
from competitive_intelligence.runtime_validation import validate_n8n_runtime

ROOT = Path(__file__).parents[1]


def test_compose_pins_runtime_and_limits_high_risk_nodes() -> None:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile.n8n").read_text(encoding="utf-8")
    assert "n8nio/n8n:2.4.4" in dockerfile
    assert "python3" in dockerfile
    assert 'N8N_BLOCK_ENV_ACCESS_IN_NODE: "true"' in compose
    assert 'N8N_RESTRICT_FILE_ACCESS_TO: "/demo-output"' in compose
    assert "n8n-nodes-base.localFileTrigger" in compose
    assert "NODES_EXCLUDE: '[]'" not in compose
    assert "n8n_data:/home/node/.n8n" in compose
    assert "./output/n8n:/demo-output" in compose


def test_container_shell_scripts_are_forced_to_lf() -> None:
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "*.sh text eol=lf" in attributes
    shell_scripts = list(ROOT.rglob("*.sh"))
    assert shell_scripts
    for script in shell_scripts:
        assert b"\r\n" not in script.read_bytes(), f"{script} contains CRLF line endings"


def test_runtime_validator_checks_real_outputs(tmp_path: Path) -> None:
    assert main(["demo-run", "--output-dir", str(tmp_path)]) == 0
    execution = tmp_path / "runtime-execution.json"
    execution.write_text(
        '{"status":"completed","executionId":"test-execution-19"}\n', encoding="utf-8"
    )
    report = validate_n8n_runtime(tmp_path, execution)
    assert report["status"] == "passed"
    assert report["execution_id"] == "test-execution-19"
    assert json.loads((tmp_path / "runtime-smoke-report.json").read_text())["status"] == "passed"
