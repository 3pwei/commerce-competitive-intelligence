"""Portfolio release metadata, documentation, and sanitized artifact checks."""

import json
import re
import tomllib
from pathlib import Path

import competitive_intelligence

ROOT = Path(__file__).parents[1]


def test_release_versions_and_license_are_consistent() -> None:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert metadata["project"]["version"] == "1.0.0"
    assert metadata["project"]["version"] == competitive_intelligence.__version__
    assert metadata["project"]["license"] == "MIT"
    assert (ROOT / "LICENSE").read_text(encoding="utf-8").startswith("MIT License")


def test_relative_markdown_links_resolve() -> None:
    missing: list[str] = []
    pattern = re.compile(r"\[[^]]*\]\(([^)]+)\)")
    for document in ROOT.rglob("*.md"):
        for target in pattern.findall(document.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "#")):
                continue
            relative = target.split("#", 1)[0]
            if relative and not (document.parent / relative).exists():
                missing.append(f"{document.relative_to(ROOT)}: {target}")
    assert not missing


def test_committed_demo_is_validated_and_sanitized() -> None:
    demo = ROOT / "examples/demo"
    report = json.loads((demo / "validation_report.json").read_text(encoding="utf-8"))
    summary = json.loads((demo / "run_summary.json").read_text(encoding="utf-8"))
    assert report["status"] == "passed"
    assert report["seqn"] == summary["seqn"]
    assert all(item["valid"] for item in report["contracts"].values())
    serialized = "\n".join(
        path.read_text(encoding="utf-8")
        for path in demo.rglob("*")
        if path.is_file() and path.suffix != ".svg"
    )
    assert not re.search(r"docs\.google\.com/spreadsheets/d/[A-Za-z0-9_-]+", serialized)
    assert not re.search(r"(?i)[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", serialized)
