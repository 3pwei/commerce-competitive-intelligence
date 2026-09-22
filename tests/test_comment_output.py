"""Tests for Comment Sheet transformation and artifacts."""

import csv
import json
from pathlib import Path

import pytest

from competitive_intelligence.comment_output import (
    load_seqn_from_run_summary,
    transform_comment_output,
    write_comment_outputs,
)
from competitive_intelligence.config import load_product_catalog
from competitive_intelligence.contracts import CommentRow, sheet_headers
from competitive_intelligence.reviews import (
    FixtureReviewSource,
    MockLLMProvider,
    NegativeTrend,
    run_review_analysis,
)

ROOT = Path(__file__).parents[1]
CATALOG = ROOT / "config/products.example.json"
FIXTURES = ROOT / "fixtures/reviews/manifest.json"


def fixture_result(seqn: str = "fixed-seqn"):
    catalog = load_product_catalog(CATALOG)
    analyses = run_review_analysis(catalog, FixtureReviewSource(FIXTURES), MockLLMProvider())
    return transform_comment_output(analyses, catalog, seqn=seqn)


def test_three_products_map_in_configuration_order_and_validate_contract() -> None:
    result = fixture_result()
    catalog = load_product_catalog(CATALOG)

    assert [row.product_name for row in result.rows] == [
        product.product_name for product in catalog.products
    ]
    assert len(result.rows) == len(result.evidence) == 3
    assert all(row.vendor.value == "amazon" for row in result.rows)
    assert all(item.status == "success" for item in result.evidence)
    assert all(item.analyzed_review_count == 6 for item in result.evidence)
    for row in result.rows:
        CommentRow.model_validate(row.model_dump(by_alias=True))


def test_outputs_preserve_exact_headers_and_json_csv_business_content(tmp_path: Path) -> None:
    result = fixture_result()
    write_comment_outputs(result, tmp_path)

    assert {path.name for path in tmp_path.iterdir()} == {
        "comment.json",
        "comment.csv",
        "comment_evidence.json",
        "comment_summary.json",
    }
    json_rows = json.loads((tmp_path / "comment.json").read_text(encoding="utf-8"))
    with (tmp_path / "comment.csv").open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == sheet_headers(CommentRow)
        csv_rows = list(reader)
    assert csv_rows == json_rows
    assert list(json_rows[0]) == sheet_headers(CommentRow)


def test_evidence_contains_seqn_provenance_and_explicit_trend() -> None:
    result = fixture_result("pipeline-seqn")

    assert result.summary.seqn == "pipeline-seqn"
    for item in result.evidence:
        assert item.seqn == "pipeline-seqn"
        assert item.supporting_review_ids
        assert item.prompt_version == "reviews-v1"
        assert item.provider == "mock"
        assert isinstance(item.negative_trend_detected, bool)


def test_missing_duplicate_and_unknown_analyses_are_rejected() -> None:
    catalog = load_product_catalog(CATALOG)
    analyses = run_review_analysis(catalog, FixtureReviewSource(FIXTURES), MockLLMProvider())

    with pytest.raises(ValueError, match="Missing analysis"):
        transform_comment_output(analyses[:-1], catalog, seqn="fixed")
    with pytest.raises(ValueError, match="Duplicate analysis"):
        transform_comment_output([*analyses, analyses[0]], catalog, seqn="fixed")
    unknown = analyses[0].model_copy(update={"product_id": "unknown-product"})
    with pytest.raises(ValueError, match="unknown or disabled"):
        transform_comment_output([unknown, *analyses[1:]], catalog, seqn="fixed")


def test_insufficient_data_is_audited_but_not_emitted_as_successful_row() -> None:
    catalog = load_product_catalog(CATALOG)
    analyses = run_review_analysis(catalog, FixtureReviewSource(FIXTURES), MockLLMProvider())
    insufficient = analyses[0].model_copy(
        update={
            "negative_trend": NegativeTrend.INSUFFICIENT_EVIDENCE,
            "warnings": ["insufficient-data"],
        }
    )

    result = transform_comment_output([insufficient, *analyses[1:]], catalog, seqn="fixed")

    assert len(result.rows) == 2
    assert result.evidence[0].status == "insufficient_data"
    assert result.evidence[0].negative_trend_detected is None
    assert result.summary.insufficient_data_count == 1


def test_fixed_inputs_and_seqn_are_deterministic() -> None:
    assert fixture_result().model_dump_json() == fixture_result().model_dump_json()


def test_run_summary_seqn_loader_validates_context(tmp_path: Path) -> None:
    path = tmp_path / "run_summary.json"
    path.write_text('{"seqn":"from-pipeline"}', encoding="utf-8")
    assert load_seqn_from_run_summary(path) == "from-pipeline"

    path.write_text('{"stg_count":9}', encoding="utf-8")
    with pytest.raises(ValueError, match="non-empty string seqn"):
        load_seqn_from_run_summary(path)
