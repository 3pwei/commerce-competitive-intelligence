"""CLI smoke tests."""

import json

import pytest

from competitive_intelligence.cli import main


def test_cli_help(capsys: pytest.CaptureFixture[str]) -> None:
    """The documented module command exposes usable help output."""
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    assert exc_info.value.code == 0
    assert "Competitive pricing and review analysis demo." in capsys.readouterr().out


def test_reviews_cli_defaults_to_offline_mock(capsys: pytest.CaptureFixture[str]) -> None:
    result = main(["reviews"])

    assert result == 0
    assert '"provider": "mock"' in capsys.readouterr().out


def test_comment_output_cli_writes_all_artifacts(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = main(["comment-output", "--output-dir", str(tmp_path), "--seqn", "cli-seqn"])

    assert result == 0
    assert {path.name for path in tmp_path.iterdir()} == {
        "comment.json",
        "comment.csv",
        "comment_evidence.json",
        "comment_summary.json",
    }
    assert '"seqn": "cli-seqn"' in capsys.readouterr().out


def test_recommendations_cli_writes_all_artifacts(tmp_path, capsys) -> None:
    trend = tmp_path / "overall_trend.json"
    events = tmp_path / "detected_events.json"
    trend.write_text(
        json.dumps(
            [
                {
                    "Product Name": "Apple AirPods Pro 2",
                    "Vendor": "amazon",
                    "Overall Trend": "COMPETITOR_PRICE_LOWER",
                    "Observation": "COMPETITOR_PRICE_LOWER",
                }
            ]
        ),
        encoding="utf-8",
    )
    events.write_text(
        json.dumps(
            [
                {
                    "rule_id": "COMPETITOR_PRICE_LOWER",
                    "product_id": "apple-airpods-pro-2",
                    "product_name": "Apple AirPods Pro 2",
                    "vendor": "amazon",
                    "severity": "warning",
                    "seqn": "cli-seqn",
                    "evidence": {"final_price": "199.00", "own_price": "249.00"},
                }
            ]
        ),
        encoding="utf-8",
    )
    output = tmp_path / "out"
    result = main(
        [
            "recommendations",
            "--trend",
            str(trend),
            "--events",
            str(events),
            "--provider",
            "mock",
            "--output-dir",
            str(output),
        ]
    )
    assert result == 0
    assert {path.name for path in output.iterdir()} == {
        "recent_suggestion.json",
        "recent_suggestion.csv",
        "recommendation_evidence.json",
        "recommendation_summary.json",
    }
    assert '"seqn": "cli-seqn"' in capsys.readouterr().out
